"""Versioned SQLite metadata. Markdown content is never stored here."""

import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from page_core.domain import Note, Vault
from page_core.vault import _require_managed_path, _require_real_directory


class MetadataError(Exception):
    """Invalid, unavailable, or incompatible metadata storage."""


class MetadataNotFoundError(MetadataError):
    """The requested metadata record does not exist."""


class MetadataDecodeError(MetadataError, ValueError):
    """A stored record could not be decoded into valid metadata.

    Raised for corrupt persisted values that satisfy the SQL constraints but
    not domain validation. It remains a ValueError for existing callers.
    """


@dataclass(frozen=True, slots=True)
class NoteMetadata:
    id: UUID
    vault_id: UUID
    relative_path: PurePosixPath
    created_at: datetime
    updated_at: datetime
    digest: str
    device: int
    inode: int
    size_bytes: int
    mtime_ns: int
    missing_since: datetime | None = None

    def __post_init__(self) -> None:
        Note(self.id, self.vault_id, self.relative_path, "", self.created_at, self.updated_at)
        _require_managed_path(self.relative_path)
        if not isinstance(self.digest, str):
            raise TypeError("digest must be str")
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("digest must be a lowercase SHA-256 hex digest")
        for name in ("device", "inode", "size_bytes", "mtime_ns"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be int")
            if name != "mtime_ns" and value < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.missing_since is not None:
            if not isinstance(self.missing_since, datetime):
                raise TypeError("missing_since must be datetime")
            if self.missing_since.utcoffset() is None:
                raise ValueError("missing_since must be timezone-aware")


# Execute each statement inside one transaction; executescript would implicitly
# commit and break migration rollback. Version 2 adds lookup/uniqueness indexes.
MIGRATIONS = (
    (
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)",
        "CREATE TABLE vaults (id TEXT PRIMARY KEY NOT NULL CHECK(length(id)=36), name TEXT NOT NULL CHECK(length(trim(name))>0))",
        """CREATE TABLE notes (
            id TEXT PRIMARY KEY NOT NULL CHECK(length(id)=36),
            vault_id TEXT NOT NULL REFERENCES vaults(id),
            relative_path TEXT NOT NULL CHECK(
                length(relative_path)>3 AND substr(relative_path,-3)='.md'
                AND substr(relative_path,1,1)<>'/' AND relative_path NOT LIKE '%//%'
                AND instr('/'||relative_path||'/', '/../')=0
                AND instr('/'||relative_path||'/', '/./')=0
                AND instr('/'||relative_path, '/.')=0
                AND instr(relative_path,char(92))=0 AND instr(relative_path,':')=0
                AND instr(relative_path,char(0))=0
            ),
            created_at TEXT NOT NULL CHECK(length(created_at)=32 AND substr(created_at,27)='+00:00' AND datetime(created_at) IS NOT NULL),
            updated_at TEXT NOT NULL CHECK(length(updated_at)=32 AND substr(updated_at,27)='+00:00' AND datetime(updated_at) IS NOT NULL AND updated_at>=created_at),
            digest TEXT NOT NULL CHECK(length(digest)=64 AND digest NOT GLOB '*[^0-9a-f]*'),
            device INTEGER NOT NULL CHECK(device>=0), inode INTEGER NOT NULL CHECK(inode>=0),
            size_bytes INTEGER NOT NULL CHECK(size_bytes>=0), mtime_ns INTEGER NOT NULL,
            missing_since TEXT CHECK(missing_since IS NULL OR
                (length(missing_since)=32 AND substr(missing_since,27)='+00:00' AND datetime(missing_since) IS NOT NULL))
        )""",
    ),
    (
        "CREATE UNIQUE INDEX notes_active_path ON notes(vault_id,relative_path) WHERE missing_since IS NULL",
        "CREATE INDEX notes_digest ON notes(vault_id,digest)",
        "CREATE INDEX notes_file_identity ON notes(vault_id,device,inode)",
        "CREATE INDEX notes_updated ON notes(vault_id,updated_at)",
    ),
    (
        # Derived, rebuildable embeddings. Markdown is never cached here.
        """CREATE TABLE semantic_vectors (
            chunk_id TEXT PRIMARY KEY NOT NULL,
            note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            fingerprint TEXT NOT NULL,
            vector BLOB NOT NULL
        )""",
    ),
    (
        # Vectors may also belong to read-only source documents (PDFs, code),
        # which are not notes, so drop the foreign key. Each update replaces the
        # whole snapshot, so no cascade is needed. Existing vectors are kept.
        """CREATE TABLE semantic_vectors_v4 (
            chunk_id TEXT PRIMARY KEY NOT NULL,
            note_id TEXT NOT NULL CHECK(length(note_id)=36),
            fingerprint TEXT NOT NULL,
            vector BLOB NOT NULL
        )""",
        "INSERT INTO semantic_vectors_v4 SELECT chunk_id,note_id,fingerprint,vector FROM semantic_vectors",
        "DROP TABLE semantic_vectors",
        "ALTER TABLE semantic_vectors_v4 RENAME TO semantic_vectors",
    ),
)
SCHEMA_VERSION = len(MIGRATIONS)


