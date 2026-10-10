"""Persistent vector index of note chunks.

Vectors live in a FAISS ``IndexIDMap2(IndexFlatIP)``; note and chunk metadata
live in SQLite. Both are stored under ``<vault>/.page/index/`` and are derived
data: if they are missing, corrupt, inconsistent, or were built with another
model, the index resets itself and the next ``sync`` rebuilds it from the
Markdown files. See docs/semantic-retrieval.md.

Identifiers:

- ``note_id``: a UUID per indexed note, persisted here. It survives restarts,
  edits, and renames or moves that keep the note's content.
- ``chunk_id``: a UUID per chunk. It survives edits elsewhere in the note,
  moves within the note, renames of the note, and restarts.
- ``vector_id``: the FAISS label. Internal to this module.
"""

import hashlib
import logging
import os
import sqlite3
import stat
import threading
import time
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
_FORMAT = "3"
_EMBED_BATCH_NOTES = 32
_RACY_WINDOW_NS = 2_000_000_000

_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

logger = logging.getLogger(__name__)


class SemanticIndexError(Exception):
    """Base class for semantic index errors."""


class IndexIncompatibleError(SemanticIndexError):
    """A vector does not match the index's model or dimension."""


class IndexStorageError(SemanticIndexError):
    """An index folder or file is a symlink, a hard link, or the wrong kind of entry.

    The index never writes through links that could lead outside the vault,
    and it does not delete entries it did not create, so this needs the
    user's attention.
    """


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """A chunk returned by a vector search, with its similarity to the query."""

    chunk_id: UUID
    note_id: UUID
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
    moved: int
    removed: int
    unchanged: int
    failed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _NoteState:
    sha256: str
    size: int
    mtime_ns: int
    """-1 when the stored time cannot be trusted; the file is then hashed again."""
    device: int
    inode: int

    def matches(self, info: os.stat_result) -> bool:
        """True if the file is certainly unchanged since this state was recorded."""
        return (
            self.mtime_ns >= 0
            and (self.size, self.mtime_ns, self.device, self.inode)
            == (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino)
        )


@dataclass(frozen=True, slots=True)
class _Known:
    note_id: str
    path: str
    state: _NoteState


@dataclass(frozen=True, slots=True)
class _Change:
    """A note whose chunks must be brought in line with ``content``."""

    note_id: str
    path: str
    state: _NoteState
    content: str
    retitled: bool
    """The note's path changed, so every chunk's embedding text changed."""


