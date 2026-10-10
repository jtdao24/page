"""Persistent vector index of note chunks.

Vectors live in a FAISS ``IndexIDMap2(IndexFlatIP)``; chunk and note metadata
live in SQLite. Both are stored under ``<vault>/.page/index/`` and are derived
data: if they are missing, corrupt, inconsistent, or were built with another
model, the index resets itself and the next ``sync`` rebuilds it from the
Markdown files. See docs/semantic-retrieval.md.

Each chunk has two identifiers. ``chunk_id`` is a UUID that callers may keep;
it survives edits elsewhere in the note and restarts. ``vector_id`` is the
FAISS label and stays internal to this module.
"""

import hashlib
import logging
import os
import sqlite3
import stat
import threading
from collections import defaultdict, deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import faiss
import numpy as np

from page_core.domain import Note
from page_core.embeddings.chunking import (
    DEFAULT_MAX_CHARS,
    TextChunk,
    chunk_markdown,
    embedding_text,
)
from page_core.embeddings.encoder import Embedder, normalize_rows
from page_core.vault import METADATA_DIR, FileSystemVault, NoteNotFoundError, VaultError

INDEX_DIR = "index"
FAISS_FILE = "chunks.faiss"
DB_FILE = "chunks.sqlite"
_DB_SIDECARS = ("-journal", "-wal", "-shm")
METRIC = "cosine"
_FORMAT = "2"
_EMBED_BATCH_NOTES = 32

_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

logger = logging.getLogger(__name__)


class SemanticIndexError(Exception):
    """Base class for semantic index errors."""


class IndexIncompatibleError(SemanticIndexError):
    """A vector does not match the index's model or dimension."""


class IndexStorageError(SemanticIndexError):
    """The index folder or one of its files is a symlink or not a regular entry.

    The index never follows links out of the vault, and it does not delete
    entries it did not create, so this needs the user's attention.
    """


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """A chunk returned by a vector search, with its similarity to the query."""

    chunk_id: UUID
    path: PurePosixPath
    ordinal: int
    start_byte: int
    end_byte: int
    heading: str | None
    text: str
    score: float
    vector_id: int


@dataclass(frozen=True, slots=True)
class IndexStats:
    notes: int
    chunks: int
    model_id: str
    dimension: int
    metric: str


@dataclass(frozen=True, slots=True)
class SyncReport:
    added: int
    updated: int
    removed: int
    unchanged: int
    failed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _NoteState:
    sha256: str
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class _Plan:
    """How to bring one note's stored chunks in line with its new content."""

    path: str
    state: _NoteState
    keep: list[tuple[int, TextChunk]]
    """Stored chunks whose text and heading are unchanged: (vector_id, new position)."""
    add: list[TextChunk]
    vectors: np.ndarray
    """Embeddings for ``add``, row for row."""
    drop: list[int]
    """Vector IDs of stored chunks that no longer exist."""