def _timestamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="microseconds") if value else None


def _private_directory(path: Path, *, create: bool = False) -> None:
    if create:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise MetadataError(f"metadata directory is not owned by this user: {path}")
        os.fchmod(fd, 0o700)
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
            raise MetadataError(f"cannot restrict metadata directory: {path}")
    finally:
        os.close(fd)


def _private_file(path: Path, *, create: bool = False) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if not create:
            return
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            return _private_file(path)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        return
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        raise MetadataError(f"unsafe metadata file: {path}")
    if stat.S_IMODE(info.st_mode) != 0o600:
        # Path-based no-follow chmod doesn't close a second descriptor and
        # therefore preserves any other live SQLite connection's POSIX locks.
        if os.chmod in os.supports_follow_symlinks:
            os.chmod(path, 0o600, follow_symlinks=False)
        else:
            # The parent is already owner-only and the entry was checked with
            # lstat. Retain the filesystem vault's trusted-owner assumption on platforms
            # without no-follow chmod; never open/close an existing DB inode.
            os.chmod(path, 0o600)
    _verify_private_file(path, required=True)


def _verify_private_file(path: Path, *, required: bool = False) -> None:
    # Never reopen/close a database or SHM inode while SQLite is connected:
    # POSIX close would release this process's SQLite fcntl locks on that inode.
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if required:
            raise
        return
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        raise MetadataError(f"unsafe metadata file: {path}")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise MetadataError("metadata file permissions changed; close and reopen to restrict them")


