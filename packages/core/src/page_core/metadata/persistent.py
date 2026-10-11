"""Opt-in persistent identities around the unchanged filesystem vault operations."""

import hashlib
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from page_core.domain import Note
from page_core.vault import (
    FileSystemVault, _decode, _read_regular_file, _require_managed_path, _timestamps,
)

from .repository import MetadataError, MetadataNotFoundError, MetadataRepository, NoteMetadata


class MetadataSyncError(MetadataError):
    """A file operation committed, but its metadata update did not.

    The file remains the source of truth. Reconcile before further operations;
    for ambiguous moves, pass {note_id: current_path} as known_renames.
    """

    def __init__(self, operation: str, note_id: UUID, path: PurePosixPath):
        self.operation = operation
        self.note_id = note_id
        self.path = path
        super().__init__(f"{operation} changed the filesystem but metadata could not be saved; reconcile the vault")


class InvalidRenameError(ValueError):
    """Known-rename confirmations do not name a missing source and a unique existing destination."""


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    added: int = 0
    modified: int = 0
    renamed: int = 0
    missing: int = 0
    unchanged: int = 0


@dataclass(frozen=True, slots=True)
class _Source:
    path: PurePosixPath
    digest: str
    info: os.stat_result


class PersistentVault:
    """Filesystem vault operations with SQLite metadata, without parsing content.

    Create/open automatically reconcile existing files. Reconciliation is also
    explicit for external changes. Use as a context manager or call close.
    Instances are not thread-safe; do not mix snapshots from different instances.
    """

    def __init__(self, files: FileSystemVault, metadata: MetadataRepository):
        if not isinstance(files, FileSystemVault) or not isinstance(metadata, MetadataRepository):
            raise TypeError("files and metadata must be vault/repository instances")
        if files.vault.id != metadata.vault.id or files.vault.root_path != metadata.vault.root_path:
            raise ValueError("files and metadata must describe the same vault")
        self.files = files
        self.metadata = metadata
        self._restore_ids()

    @classmethod
    def create(cls, root: Path, name: str):
        return cls._open_files(FileSystemVault.create(root, name))

    @classmethod
    def open(cls, root: Path):
        return cls._open_files(FileSystemVault.open(root))

    @classmethod
    def _open_files(cls, files: FileSystemVault):
        metadata = MetadataRepository(files.vault)
        try:
            result = cls(files, metadata)
            result.reconcile()
            return result
        except BaseException:
            metadata.close()
            raise

    @property
    def vault(self):
        return self.files.vault

    def _restore_ids(self) -> None:
        # Keep already-issued filesystem vault UUIDs for notes not yet registered, on
        # every refresh, not only when attaching. A registered path takes its
        # stored ID, and known or retired IDs are never reused.
        registered = {record.relative_path: record.id for record in self.metadata.list_notes()}
        identities = {path: identifier for path, identifier in self.files._ids.items()
                      if path not in registered and self.metadata.get(identifier) is None}
        identities.update(registered)
        self.files.restore_note_identities(identities)

    def list_note_paths(self) -> list[PurePosixPath]:
        return self.files.list_note_paths()

    def _capture(self, path: PurePosixPath) -> tuple[_Source, bytes]:
        path = _require_managed_path(path)
        # Reuse the filesystem vault's path checks and no-follow regular-file reader. Hash
        # raw bytes; even unreadable UTF-8 notes can have metadata reconciled.
        data, info = _read_regular_file(self.files._existing_file(path))
        return _Source(path, hashlib.sha256(data).hexdigest(), info), data

    def _record(self, source: _Source, previous: NoteMetadata | None = None, *, identifier: UUID | None = None) -> NoteMetadata:
        created_at, updated_at = _timestamps(source.info)
        if previous:
            created_at = previous.created_at
        if previous is None and identifier is None:
            identifier = self.files.note_identity(source.path)
            if self.metadata.get(identifier) is not None:
                identifier = uuid4()
        return NoteMetadata(previous.id if previous else identifier, self.vault.id,
                            source.path, created_at, max(created_at, updated_at), source.digest,
                            source.info.st_dev, source.info.st_ino, source.info.st_size, source.info.st_mtime_ns)

    def read_note(self, path: PurePosixPath) -> Note:
        source, data = self._capture(path)
        content = _decode(data, source.path)
        with self.metadata.transaction():
            previous = self.metadata.get_by_path(source.path)
            record = self._record(source, previous)
            if previous is None:
                self.metadata.insert(record)
            elif record != previous:
                self.metadata.update(record)
        # Re-syncing identities lists every note, so only do it when this read changed
        # metadata or the in-memory ID disagrees; otherwise reading n notes costs n².
        if previous is None or record != previous or self.files._ids.get(source.path) != record.id:
            self._restore_ids()
        return Note(record.id, self.vault.id, source.path, content, record.created_at, record.updated_at)

    def _finish_write(self, note: Note, operation: str, previous: NoteMetadata | None) -> Note:
        try:
            source, data = self._capture(note.relative_path)
            record = self._record(source, previous, identifier=uuid4() if previous is None else None)
            with self.metadata.transaction():
                occupying = self.metadata.get_by_path(record.relative_path)
                if occupying and occupying.id != record.id:
                    self.metadata.update(replace(occupying, missing_since=datetime.now(UTC)))
                if previous:
                    self.metadata.update(record)
                else:
                    self.metadata.insert(record)
            self._restore_ids()
        except Exception as exc:
            raise MetadataSyncError(operation, previous.id if previous else note.id, note.relative_path) from exc
        return Note(record.id, self.vault.id, source.path, _decode(data, source.path), record.created_at, record.updated_at)

    def _existing(self, note: Note) -> NoteMetadata:
        if not isinstance(note, Note):
            raise TypeError("note must be Note")
        record = self.metadata.get(note.id)
        if record is None:
            raise MetadataNotFoundError(f"unknown note id: {note.id}")
        return record

    def create_note(self, path: PurePosixPath, content: str = "") -> Note:
        note = self.files.create_note(path, content)
        # Explicit creation always allocates a new independent identity, even
        # when a previously missing path still has metadata or an in-memory ID.
        return self._finish_write(note, "create", None)

    def update_note(self, note: Note, content: str) -> Note:
        previous = self._existing(note)
        return self._finish_write(self.files.update_note(note, content), "update", previous)

    def move_note(self, note: Note, new_path: PurePosixPath) -> Note:
        previous = self._existing(note)
        return self._finish_write(self.files.move_note(note, new_path), "move", previous)

    def rename_note(self, note: Note, new_name: str) -> Note:
        previous = self._existing(note)
        return self._finish_write(self.files.rename_note(note, new_name), "rename", previous)

    def delete_note(self, note: Note) -> None:
        previous = self._existing(note)
        self.files.delete_note(note)
        try:
            self.metadata.update(replace(previous, missing_since=datetime.now(UTC)))
            self._restore_ids()
        except Exception as exc:
            raise MetadataSyncError("delete", note.id, note.relative_path) from exc

    def reconcile(self, *, known_renames: Mapping[UUID, PurePosixPath] | None = None) -> ReconcileResult:
        """Publish one complete filesystem metadata snapshot transactionally.

        Existing paths keep their identities across atomic editor replacements.
        Unique unmatched, byte-identical files can be inferred as renames. No
        identity is guessed for ambiguous duplicates or edited external moves.
        Callers may explicitly confirm those moves with known_renames.
        Missing records remain tombstones and aren't automatically resurrected.
        """
        def fail(error: OSError):
            raise error

        paths = self.files.list_note_paths(on_error=fail)
        sources = {path: self._capture(path)[0] for path in paths}
        if paths != self.files.list_note_paths(on_error=fail):
            raise MetadataError("vault changed during reconciliation; retry")
        for path, source in sources.items():
            info = self.files._existing_file(path).stat(follow_symlinks=False)
            if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (source.info.st_dev, source.info.st_ino, source.info.st_size, source.info.st_mtime_ns):
                raise MetadataError("note changed during reconciliation; retry")
        confirmations = {} if known_renames is None else dict(known_renames)
        counts = dict(added=0, modified=0, renamed=0, missing=0, unchanged=0)
        with self.metadata.transaction():
            all_records = {record.id: record for record in self.metadata.list_notes(include_missing=True)}
            active = {record.relative_path: record for record in all_records.values() if record.missing_since is None}
            explicit: dict[PurePosixPath, NoteMetadata] = {}
            for identifier, path in confirmations.items():
                if not isinstance(identifier, UUID):
                    raise TypeError("known rename IDs must be UUIDs")
                path = _require_managed_path(path)
                record = all_records.get(identifier)
                if record is None or record.relative_path in sources or path not in sources or path in explicit:
                    raise InvalidRenameError("known renames require a missing source ID and a unique existing destination")
                explicit[path] = record
            used = {record.id for record in explicit.values()}
            missing = [record for path, record in active.items() if path not in sources and record.id not in used]
            incoming = Counter(source.digest for path, source in sources.items() if path not in active and path not in explicit)
            staged = {}
            for path, source in sources.items():
                previous = explicit.get(path) or active.get(path)
                if previous is None and incoming[source.digest] == 1:
                    matches = [record for record in missing if record.id not in used and record.digest == source.digest]
                    if len(matches) == 1:
                        previous = matches[0]
                record = self._record(source, previous)
                if record.id in staged:
                    raise MetadataError("duplicate allocated note identity")
                used.add(record.id)
                staged[record.id] = record
                if previous is None:
                    counts["added"] += 1
                elif previous.relative_path != path:
                    counts["renamed"] += 1
                    counts["modified"] += int(previous.digest != record.digest)
                elif previous == record:
                    counts["unchanged"] += 1
                else:
                    counts["modified"] += 1
            now = datetime.now(UTC)
            # Vacate changed paths before assigning destinations. All changes
            # remain invisible to other SQLite readers until the final commit.
            for record in active.values():
                next_record = staged.get(record.id)
                if next_record is None or next_record.relative_path != record.relative_path:
                    self.metadata.update(replace(record, missing_since=now))
                    counts["missing"] += int(next_record is None)
            for record in staged.values():
                previous = all_records.get(record.id)
                if previous is None:
                    self.metadata.insert(record)
                elif previous != record:
                    self.metadata.update(record)
        self._restore_ids()
        return ReconcileResult(**counts)

    def close(self) -> None:
        self.metadata.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