@dataclass(frozen=True, slots=True)
class _Plan:
    note_id: str
    path: str
    state: _NoteState
    keep: list[tuple[int, TextChunk]]
    """Stored chunks reused as they are: (vector_id, new position)."""
    add: list[tuple[TextChunk, str]]
    """Chunks to insert with a fresh vector: (chunk, chunk_id), the ID reused if possible."""
    vectors: np.ndarray
    """Embeddings for ``add``, row for row."""
    drop: list[int]
    """Vector IDs of stored chunk rows to delete."""


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

    def note_id_for(self, path: PurePosixPath) -> UUID | None:
        """The persistent ID of the note indexed at ``path``, if any."""
        with self._lock:
            row = self._conn.execute(
                "SELECT note_id FROM notes WHERE path = ?", (str(path),)
            ).fetchone()
        return UUID(row[0]) if row else None

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
                note_id=UUID(note_id),
                path=PurePosixPath(path),
                ordinal=ordinal,
                start_byte=start_byte,
                end_byte=end_byte,
                heading=heading,
                text=text,
                score=found[vector_id],
                vector_id=vector_id,
            )
            for vector_id, chunk_id, note_id, path, ordinal, start_byte, end_byte, heading, text
            in rows
        ]
        hits.sort(key=lambda hit: (-hit.score, hit.vector_id))
        return hits

    # --- Lifecycle ------------------------------------------------------------

    def sync(self, vault: FileSystemVault) -> SyncReport:
        """Bring the index in line with the vault's notes.

        - Only notes whose size or modification time changed are read, and only
          notes whose content hash changed are re-chunked.
        - Within a changed note, chunks whose text and heading are unchanged keep
          their ID and vector; only new chunks are embedded.
        - A new path whose content exactly matches a note that disappeared is a
          rename or move: the note keeps its ID and its chunks keep theirs.
        - Notes that no longer exist or can no longer be read are removed.

        ``vault`` must not be used by other threads during the call.
        """
        with self._sync_lock:
            root = vault.vault.root_path
            known = self._known()
            paths = vault.list_note_paths()
            current = {str(path) for path in paths}
            missing = {path: entry for path, entry in known.items() if path not in current}
            # Paths whose content changed (old entry) or that are new (None).
            changed: list[tuple[str, _Known | None, _NoteState, str]] = []
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
                        missing[key] = old
                    continue
                if old and old.state.matches(info):
                    unchanged += 1
                    continue
                try:
                    note = vault.read_note(path)
                except NoteNotFoundError:
                    if old:
                        missing[key] = old
                    continue
                except VaultError as exc:
                    logger.warning("skipping %s: %s", key, exc)
                    failed.append(key)
                    if old:
                        missing[key] = old
                    continue
                state = _state(note.content, info)
                if old is not None and old.state.sha256 == state.sha256:
                    touched.append((old.note_id, state))
                    unchanged += 1
                else:
                    changed.append((key, old, state, note.content))

            changes, moved, removed = _assign_identities(changed, missing)
            known_ids = {entry.note_id for entry in known.values()}
            added = sum(1 for change in changes if change.note_id not in known_ids)
            updated = len(changes) - added - moved

            # Removals go first and renamed notes give up their old paths, so every
            # path is free before any batch claims it.
            self._apply([], removed)
            self._park([change.note_id for change in changes if change.retitled])
            for batch in _batched(changes, _EMBED_BATCH_NOTES):
                self._apply(self._plan(batch), [])
            self._apply([], [], touched)
            self._save()
            return SyncReport(
                added=added,
                updated=updated,
                moved=moved,
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
        path = str(note.relative_path)
        data = note.content.encode("utf-8")
        state = _NoteState(hashlib.sha256(data).hexdigest(), len(data), -1, 0, 0)
        with self._sync_lock:
            entry = self._known().get(path)
            note_id = entry.note_id if entry else str(uuid4())
            self._apply(self._plan([_Change(note_id, path, state, note.content, False)]), [])
            self._save()

    def remove_note(self, path: PurePosixPath) -> None:
        with self._sync_lock:
            entry = self._known().get(str(path))
            if entry is not None:
                self._apply([], [entry.note_id])
                self._save()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- Storage ------------------------------------------------------------

    def _open_database(self) -> tuple[sqlite3.Connection, dict[str, str]]:
        """Connect to the metadata database, replacing it if it is corrupt.

        The database and its sidecar files are checked before connecting, and
        the database file is checked again afterwards to make sure SQLite
        opened the same file that passed the checks.
        """
        database = self._dir / DB_FILE
        for attempt in range(2):
            for suffix in _DB_SIDECARS:
                _require_safe_file(self._dir / f"{DB_FILE}{suffix}")
            before = _file_identity(database)
            conn = sqlite3.connect(database, check_same_thread=False, isolation_level=None)
            try:
                (check,) = conn.execute("PRAGMA quick_check").fetchone()
                if check != "ok":
                    raise sqlite3.DatabaseError(f"integrity check failed: {check}")
                conn.execute("PRAGMA foreign_keys = ON")
                has_meta = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
                ).fetchone()
                meta = (
                    dict(conn.execute("SELECT key, value FROM meta").fetchall())
                    if has_meta
                    else {}
                )
            except sqlite3.DatabaseError as exc:
                conn.close()
                if attempt:
                    raise
                self.reset_reason = f"metadata database was unreadable ({exc})"
                logger.warning("discarding semantic index: %s", self.reset_reason)
                self._discard_files()
                continue
            after = _file_identity(database)
            if after is None or (before is not None and before != after):
                conn.close()
                raise IndexStorageError(f"{database} changed while it was being opened")
            return conn, meta
        raise AssertionError("unreachable")

    def _discard_files(self) -> None:
        for name in (FAISS_FILE, *(f"{DB_FILE}{suffix}" for suffix in ("", *_DB_SIDECARS))):
            path = self._dir / name
            _require_safe_file(path)
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
        stored = [int(row[0]) for row in self._conn.execute("SELECT vector_id FROM chunks")]
        problem = _vector_index_problem(index, self.dimension, stored)
        if problem:
            self._reset(problem)
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
        _require_safe_file(target)
        temporary = self._dir / f".{FAISS_FILE}.{uuid4().hex}.tmp"
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW, 0o644
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # os.replace swaps the directory entry itself; it never writes through a link.
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    # --- Updates ------------------------------------------------------------

    def _known(self) -> dict[str, _Known]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT note_id, path, sha256, size, mtime_ns, device, inode FROM notes"
            ).fetchall()
        return {
            path: _Known(note_id, path, _NoteState(sha, size, mtime, device, inode))
            for note_id, path, sha, size, mtime, device, inode in rows
        }

    def _chunk_rows(self, vector_ids: list[int]) -> list[tuple]:
        if not vector_ids:
            return []
        marks = ",".join("?" * len(vector_ids))
        return self._conn.execute(
            "SELECT c.vector_id, c.chunk_id, c.note_id, n.path, c.ordinal, c.start_byte,"
            " c.end_byte, c.heading, c.text"
            " FROM chunks AS c JOIN notes AS n ON n.note_id = c.note_id"
            f" WHERE c.vector_id IN ({marks})",
            vector_ids,
        ).fetchall()

    def _park(self, note_ids: Sequence[str]) -> None:
        """Move notes to placeholder paths (NUL never appears in a note path)."""
        if not note_ids:
            return
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.executemany(
                    "UPDATE notes SET path = ? WHERE note_id = ?",
                    [("\x00" + note_id, note_id) for note_id in note_ids],
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _plan(self, changes: Sequence[_Change]) -> list[_Plan]:
        """Match new chunks to stored ones and embed only what changed.

        A stored chunk is matched when the new chunk has the same text and
        heading; matching is in document order, so repeated passages pair up
        in order. A matched chunk keeps its ID. It also keeps its vector unless
        the note was renamed, because the note title is part of the embedding
        text.
        """
        drafts = []
        texts: list[str] = []
        for change in changes:
            with self._lock:
                stored = self._conn.execute(
                    "SELECT vector_id, chunk_id, text, heading FROM chunks"
                    " WHERE note_id = ? ORDER BY ordinal",
                    (change.note_id,),
                ).fetchall()
            available: dict[tuple[str, str | None], deque[tuple[int, str]]] = defaultdict(deque)
            for vector_id, chunk_id, text, heading in stored:
                available[(text, heading)].append((vector_id, chunk_id))
            keep: list[tuple[int, TextChunk]] = []
            add: list[tuple[TextChunk, str]] = []
            drop: list[int] = []
            for chunk in chunk_markdown(change.content, max_chars=self._max_chunk_chars):
                matches = available.get((chunk.text, chunk.heading))
                if not matches:
                    add.append((chunk, str(uuid4())))
                    continue
                vector_id, chunk_id = matches.popleft()
                if change.retitled:
                    drop.append(vector_id)
                    add.append((chunk, chunk_id))
                else:
                    keep.append((vector_id, chunk))
            drop.extend(vector_id for ids in available.values() for vector_id, _ in ids)
            drafts.append((change, keep, add, drop))
            path = PurePosixPath(change.path)
            texts.extend(embedding_text(path, chunk) for chunk, _ in add)

        vectors = (
            normalize_rows(self._embedder.embed(texts), self.dimension)
            if texts
            else np.zeros((0, self.dimension), dtype=np.float32)
        )
        plans: list[_Plan] = []
        offset = 0
        for change, keep, add, drop in drafts:
            block = vectors[offset : offset + len(add)]
            offset += len(add)
            plans.append(_Plan(change.note_id, change.path, change.state, keep, add, block, drop))
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
                for note_id in removals:
                    old_ids.extend(
                        row[0]
                        for row in self._conn.execute(
                            "SELECT vector_id FROM chunks WHERE note_id = ?", (note_id,)
                        )
                    )
                    self._conn.execute("DELETE FROM chunks WHERE note_id = ?", (note_id,))
                    self._conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
                # Park this batch's notes too, so paths swapped within it cannot collide.
                self._conn.executemany(
                    "UPDATE notes SET path = ? WHERE note_id = ?",
                    [("\x00" + plan.note_id, plan.note_id) for plan in plans],
                )
                new_ids: list[int] = []
                for plan in plans:
                    state = plan.state
                    self._conn.execute(
                        "INSERT INTO notes (note_id, path, sha256, size, mtime_ns, device, inode)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)"
                        " ON CONFLICT(note_id) DO UPDATE SET path = excluded.path,"
                        " sha256 = excluded.sha256, size = excluded.size,"
                        " mtime_ns = excluded.mtime_ns, device = excluded.device,"
                        " inode = excluded.inode",
                        (
                            plan.note_id,
                            plan.path,
                            state.sha256,
                            state.size,
                            state.mtime_ns,
                            state.device,
                            state.inode,
                        ),
                    )
                    self._conn.executemany(
                        "DELETE FROM chunks WHERE vector_id = ?",
                        [(vector_id,) for vector_id in plan.drop],
                    )
                    old_ids.extend(plan.drop)
                    self._conn.executemany(
                        "UPDATE chunks SET ordinal = ?, start_byte = ?, end_byte = ?"
                        " WHERE vector_id = ?",
                        [
                            (chunk.ordinal, chunk.start_byte, chunk.end_byte, vector_id)
                            for vector_id, chunk in plan.keep
                        ],
                    )
                    for chunk, chunk_id in plan.add:
                        cursor = self._conn.execute(
                            "INSERT INTO chunks (chunk_id, note_id, ordinal, start_byte,"
                            " end_byte, heading, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                chunk_id,
                                plan.note_id,
                                chunk.ordinal,
                                chunk.start_byte,
                                chunk.end_byte,
                                chunk.heading,
                                chunk.text,
                            ),
                        )
                        new_ids.append(int(cursor.lastrowid))
                for note_id, state in touched:
                    self._conn.execute(
                        "UPDATE notes SET sha256 = ?, size = ?, mtime_ns = ?, device = ?,"
                        " inode = ? WHERE note_id = ?",
                        (
                            state.sha256,
                            state.size,
                            state.mtime_ns,
                            state.device,
                            state.inode,
                            note_id,
                        ),
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


def _state(content: str, info: os.stat_result) -> _NoteState:
    data = content.encode("utf-8")
    # File times advance in coarse ticks, so an edit made in the same tick as
    # this read could keep the same size and time. Like git's "racy" entries,
    # recently modified files are hashed again on the next sync.
    mtime_ns = info.st_mtime_ns
    if time.time_ns() - mtime_ns < _RACY_WINDOW_NS:
        mtime_ns = -1
    return _NoteState(hashlib.sha256(data).hexdigest(), len(data), mtime_ns, info.st_dev, info.st_ino)


def _assign_identities(
    changed: list[tuple[str, _Known | None, _NoteState, str]],
    missing: dict[str, _Known],
) -> tuple[list[_Change], int, list[str]]:
    """Decide which note ID each new or changed path carries.

    Identity follows exact content: a note whose stored content left its path
    (the path is gone, or now holds other content) is claimed by a path that
    now holds exactly that content. This covers renames, moves and swaps.
    Among several candidates, the same file (device and inode) wins, then the
    first by path, so the result is deterministic. Otherwise a changed path
    keeps its own note's ID, unless another path claimed it, and a new path
    gets a new ID. An edit combined with a rename between two syncs therefore
    yields a new note.

    Returns the changes, the number of moved notes and the removed note IDs.
    """
    sources = dict(missing)
    for key, old, _, _ in changed:
        if old is not None:
            sources[key] = old
    by_hash: dict[str, list[str]] = defaultdict(list)
    for path in sorted(sources):
        by_hash[sources[path].state.sha256].append(path)

    claims: dict[str, _Known] = {}
    claimed: set[str] = set()
    for key, _, state, _ in sorted(changed, key=lambda item: item[0]):
        candidates = [
            path for path in by_hash.get(state.sha256, []) if path != key and path not in claimed
        ]
        same_file = [
            path
            for path in candidates
            if sources[path].state.inode
            and (sources[path].state.device, sources[path].state.inode)
            == (state.device, state.inode)
        ]
        chosen = (same_file or candidates or [None])[0]
        if chosen is not None:
            claims[key] = sources[chosen]
            claimed.add(chosen)

    changes: list[_Change] = []
    for key, old, state, content in changed:
        if key in claims:
            changes.append(_Change(claims[key].note_id, key, state, content, retitled=True))
        elif old is not None and key not in claimed:
            changes.append(_Change(old.note_id, key, state, content, retitled=False))
        else:
            changes.append(_Change(str(uuid4()), key, state, content, retitled=False))
    # Any identity that no path carries any more is removed, including a changed
    # path's own note when that path took over another note's content.
    carried = {change.note_id for change in changes}
    removed = [entry.note_id for entry in sources.values() if entry.note_id not in carried]
    return changes, len(claims), removed


def _vector_index_problem(index: object, dimension: int, stored_ids: list[int]) -> str | None:
    """Why a loaded FAISS index cannot be used as this index, or None if it can."""
    if not isinstance(index, faiss.IndexIDMap2):
        return "vector file is not an ID-mapped FAISS index"
    base = faiss.downcast_index(index.index)
    if (
        not isinstance(base, faiss.IndexFlatIP)
        or base.metric_type != faiss.METRIC_INNER_PRODUCT
        or index.metric_type != faiss.METRIC_INNER_PRODUCT
    ):
        return "vector file does not use an exact inner-product index"
    if index.d != dimension or base.d != dimension:
        return f"vector file has dimension {index.d}, expected {dimension}"
    ids = faiss.vector_to_array(index.id_map).tolist()
    if len(ids) != index.ntotal or base.ntotal != index.ntotal:
        return "vector file ID map does not match its vector count"
    if len(set(ids)) != len(ids):
        return "vector file contains duplicate IDs"
    if len(ids) != len(stored_ids) or set(ids) != set(stored_ids):
        return "vector file and chunk metadata are out of step"
    return None


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            note_id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            device INTEGER NOT NULL,
            inode INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL UNIQUE,
            note_id TEXT NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            start_byte INTEGER NOT NULL,
            end_byte INTEGER NOT NULL,
            heading TEXT,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chunks_by_note ON chunks(note_id);
        """
    )


def _is_link(info: os.stat_result) -> bool:
    # On Windows, junctions and other reparse points are not reported as
    # symlinks but can still redirect outside the vault.
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_reparse_tag", 0))


def _require_real_directory(path: Path) -> None:
    info = os.lstat(path)
    if _is_link(info) or not stat.S_ISDIR(info.st_mode):
        raise IndexStorageError(f"{path} must be a directory, not a link or file")


def _prepare_directory(directory: Path) -> None:
    """Create the index folder inside a real ``.page`` folder, following no links."""
    _require_real_directory(directory.parent)
    try:
        os.mkdir(directory)
    except FileExistsError:
        pass
    _require_real_directory(directory)


def _check_file_info(path: Path, info: os.stat_result) -> None:
    if _is_link(info) or not stat.S_ISREG(info.st_mode):
        raise IndexStorageError(f"{path} must be a regular file, not a link or folder")
    if info.st_nlink > 1:
        # Another name for the same file may live outside the vault.
        raise IndexStorageError(f"{path} has other hard links; refusing to use it")


def _require_safe_file(path: Path) -> None:
    """Allow a missing file or a regular file with exactly one link."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    _check_file_info(path, info)


def _file_identity(path: Path) -> tuple[int, int] | None:
    """(device, inode) of a safe file, or None if it does not exist."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    _check_file_info(path, info)
    return info.st_dev, info.st_ino


def _read_regular_file(path: Path) -> bytes:
    _require_safe_file(path)
    fd = os.open(path, os.O_RDONLY | _O_BINARY | _O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        _check_file_info(path, os.fstat(stream.fileno()))
        return stream.read()


def _batched[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