class MetadataRepository:
    """One vault's metadata database; use as a context manager or call close.

    Public writes commit individually, or participate in transaction/savepoint
    scopes. Instances are not thread-safe. Independent instances serialize
    writes through SQLite. Unknown schema versions fail without changing data.
    """

    def __init__(self, vault: Vault):
        if not isinstance(vault, Vault):
            raise TypeError("vault must be Vault")
        # chmod does not implement owner-only ACLs on Windows. Until an ACL
        # implementation is verified, fail closed rather than promise privacy.
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise MetadataError("private metadata storage currently requires POSIX permissions")
        self.vault = vault
        _require_real_directory(vault.root_path)
        root_info = vault.root_path.stat()
        if root_info.st_uid != os.geteuid() or root_info.st_mode & 0o022:
            raise MetadataError("vault root must be owned by this user and not writable by others")
        parent = vault.root_path / ".page"
        _require_real_directory(parent)
        _private_directory(parent)
        self.directory = parent / "metadata"
        _private_directory(self.directory, create=True)
        self.database = self.directory / "notes.sqlite3"
        self._directory_identity = (self.directory.stat().st_dev, self.directory.stat().st_ino)
        self._verify_files(create=True)
        self._database_identity = (self.database.stat().st_dev, self.database.stat().st_ino)
        self._db = sqlite3.connect(self.database, timeout=5, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._savepoint = 0
        try:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA synchronous=FULL")
            self._migrate()
            self._verify_files()
        except BaseException:
            self._db.close()
            raise

    def _verify_files(self, *, create: bool = False) -> None:
        _private_directory(self.directory.parent)
        _private_directory(self.directory)
        directory = self.directory.stat()
        if (directory.st_dev, directory.st_ino) != self._directory_identity:
            raise MetadataError("metadata directory was replaced; reopen the repository")
        if create:
            _private_file(self.database, create=True)
        else:
            _verify_private_file(self.database, required=True)
        database = self.database.stat(follow_symlinks=False)
        if hasattr(self, "_database_identity") and (database.st_dev, database.st_ino) != self._database_identity:
            raise MetadataError("metadata database was replaced; reopen the repository")
        for suffix in ("-journal", "-wal", "-shm"):
            path = Path(str(self.database) + suffix)
            if create:
                _private_file(path)
            else:
                _verify_private_file(path)

    def _migrate(self) -> None:
        with self.transaction():
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if not 0 <= version <= SCHEMA_VERSION:
                raise MetadataError(f"unsupported metadata schema version {version}")
            if version:
                history = [row[0] for row in self._db.execute("SELECT version FROM schema_migrations ORDER BY version")]
                if history != list(range(1, version + 1)):
                    raise MetadataError("metadata migration history does not match schema version")
                owners = [row[0] for row in self._db.execute("SELECT id FROM vaults")]
                if owners != [str(self.vault.id)]:
                    raise MetadataError("metadata belongs to another vault")
            elif self._db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise MetadataError("unversioned metadata database is not supported")
            for next_version in range(version + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[next_version - 1]:
                    self._db.execute(statement)
                self._db.execute("INSERT INTO schema_migrations VALUES (?,?)", (next_version, _timestamp(datetime.now(UTC))))
                self._db.execute(f"PRAGMA user_version={next_version}")
            self._db.execute("INSERT INTO vaults VALUES (?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name", (str(self.vault.id), self.vault.name))

    @contextmanager
    def transaction(self):
        self._verify_files()
        nested = self._db.in_transaction
        self._savepoint += 1
        savepoint = f"metadata_{self._savepoint}"
        self._db.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
        try:
            yield self
            self._verify_files()
            self._db.execute(f"RELEASE {savepoint}" if nested else "COMMIT")
        except BaseException:
            if nested:
                self._db.execute(f"ROLLBACK TO {savepoint}")
                self._db.execute(f"RELEASE {savepoint}")
            else:
                self._db.rollback()
            raise

    def _check_record(self, record: NoteMetadata) -> None:
        if not isinstance(record, NoteMetadata):
            raise TypeError("record must be NoteMetadata")
        if record.vault_id != self.vault.id:
            raise ValueError("record belongs to another vault")

    @staticmethod
    def _id(identifier: UUID) -> str:
        if not isinstance(identifier, UUID):
            raise TypeError("note id must be UUID")
        return str(identifier)

    @staticmethod
    def _values(record: NoteMetadata) -> tuple:
        return (str(record.id), str(record.vault_id), str(record.relative_path),
                _timestamp(record.created_at), _timestamp(record.updated_at), record.digest,
                record.device, record.inode, record.size_bytes, record.mtime_ns,
                _timestamp(record.missing_since))

    @staticmethod
    def _record(row: sqlite3.Row | None) -> NoteMetadata | None:
        if row is None:
            return None
        try:
            return NoteMetadata(UUID(row["id"]), UUID(row["vault_id"]), PurePosixPath(row["relative_path"]),
                                datetime.fromisoformat(row["created_at"]), datetime.fromisoformat(row["updated_at"]),
                                row["digest"], row["device"], row["inode"], row["size_bytes"], row["mtime_ns"],
                                datetime.fromisoformat(row["missing_since"]) if row["missing_since"] else None)
        except (TypeError, ValueError) as exc:
            raise MetadataDecodeError("stored note metadata is corrupt") from exc

    def get(self, identifier: UUID) -> NoteMetadata | None:
        return self._record(self._db.execute("SELECT * FROM notes WHERE id=? AND vault_id=?", (self._id(identifier), str(self.vault.id))).fetchone())

    def get_by_path(self, path: PurePosixPath) -> NoteMetadata | None:
        path = _require_managed_path(path)
        return self._record(self._db.execute("SELECT * FROM notes WHERE vault_id=? AND relative_path=? AND missing_since IS NULL", (str(self.vault.id), str(path))).fetchone())

    def list_notes(self, *, include_missing: bool = False) -> list[NoteMetadata]:
        condition = "" if include_missing else " AND missing_since IS NULL"
        return [self._record(row) for row in self._db.execute("SELECT * FROM notes WHERE vault_id=?" + condition + " ORDER BY relative_path,id", (str(self.vault.id),))]

    def insert(self, record: NoteMetadata) -> None:
        self._check_record(record)
        with self.transaction():
            self._db.execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)", self._values(record))

    def update(self, record: NoteMetadata) -> None:
        self._check_record(record)
        with self.transaction():
            previous = self.get(record.id)
            if previous is None:
                raise MetadataNotFoundError(f"unknown note id: {record.id}")
            if previous.created_at != record.created_at:
                raise ValueError("creation timestamp is immutable")
            values = self._values(record)
            self._db.execute("""UPDATE notes SET relative_path=?,created_at=?,updated_at=?,digest=?,
                device=?,inode=?,size_bytes=?,mtime_ns=?,missing_since=? WHERE id=? AND vault_id=?""", values[2:] + values[:2])

    def delete(self, identifier: UUID) -> None:
        with self.transaction():
            result = self._db.execute("DELETE FROM notes WHERE id=? AND vault_id=?", (self._id(identifier), str(self.vault.id)))
            if result.rowcount != 1:
                raise MetadataNotFoundError(f"unknown note id: {identifier}")

    def read_vectors(self, fingerprint: str) -> dict[str, bytes]:
        """Return cached embeddings for exactly one model/chunker contract."""
        if not isinstance(fingerprint, str):
            raise TypeError("fingerprint must be str")
        self._verify_files()
        return {row[0]: row[1] for row in self._db.execute(
            "SELECT chunk_id,vector FROM semantic_vectors WHERE fingerprint=?", (fingerprint,))}

    def replace_vectors(self, fingerprint: str, vectors: list[tuple[UUID, UUID, bytes]]) -> None:
        """Atomically replace the derived snapshot after all encoding succeeds."""
        if not isinstance(fingerprint, str) or not isinstance(vectors, list):
            raise TypeError("invalid vector snapshot types")
        for chunk_id, note_id, vector in vectors:
            if not isinstance(chunk_id, UUID) or not isinstance(note_id, UUID) or not isinstance(vector, bytes):
                raise TypeError("vectors require UUID identities and bytes")
        with self.transaction():
            self._db.execute("DELETE FROM semantic_vectors")
            self._db.executemany("INSERT INTO semantic_vectors VALUES (?,?,?,?)",
                [(str(chunk_id), str(note_id), fingerprint, vector) for chunk_id, note_id, vector in vectors])

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
