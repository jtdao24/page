"""SQLite is the durable cache; FAISS is a checksummed, replaceable artifact."""

import hashlib
import json
import os
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import numpy as np
import faiss

from page_core.vault import FileSystemVault, _decode, _read_regular_file, _require_real_directory
from .chunking import CHUNK_VERSION, chunk_markdown
from .embedding import MiniLM
from .scanner import scan


@dataclass
class IndexStatus:
    state: str = "idle"
    phase: str = "idle"
    completed: int = 0
    total: int = 0
    changed: int = 0
    skipped: int = 0
    embedded: int = 0
    reused: int = 0
    deleted: int = 0
    error: str | None = None


class IngestionIndex:
    """One writer per vault; readers share a lock with atomic cache publication.

    Opening recovers FAISS from SQLite without loading the embedding model.
    Worker threads own their SQLite connections. Failed scans/embeddings never
    publish partial note state. SQLite commits before artifact replacement, so a
    crash in that gap is repaired automatically on the next search/open.
    """

    def __init__(self, vault: FileSystemVault, embedder=None, *, budget: int = 254):
        if not 1 <= budget <= 254:
            raise ValueError("token budget must be between 1 and 254")
        self.vault = vault
        self.embedder = embedder if embedder is not None else MiniLM()
        self.budget = budget
        self.config = f"{CHUNK_VERSION}:{budget}:{self.embedder.key}:{self.embedder.dimension}"
        self.directory = vault.vault.root_path / ".page" / "ingestion"
        _require_real_directory(self.directory.parent)
        self.directory.mkdir(exist_ok=True)
        _require_real_directory(self.directory)
        self.database = self.directory / "chunks.sqlite3"
        self.artifact = self.directory / "vectors.faiss"
        self._lock = threading.RLock()
        self._status_lock = threading.Lock()
        self._writer = threading.Lock()
        self._status = IndexStatus()
        self._thread = None
        self._index = None
        self._generation = None
        self._check_paths()
        with self._publication_lock(), self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, digest TEXT NOT NULL,
                    device INTEGER NOT NULL, inode INTEGER NOT NULL, mtime_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vectors (
                    key TEXT PRIMARY KEY, vector BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE NOT NULL, note_id TEXT NOT NULL REFERENCES notes(id),
                    ordinal INTEGER NOT NULL, text TEXT NOT NULL,
                    start_byte INTEGER NOT NULL, end_byte INTEGER NOT NULL,
                    tokens INTEGER NOT NULL, headings TEXT NOT NULL,
                    start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
                    cache_key TEXT NOT NULL REFERENCES vectors(key)
                );
                CREATE INDEX IF NOT EXISTS chunks_note_ordinal ON chunks(note_id,ordinal);
            """)
            settings = dict(db.execute("SELECT key,value FROM settings"))
            if settings.get("vault_id", str(vault.vault.id)) != str(vault.vault.id):
                raise ValueError("index cache belongs to another vault")
            if settings.get("schema", "1") != "1":
                raise ValueError("unsupported ingestion cache schema")
            db.executemany("INSERT OR IGNORE INTO settings VALUES (?,?)", [
                ("schema", "1"), ("vault_id", str(vault.vault.id))])
            db.commit()
            self._recover(db)
            for row in db.execute("SELECT path,id FROM notes"):
                self.vault.note_identity(PurePosixPath(row[0]), restore=UUID(row[1]))

    def _check_paths(self):
        _require_real_directory(self.directory.parent)
        _require_real_directory(self.directory)
        for name in ("chunks.sqlite3", "chunks.sqlite3-journal", "chunks.sqlite3-wal",
                     "chunks.sqlite3-shm", "vectors.faiss", "writer.lock", "publication.lock"):
            path = self.directory / name
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError(f"unsafe index cache path: {path}")

    @contextmanager
    def _publication_lock(self):
        import fcntl

        self._check_paths()
        fd = os.open(self.directory / "publication.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    @contextmanager
    def _connect(self):
        self._check_paths()
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def status(self) -> dict:
        with self._status_lock:
            return asdict(self._status)

    def _progress(self, **values):
        with self._status_lock:
            for key, value in values.items():
                setattr(self._status, key, value)

    def start(self, *, rebuild: bool = False) -> bool:
        """Start background work; return False when already indexing."""
        if not self._writer.acquire(blocking=False):
            return False
        self._progress(state="running", phase="scanning", completed=0, total=0,
                       changed=0, skipped=0, embedded=0, reused=0, deleted=0, error=None)
        self._thread = threading.Thread(target=self._run, args=(rebuild,), daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None):
        if self._thread:
            self._thread.join(timeout)

    def update(self, *, rebuild: bool = False) -> dict:
        """Synchronous indexing for scripts and benchmarks; surface errors."""
        if not self._writer.acquire(blocking=False):
            raise RuntimeError("indexing already running")
        self._progress(state="running", phase="scanning", completed=0, total=0,
                       changed=0, skipped=0, embedded=0, reused=0, deleted=0, error=None)
        self._run(rebuild)
        status = self.status()
        if status["state"] == "error":
            raise RuntimeError(status["error"])
        return status

    def _run(self, rebuild):
        try:
            self._update(rebuild)
            self._progress(state="complete", phase="idle")
        except Exception as exc:
            self._progress(state="error", phase="idle", error=f"{type(exc).__name__}: {exc}")
        finally:
            self._writer.release()

    def _update(self, rebuild):
        # An OS advisory lock also excludes independent processes on macOS.
        import fcntl

        lock_path = self.directory / "writer.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            documents = scan(self.vault.vault.root_path)
            self._progress(total=len(documents), phase="chunking")
            with self._connect() as db:
                old = {r["path"]: dict(r) for r in db.execute("SELECT * FROM notes")}
                settings = dict(db.execute("SELECT key,value FROM settings"))
                paths = {str(d.path) for d in documents}
                missing = [r for p, r in old.items() if p not in paths]
                available = {r["id"]: r for r in missing}
                incoming_digests = Counter(d.digest for d in documents if str(d.path) not in old)
                staged = []
                pending: dict[str, str] = {}
                cached: dict[str, bytes] = {}
                changed = skipped = reused = 0
                for count, doc in enumerate(documents, 1):
                    previous = old.get(str(doc.path))
                    if previous is None:
                        candidates = [r for r in available.values()
                                      if (r["device"], r["inode"]) == (doc.device, doc.inode)]
                        if len(candidates) != 1:
                            candidates = ([r for r in available.values() if r["digest"] == doc.digest]
                                          if incoming_digests[doc.digest] == 1 else [])
                        # Ambiguous copies get new identities rather than guessing.
                        previous = candidates[0] if len(candidates) == 1 else None
                        if previous:
                            available.pop(previous["id"])
                    note_id = UUID(previous["id"]) if previous else self.vault.note_identity(doc.path)
                    unchanged = previous and previous["digest"] == doc.digest and settings.get("config") == self.config and not rebuild
                    if unchanged:
                        chunks = None
                        skipped += 1
                    else:
                        changed += 1
                        chunks = chunk_markdown(note_id, doc.content, self.embedder.tokenizer, budget=self.budget)
                        for span in chunks:
                            key = hashlib.sha256((self.embedder.key + "\0" + span.chunk.text).encode()).hexdigest()
                            row = db.execute("SELECT vector FROM vectors WHERE key=?", (key,)).fetchone()
                            if row:
                                cached[key] = row[0]
                                reused += 1
                            else:
                                pending[key] = span.chunk.text
                    staged.append((doc, note_id, chunks))
                    self._progress(completed=count, changed=changed, skipped=skipped, reused=reused)
                self._progress(phase="embedding")
                keys = list(pending)
                for start in range(0, len(keys), 32):
                    batch = keys[start:start + 32]
                    vectors = np.asarray(self.embedder.encode([pending[k] for k in batch]), dtype="float32")
                    if vectors.shape != (len(batch), self.embedder.dimension) or not np.isfinite(vectors).all():
                        raise ValueError("invalid embedding shape or non-finite vectors")
                    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                    if (norms <= 0).any():
                        raise ValueError("zero embedding vector")
                    vectors /= norms
                    cached.update((key, vector.astype("<f4").tobytes()) for key, vector in zip(batch, vectors))
                    self._progress(embedded=start + len(batch))
                self._progress(phase="publishing", deleted=len(available))
                if (not rebuild and not available and settings.get("config") == self.config
                    and all(spans is None and str(doc.path) in old
                            and old[str(doc.path)]["id"] == str(note_id)
                            and old[str(doc.path)]["device"] == doc.device
                            and old[str(doc.path)]["inode"] == doc.inode
                            and old[str(doc.path)]["mtime_ns"] == doc.mtime_ns
                            for doc, note_id, spans in staged)):
                    return
                with self._lock, self._publication_lock():
                    db.execute("BEGIN IMMEDIATE")
                    for row in available.values():
                        db.execute("DELETE FROM chunks WHERE note_id=?", (row["id"],))
                        db.execute("DELETE FROM notes WHERE id=?", (row["id"],))
                    # Vacate old paths first so rename swaps cannot violate uniqueness.
                    for doc, note_id, chunks in staged:
                        db.execute("UPDATE notes SET path=? WHERE id=?", (f"@{note_id}", str(note_id)))
                    for key, value in cached.items():
                        db.execute("INSERT OR IGNORE INTO vectors VALUES (?,?)", (key, value))
                    for doc, note_id, spans in staged:
                        db.execute("""INSERT INTO notes VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                            path=excluded.path,digest=excluded.digest,device=excluded.device,
                            inode=excluded.inode,mtime_ns=excluded.mtime_ns""",
                            (str(note_id), str(doc.path), doc.digest, doc.device, doc.inode, doc.mtime_ns))
                        if spans is None:
                            continue
                        db.execute("DELETE FROM chunks WHERE note_id=?", (str(note_id),))
                        for span in spans:
                            c = span.chunk
                            key = hashlib.sha256((self.embedder.key + "\0" + c.text).encode()).hexdigest()
                            db.execute("""INSERT INTO chunks
                                (id,note_id,ordinal,text,start_byte,end_byte,tokens,headings,start_line,end_line,cache_key)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (str(c.id), str(note_id), c.ordinal,
                                c.text, c.start_byte, c.end_byte, c.token_count, json.dumps(span.headings),
                                span.start_line, span.end_line, key))
                    db.execute("DELETE FROM vectors WHERE key NOT IN (SELECT cache_key FROM chunks)")
                    generation = int(settings.get("generation", "0")) + 1
                    db.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", [
                        ("config", self.config), ("dimension", str(self.embedder.dimension)),
                        ("generation", str(generation)), ("checksum", "")])
                    db.commit()
                    self.vault.restore_note_identities({doc.path: note_id for doc, note_id, _ in staged})
                    self._rebuild(db)
        finally:
            os.close(fd)

    def _rebuild(self, db):
        faiss.omp_set_num_threads(1)
        settings = dict(db.execute("SELECT key,value FROM settings"))
        dimension = int(settings.get("dimension", str(self.embedder.dimension)))
        rows = list(db.execute("SELECT c.vector_id,v.vector FROM chunks c JOIN vectors v ON c.cache_key=v.key ORDER BY c.vector_id"))
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
        if rows:
            vectors = np.stack([np.frombuffer(r[1], dtype="<f4") for r in rows])
            if vectors.shape != (len(rows), dimension) or not np.isfinite(vectors).all():
                raise ValueError("invalid cached vectors; remove cache and reindex")
            index.add_with_ids(vectors, np.asarray([r[0] for r in rows], dtype="int64"))
        data = faiss.serialize_index(index).tobytes()
        self._check_paths()
        temporary = self.directory / f"vectors.{os.getpid()}.{threading.get_ident()}.tmp"
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.artifact)
        finally:
            temporary.unlink(missing_ok=True)
        db.execute("INSERT OR REPLACE INTO settings VALUES ('checksum',?)", (hashlib.sha256(data).hexdigest(),))
        db.commit()
        self._index = index
        self._generation = settings.get("generation")

    def _recover(self, db):
        settings = dict(db.execute("SELECT key,value FROM settings"))
        # A content checksum is checked BEFORE passing data to the native reader.
        try:
            self._check_paths()
            data = self.artifact.read_bytes()
            if hashlib.sha256(data).hexdigest() != settings.get("checksum"):
                raise ValueError("FAISS checksum mismatch")
            index = faiss.deserialize_index(np.frombuffer(data, dtype="uint8"))
            ids = [r[0] for r in db.execute("SELECT vector_id FROM chunks ORDER BY vector_id")]
            if index.d != int(settings.get("dimension", self.embedder.dimension)) or index.ntotal != len(ids) or sorted(faiss.vector_to_array(index.id_map).tolist()) != ids:
                raise ValueError("FAISS metadata mismatch")
            self._index = index
            self._generation = settings.get("generation")
        except (OSError, ValueError, RuntimeError, AttributeError):
            self._rebuild(db)

    def list_context(self) -> list[dict]:
        """Read committed note summaries for the bookshelf; never load a model.

        Metadata and excerpts describe the last successful indexing snapshot.
        Empty notes remain visible, and persisted UUIDs are the frontend keys.
        """
        with self._lock, self._publication_lock(), self._connect() as db:
            rows = db.execute("""SELECT n.id,n.path,n.mtime_ns,COUNT(c.vector_id) AS chunks,
                (SELECT text FROM chunks WHERE note_id=n.id ORDER BY ordinal LIMIT 1) AS text,
                (SELECT headings FROM chunks WHERE note_id=n.id ORDER BY ordinal LIMIT 1) AS headings
                FROM notes n LEFT JOIN chunks c ON c.note_id=n.id
                GROUP BY n.id ORDER BY n.path""")
            result = []
            for row in rows:
                headings = json.loads(row["headings"]) if row["headings"] else []
                text = row["text"] or ""
                # The complete source/provenance stays in chunk metadata.
                excerpt = "\n".join(line for line in text.splitlines()
                                    if not line.lstrip().startswith("#")).strip()[:320]
                result.append({"id": row["id"], "title": headings[0] if headings else PurePosixPath(row["path"]).stem,
                    "path": row["path"], "excerpt": excerpt, "chunks": row["chunks"],
                    "updated_at": datetime.fromtimestamp(row["mtime_ns"] / 1e9, tz=UTC).isoformat()})
            return result

    def read_context(self, note_id: str) -> dict:
        """Read a full current Markdown source by its committed index UUID.

        The reader never accepts filesystem paths from clients, caches source
        content, or loads the embedding model. Stage 3 path/UTF-8/no-follow
        checks apply. Bound reads to 1 MiB to keep the desktop reader responsive.
        """
        identifier = str(UUID(note_id))
        with self._lock, self._publication_lock(), self._connect() as db:
            row = db.execute("SELECT path FROM notes WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("unknown indexed note")
            path = PurePosixPath(row["path"])
            data, info = _read_regular_file(self.vault._existing_file(path), max_bytes=1024 * 1024)
            return {"id": identifier, "path": str(path), "content": _decode(data, path),
                    "updated_at": datetime.fromtimestamp(info.st_mtime_ns / 1e9, tz=UTC).isoformat()}

    def search(self, query: str, *, limit: int = 10) -> list[dict]:
        faiss.omp_set_num_threads(1)
        if not query.strip() or not 1 <= limit <= 100:
            raise ValueError("query must be nonblank and limit must be between 1 and 100")
        vector = np.asarray(self.embedder.encode([query]), dtype="float32")
        if vector.shape != (1, self.embedder.dimension) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
            raise ValueError("invalid query embedding")
        vector /= np.linalg.norm(vector)
        with self._lock, self._publication_lock(), self._connect() as db:
            settings = dict(db.execute("SELECT key,value FROM settings"))
            if settings.get("config") not in (None, self.config):
                raise ValueError("embedding configuration changed; reindex before search")
            if settings.get("generation") != self._generation:
                self._recover(db)
            if self._index.ntotal == 0:
                return []
            scores, ids = self._index.search(vector, min(limit, self._index.ntotal))
            results = []
            for score, identifier in zip(scores[0], ids[0]):
                row = db.execute("""SELECT c.*,n.path,n.digest AS source_digest FROM chunks c JOIN notes n ON c.note_id=n.id
                    WHERE c.vector_id=?""", (int(identifier),)).fetchone()
                if row:
                    result = {key: row[key] for key in (
                        "id", "note_id", "path", "ordinal", "text", "start_byte", "end_byte",
                        "tokens", "start_line", "end_line", "source_digest")}
                    result.update(score=float(score), headings=json.loads(row["headings"]))
                    results.append(result)
            return results