class SemanticIndex:
    """Chunk embeddings for one vault, kept in step with its Markdown files.

    Thread-safe. Searches and writes are serialized by one lock, so a search
    never sees FAISS and SQLite out of step. Embedding happens outside that
    lock, so searches continue while notes are being re-embedded.
    """

    def __init__(
        self,
        directory: Path,
        embedder: Embedder,
        *,
        max_chunk_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self._dir = directory
        self._embedder = embedder
        self._max_chunk_chars = max_chunk_chars
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self.reset_reason: str | None = None
        self.loaded_from_disk = False
        _prepare_directory(directory)
        self._conn, meta = self._open_database()
        self._index = self._empty_faiss()
        self._load(meta)

    @classmethod
    def for_vault(cls, vault_root: Path, embedder: Embedder, **kwargs: int) -> "SemanticIndex":
        return cls(vault_root / METADATA_DIR / INDEX_DIR, embedder, **kwargs)

    # --- Queries ------------------------------------------------------------

    @property
    def dimension(self) -> int:
        return self._embedder.dimension

    @property
    def model_id(self) -> str:
        return self._embedder.model_id

    def stats(self) -> IndexStats:
        with self._lock:
            (notes,) = self._conn.execute("SELECT COUNT(*) FROM notes").fetchone()
            return IndexStats(notes, self._index.ntotal, self.model_id, self.dimension, METRIC)

    def search(self, query_vector: np.ndarray, k: int) -> list[ChunkHit]:
        """Return up to ``k`` chunks by descending cosine similarity.

        Ties are broken by vector ID so the order is deterministic.
        """
        query = np.asarray(query_vector, dtype=np.float32)
        if query.shape != (1, self.dimension):
            raise IndexIncompatibleError(
                f"query vector has shape {query.shape}, index expects (1, {self.dimension})"
            )
        with self._lock:
            k = min(k, self._index.ntotal)
            if k <= 0:
                return []
            scores, ids = self._index.search(np.ascontiguousarray(query), k)
            found = {int(i): float(s) for i, s in zip(ids[0], scores[0]) if i != -1}
            rows = self._chunk_rows(list(found))
        hits = [
            ChunkHit(
                chunk_id=UUID(chunk_id),
                path=PurePosixPath(path),
                ordinal=ordinal,
                start_byte=start_byte,
                end_byte=end_byte,
                heading=heading,
                text=text,
                score=found[vector_id],
                vector_id=vector_id,
            )
            for vector_id, chunk_id, path, ordinal, start_byte, end_byte, heading, text in rows
        ]
        hits.sort(key=lambda hit: (-hit.score, hit.vector_id))
        return hits

    # --- Lifecycle ------------------------------------------------------------

    def sync(self, vault: FileSystemVault) -> SyncReport:
        """Bring the index in line with the vault's notes.

        Only notes whose size or modification time changed are read, and only
        notes whose content hash changed are re-chunked. Within a changed note,
        chunks whose text and heading are unchanged keep their ID and vector;
        only new chunks are embedded. Notes that no longer exist or can no
        longer be read are removed. ``vault`` must not be used by other threads
        during the call.
        """
        with self._sync_lock:
            root = vault.vault.root_path
            known = self._note_states()
            paths = vault.list_note_paths()
            current = {str(path) for path in paths}
            removed = [path for path in known if path not in current]
            pending: list[tuple[str, _NoteState, str]] = []
            touched: list[tuple[str, _NoteState]] = []
            failed: list[str] = []
            unchanged = 0
            for path in paths:
                key = str(path)
                old = known.get(key)
                try:
                    info = os.lstat(root.joinpath(*path.parts))
                except FileNotFoundError:
                    if old:
                        removed.append(key)
                    continue
                if old and old.size == info.st_size and old.mtime_ns == info.st_mtime_ns:
                    unchanged += 1
                    continue
                try:
                    note = vault.read_note(path)
                except NoteNotFoundError:
                    if old:
                        removed.append(key)
                    continue
                except VaultError as exc:
                    logger.warning("skipping %s: %s", key, exc)
                    failed.append(key)
                    if old:
                        removed.append(key)
                    continue
                data = note.content.encode("utf-8")
                state = _NoteState(hashlib.sha256(data).hexdigest(), len(data), info.st_mtime_ns)
                if old and old.sha256 == state.sha256:
                    touched.append((key, state))
                    unchanged += 1
                    continue
                pending.append((key, state, note.content))

            for batch in _batched(pending, _EMBED_BATCH_NOTES):
                self._apply(self._plan(batch), [])
            self._apply([], removed, touched)
            self._save()
            updated = sum(1 for key, _, _ in pending if key in known)
            return SyncReport(
                added=len(pending) - updated,
                updated=updated,
                removed=len(removed),
                unchanged=unchanged,
                failed=tuple(failed),
            )

    def index_note(self, note: Note) -> None:
        """Index one note's current content immediately.

        For callers that just wrote a note. The file's modification time is
        not recorded, so the next ``sync`` re-reads the file and compares its
        hash instead of trusting the stored state.
        """
        data = note.content.encode("utf-8")
        state = _NoteState(hashlib.sha256(data).hexdigest(), len(data), -1)
        with self._sync_lock:
            self._apply(self._plan([(str(note.relative_path), state, note.content)]), [])
            self._save()

    def remove_note(self, path: PurePosixPath) -> None:
        with self._sync_lock:
            self._apply([], [str(path)])
            self._save()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- Storage ------------------------------------------------------------

    def _open_database(self) -> tuple[sqlite3.Connection, dict[str, str]]:
        """Connect to the metadata database, replacing it if it is corrupt."""
        for attempt in range(2):
            for suffix in ("", *_DB_SIDECARS):
                _require_regular_or_missing(self._dir / f"{DB_FILE}{suffix}")
            conn = sqlite3.connect(
                self._dir / DB_FILE, check_same_thread=False, isolation_level=None
            )
            try:
                (check,) = conn.execute("PRAGMA quick_check").fetchone()
                if check != "ok":
                    raise sqlite3.DatabaseError(f"integrity check failed: {check}")
                conn.execute("PRAGMA foreign_keys = ON")
                _create_schema(conn)
                meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            except sqlite3.DatabaseError as exc:
                conn.close()
                if attempt:
                    raise
                self.reset_reason = f"metadata database was unreadable ({exc})"
                logger.warning("discarding semantic index: %s", self.reset_reason)
                self._discard_files()
                continue
            return conn, meta
        raise AssertionError("unreachable")

    def _discard_files(self) -> None:
        for name in (FAISS_FILE, *(f"{DB_FILE}{suffix}" for suffix in ("", *_DB_SIDECARS))):
            path = self._dir / name
            _require_regular_or_missing(path)
            path.unlink(missing_ok=True)

    def _expected_meta(self) -> dict[str, str]:
        return {
            "format": _FORMAT,
            "model_id": self.model_id,
            "dimension": str(self.dimension),
            "metric": METRIC,
            "max_chunk_chars": str(self._max_chunk_chars),
        }

    def _empty_faiss(self) -> faiss.IndexIDMap2:
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dimension))

    def _load(self, meta: dict[str, str]) -> None:
        if not meta:
            self._reset(self.reset_reason)
            return
        if meta != self._expected_meta():
            self._reset(f"index settings changed from {meta} to {self._expected_meta()}")
            return
        try:
            data = _read_regular_file(self._dir / FAISS_FILE)
            index = faiss.deserialize_index(np.frombuffer(data, dtype=np.uint8))
        except IndexStorageError:
            raise
        except Exception as exc:  # missing or unreadable vector file
            self._reset(f"vector file could not be loaded: {exc}")
            return
        if not isinstance(index, faiss.IndexIDMap2) or index.d != self.dimension:
            self._reset("vector file has an unexpected type or dimension")
            return
        stored = {int(row[0]) for row in self._conn.execute("SELECT vector_id FROM chunks")}
        if set(faiss.vector_to_array(index.id_map).tolist()) != stored:
            self._reset("vector file and chunk metadata are out of step")
            return
        self._index = index
        self.loaded_from_disk = True

    def _reset(self, reason: str | None) -> None:
        if reason:
            logger.warning("rebuilding semantic index: %s", reason)
        self.reset_reason = reason
        with self._lock:
            # Dropping the tables also migrates databases from older formats.
            self._conn.executescript(
                "DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS notes; DROP TABLE IF EXISTS meta;"
            )
            _create_schema(self._conn)
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.executemany(
                    "INSERT INTO meta (key, value) VALUES (?, ?)",
                    self._expected_meta().items(),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._index = self._empty_faiss()
            self._save()

    def _save(self) -> None:
        """Write the FAISS index atomically beside the SQLite metadata."""
        with self._lock:
            data = faiss.serialize_index(self._index).tobytes()
        target = self._dir / FAISS_FILE
        _require_regular_or_missing(target)
        temporary = self._dir / f".{FAISS_FILE}.{uuid4().hex}.tmp"
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW, 0o644
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # os.replace swaps the directory entry itself and never follows a link.
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    # --- Updates ------------------------------------------------------------

    def _note_states(self) -> dict[str, _NoteState]:
        with self._lock:
            rows = self._conn.execute("SELECT path, sha256, size, mtime_ns FROM notes").fetchall()
        return {path: _NoteState(sha, size, mtime) for path, sha, size, mtime in rows}

    def _chunk_rows(self, vector_ids: list[int]) -> list[tuple]:
        if not vector_ids:
            return []
        marks = ",".join("?" * len(vector_ids))
        return self._conn.execute(
            "SELECT vector_id, chunk_id, path, ordinal, start_byte, end_byte, heading, text "
            f"FROM chunks WHERE vector_id IN ({marks})",
            vector_ids,
        ).fetchall()

    def _plan(self, notes: Sequence[tuple[str, _NoteState, str]]) -> list[_Plan]:
        """Match new chunks to stored ones and embed only the new chunks.

        A chunk is reused when a stored chunk of the same note has the same
        text and heading, which also means the same embedding input. Matching
        is in document order, so repeated passages pair up in order.
        """
        drafts = []
        texts: list[str] = []
        for path, state, content in notes:
            with self._lock:
                stored = self._conn.execute(
                    "SELECT vector_id, text, heading FROM chunks WHERE path = ? ORDER BY ordinal",
                    (path,),
                ).fetchall()
            available: dict[tuple[str, str | None], deque[int]] = defaultdict(deque)
            for vector_id, text, heading in stored:
                available[(text, heading)].append(vector_id)
            keep: list[tuple[int, TextChunk]] = []
            add: list[TextChunk] = []
            for chunk in chunk_markdown(content, max_chars=self._max_chunk_chars):
                matches = available.get((chunk.text, chunk.heading))
                if matches:
                    keep.append((matches.popleft(), chunk))
                else:
                    add.append(chunk)
            drop = [vector_id for ids in available.values() for vector_id in ids]
            drafts.append((path, state, keep, add, drop))
            texts.extend(embedding_text(PurePosixPath(path), chunk) for chunk in add)

        vectors = (
            normalize_rows(self._embedder.embed(texts), self.dimension)
            if texts
            else np.zeros((0, self.dimension), dtype=np.float32)
        )
        plans: list[_Plan] = []
        offset = 0
        for path, state, keep, add, drop in drafts:
            block = vectors[offset : offset + len(add)]
            offset += len(add)
            plans.append(_Plan(path, state, keep, add, block, drop))
        return plans

    def _apply(
        self,
        plans: Sequence[_Plan],
        removals: Sequence[str],
        touched: Sequence[tuple[str, _NoteState]] = (),
    ) -> None:
        """Apply note changes to SQLite and FAISS as one step for searches."""
        if not plans and not removals and not touched:
            return
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                old_ids: list[int] = []
                for path in removals:
                    old_ids.extend(
                        row[0]
                        for row in self._conn.execute(
                            "SELECT vector_id FROM chunks WHERE path = ?", (path,)
                        )
                    )
                    self._conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
                    self._conn.execute("DELETE FROM notes WHERE path = ?", (path,))
                new_ids: list[int] = []
                for plan in plans:
                    state = plan.state
                    self._conn.execute(
                        "INSERT INTO notes (path, sha256, size, mtime_ns) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(path) DO UPDATE SET sha256 = excluded.sha256, "
                        "size = excluded.size, mtime_ns = excluded.mtime_ns",
                        (plan.path, state.sha256, state.size, state.mtime_ns),
                    )
                    self._conn.executemany(
                        "DELETE FROM chunks WHERE vector_id = ?",
                        [(vector_id,) for vector_id in plan.drop],
                    )
                    old_ids.extend(plan.drop)
                    self._conn.executemany(
                        "UPDATE chunks SET ordinal = ?, start_byte = ?, end_byte = ? "
                        "WHERE vector_id = ?",
                        [
                            (chunk.ordinal, chunk.start_byte, chunk.end_byte, vector_id)
                            for vector_id, chunk in plan.keep
                        ],
                    )
                    for chunk in plan.add:
                        cursor = self._conn.execute(
                            "INSERT INTO chunks (chunk_id, path, ordinal, start_byte, end_byte,"
                            " heading, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                str(uuid4()),
                                plan.path,
                                chunk.ordinal,
                                chunk.start_byte,
                                chunk.end_byte,
                                chunk.heading,
                                chunk.text,
                            ),
                        )
                        new_ids.append(int(cursor.lastrowid))
                for path, state in touched:
                    self._conn.execute(
                        "UPDATE notes SET sha256 = ?, size = ?, mtime_ns = ? WHERE path = ?",
                        (state.sha256, state.size, state.mtime_ns, path),
                    )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            try:
                if old_ids:
                    self._index.remove_ids(np.array(old_ids, dtype=np.int64))
                vectors = [plan.vectors for plan in plans if len(plan.vectors)]
                if vectors:
                    self._index.add_with_ids(
                        np.ascontiguousarray(np.vstack(vectors)),
                        np.array(new_ids, dtype=np.int64),
                    )
            except BaseException:
                # SQLite is committed but FAISS is not; start over rather than serve
                # mismatched results.
                self._reset("in-memory vector update failed")
                raise


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            path TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL UNIQUE,
            path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            start_byte INTEGER NOT NULL,
            end_byte INTEGER NOT NULL,
            heading TEXT,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chunks_by_path ON chunks(path);
        """
    )


def _require_real_directory(path: Path) -> None:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise IndexStorageError(f"{path} must be a directory, not a symlink or file")


def _prepare_directory(directory: Path) -> None:
    """Create the index folder inside a real ``.page`` folder, following no links."""
    _require_real_directory(directory.parent)
    try:
        os.mkdir(directory)
    except FileExistsError:
        pass
    _require_real_directory(directory)


def _require_regular_or_missing(path: Path) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise IndexStorageError(f"{path} must be a regular file, not a symlink or folder")


def _read_regular_file(path: Path) -> bytes:
    _require_regular_or_missing(path)
    fd = os.open(path, os.O_RDONLY | _O_BINARY | _O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise IndexStorageError(f"{path} must be a regular file")
        return stream.read()


def _batched[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
