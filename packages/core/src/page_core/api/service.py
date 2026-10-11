"""Vault sessions and storage orchestration for the local API.

``LocalVaultService`` holds the session registry and performs every storage
operation. ``PersistentVault`` instances and their SQLite connections are not
thread-safe, so the service must be constructed and used on one thread: the
API's single storage worker. Arguments and results are domain/metadata values;
nothing here knows about HTTP.
"""

import hashlib
import json
import os
import secrets
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from page_core.domain import Note, SourceDocument, Vault
from page_core.semantic import FINGERPRINT, Encoder, IndexReport, SearchHit, SemanticIndex, SentenceEncoder
from page_core.context import ContextPackage, optimize_context
from page_core.graph import GraphSnapshot, build_graph
from page_core.sources import SourceEntry, SourceLibrary
from page_core.web import WebPage, note_for_page
from page_core.metadata import (
    InvalidRenameError, MetadataSyncError, NoteMetadata, PersistentVault, ReconcileResult,
)
from page_core.vault import FileSystemVault, InvalidNotePathError, NoteNotFoundError, VaultError


class InvalidSearchError(Exception):
    """A search query exceeds the model input bounds."""


class ServiceError(Exception):
    """A session-level refusal raised by ``LocalVaultService``."""


class VaultSessionNotFoundError(ServiceError):
    """No open session has this vault UUID."""


class VaultAlreadyOpenError(ServiceError):
    """Creation was requested for a root that is already an open vault."""


class VaultIdentityConflictError(ServiceError):
    """Another root with the same manifest UUID is already open."""


class InvalidVaultError(ServiceError):
    """The manifest or vault structure is invalid or unsupported."""


class NoteNotFoundInVaultError(ServiceError):
    """The UUID is not an active note of this vault."""


class RevisionConflictError(ServiceError):
    """The caller's revision is not the note's current revision."""


class ReconciliationRequiredError(ServiceError):
    """A partial success must be reconciled before note operations resume."""


class InvalidReconciliationError(ServiceError):
    """Known-rename confirmations were rejected by reconciliation."""


class StorageUnavailableError(ServiceError):
    """Private metadata storage is not supported on this platform."""


@dataclass(frozen=True, slots=True)
class VaultSession:
    """A snapshot of one open vault session."""

    vault: Vault
    needs_reconciliation: bool


class _Session:
    def __init__(self, storage: PersistentVault) -> None:
        self.storage = storage
        self.needs_reconciliation = False
        self.sources = SourceLibrary(storage.vault.root_path, storage.vault.id)

    def snapshot(self) -> VaultSession:
        return VaultSession(self.storage.vault, self.needs_reconciliation)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def note_revision(vault_id: UUID, note_id: UUID, path: PurePosixPath,
                  created_at: datetime, updated_at: datetime, content_digest: str) -> str:
    values = [str(vault_id), str(note_id), str(path), format_timestamp(created_at),
              format_timestamp(updated_at), content_digest]
    encoded = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def revision_of_note(note: Note) -> str:
    digest = hashlib.sha256(note.content.encode("utf-8")).hexdigest()
    return note_revision(note.vault_id, note.id, note.relative_path, note.created_at, note.updated_at, digest)


def revision_of_metadata(record: NoteMetadata) -> str:
    return note_revision(record.vault_id, record.id, record.relative_path,
                         record.created_at, record.updated_at, record.digest)


def metadata_storage_supported() -> bool:
    # Mirrors MetadataRepository's fail-closed platform check, so creation can
    # refuse before writing a root or manifest that metadata could never use.
    return os.name == "posix" and hasattr(os, "O_NOFOLLOW")


class LocalVaultService:
    """Open vault sessions keyed by manifest UUID, with resolved roots indexed.

    Construct and call on one thread only. The registry is session-only and
    starts empty; closing a session never deletes files.
    """

    def __init__(self) -> None:
        self._owner = threading.get_ident()
        self._sessions: dict[UUID, _Session] = {}
        self._roots: dict[Path, UUID] = {}
        self._encoder: Encoder | None = None

    def _check_thread(self) -> None:
        if threading.get_ident() != self._owner:
            raise RuntimeError("LocalVaultService must be used on its owning thread")

    def _session(self, vault_id: UUID) -> _Session:
        self._check_thread()
        if not isinstance(vault_id, UUID):
            raise TypeError(f"vault_id must be UUID, got {type(vault_id).__name__}")
        session = self._sessions.get(vault_id)
        if session is None:
            raise VaultSessionNotFoundError(str(vault_id))
        return session

    def _note_session(self, vault_id: UUID) -> _Session:
        session = self._session(vault_id)
        if session.needs_reconciliation:
            raise ReconciliationRequiredError(str(vault_id))
        return session

    def _register(self, storage: PersistentVault) -> VaultSession:
        session = _Session(storage)
        self._sessions[storage.vault.id] = session
        self._roots[storage.vault.root_path] = storage.vault.id
        return session.snapshot()

    def _registered_alias(self, root: Path, vault_id: UUID) -> _Session | None:
        session = self._sessions.get(vault_id)
        if session is None:
            return None
        try:
            same = os.path.samefile(root, session.storage.vault.root_path)
        except OSError:
            same = False
        return session if same else None

    def create_vault(self, root: Path, name: str) -> VaultSession:
        self._check_thread()
        if not isinstance(root, Path) or not isinstance(name, str):
            raise TypeError("root must be Path and name must be str")
        try:
            resolved = root.resolve()
        except (OSError, RuntimeError):
            resolved = None
        if resolved in self._roots:
            raise VaultAlreadyOpenError(str(self._roots[resolved]))
        if not metadata_storage_supported():
            raise StorageUnavailableError("private metadata storage is not supported here")
        with _invalid_vault_errors():
            storage = PersistentVault.create(root, name)
        return self._register(storage)

    def open_vault(self, root: Path) -> VaultSession:
        self._check_thread()
        if not isinstance(root, Path):
            raise TypeError(f"root must be Path, got {type(root).__name__}")
        try:
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError):
            resolved = None
        if resolved in self._roots:
            return self._sessions[self._roots[resolved]].snapshot()
        with _invalid_vault_errors():
            # Read-only manifest preflight: detects a cloned identity before any
            # metadata for the second root is initialized.
            manifest = FileSystemVault.open(root).vault
        existing = self._registered_alias(manifest.root_path, manifest.id)
        if existing is not None:
            return existing.snapshot()
        if manifest.id in self._sessions:
            raise VaultIdentityConflictError(str(manifest.id))
        with _invalid_vault_errors():
            storage = PersistentVault.open(root)
        if storage.vault.id in self._sessions or storage.vault.root_path in self._roots:
            # The manifest changed between preflight and open.
            storage.close()
            raise VaultIdentityConflictError(str(storage.vault.id))
        return self._register(storage)

    def list_vaults(self) -> list[VaultSession]:
        self._check_thread()
        sessions = [session.snapshot() for session in self._sessions.values()]
        return sorted(sessions, key=lambda item: (str(item.vault.root_path), str(item.vault.id)))

    def get_vault(self, vault_id: UUID) -> VaultSession:
        return self._session(vault_id).snapshot()

    def close_vault(self, vault_id: UUID) -> None:
        session = self._session(vault_id)
        del self._sessions[vault_id]
        del self._roots[session.storage.vault.root_path]
        session.storage.close()

    def reconcile(self, vault_id: UUID, known_renames: Mapping[UUID, PurePosixPath]) -> ReconcileResult:
        session = self._session(vault_id)
        # Corrupt stored records raise MetadataDecodeError, never InvalidRenameError.
        try:
            result = session.storage.reconcile(known_renames=dict(known_renames))
        except InvalidRenameError as exc:
            raise InvalidReconciliationError("invalid known rename") from exc
        session.needs_reconciliation = False
        return result

    def list_notes(self, vault_id: UUID) -> list[NoteMetadata]:
        session = self._note_session(vault_id)
        records = session.storage.metadata.list_notes()
        return sorted(records, key=lambda record: (str(record.relative_path), str(record.id)))

    def _read(self, session: _Session, note_id: UUID) -> Note:
        if not isinstance(note_id, UUID):
            raise TypeError(f"note_id must be UUID, got {type(note_id).__name__}")
        record = session.storage.metadata.get(note_id)
        if record is None or record.missing_since is not None:
            raise NoteNotFoundInVaultError(str(note_id))
        try:
            note = session.storage.read_note(record.relative_path)
        except NoteNotFoundError as exc:
            raise NoteNotFoundInVaultError(str(note_id)) from exc
        if note.id != note_id:
            raise NoteNotFoundInVaultError(str(note_id))
        return note

    def _current(self, session: _Session, note_id: UUID, revision: str) -> Note:
        if not isinstance(revision, str):
            raise TypeError(f"revision must be str, got {type(revision).__name__}")
        note = self._read(session, note_id)
        if not secrets.compare_digest(revision_of_note(note).encode("ascii"), revision.encode("ascii")):
            raise RevisionConflictError(str(note_id))
        return note

    @staticmethod
    def _mutate[T](session: _Session, action: Callable[[], T]) -> T:
        try:
            return action()
        except MetadataSyncError:
            session.needs_reconciliation = True
            raise

    def _semantic_snapshot(self, vault_id: UUID) -> tuple[_Session, tuple[Note, ...]]:
        session = self._note_session(vault_id)
        session.storage.reconcile()
        notes = tuple(self._read(session, record.id) for record in session.storage.metadata.list_notes())
        return session, notes

    @staticmethod
    def _documents(session: _Session, notes: tuple[Note, ...]) -> tuple[Note | SourceDocument, ...]:
        """Notes plus readable PDFs, code and text files in the vault folder."""
        return notes + session.sources.documents()

    @staticmethod
    def _revisions(documents: tuple[Note | SourceDocument, ...]) -> dict[UUID, str]:
        return {document.id: revision_of_note(document) if isinstance(document, Note) else document.revision
                for document in documents}

    def _semantic_encoder(self) -> Encoder:
        if self._encoder is None:
            self._encoder = SentenceEncoder()
        return self._encoder

    def index_vault(self, vault_id: UUID, rebuild: bool = False) -> IndexReport:
        if not isinstance(rebuild, bool):
            raise TypeError("rebuild must be bool")
        session, notes = self._semantic_snapshot(vault_id)
        documents = self._documents(session, notes)
        if not documents:
            previous = session.storage.metadata.read_vectors(FINGERPRINT)
            session.storage.metadata.replace_vectors(FINGERPRINT, [])
            return IndexReport(0, 0, 0, 0, len(previous))
        return SemanticIndex(session.storage.metadata, self._semantic_encoder()).update(documents, rebuild=rebuild)

    def search_vault(self, vault_id: UUID, query: str, limit: int = 10) -> tuple[SearchHit, ...]:
        session, notes = self._semantic_snapshot(vault_id)
        if not isinstance(query, str) or isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("query must be str and limit must be int")
        if not query.strip() or len(query) > 2000 or not 1 <= limit <= 50:
            raise InvalidSearchError("invalid search input")
        documents = self._documents(session, notes)
        if not documents:
            session.storage.metadata.replace_vectors(FINGERPRINT, [])
            return ()
        try:
            return SemanticIndex(session.storage.metadata, self._semantic_encoder()).search(
                query, documents, self._revisions(documents), limit)
        except ValueError as exc:
            raise InvalidSearchError("invalid search input") from exc

    def question_context(self, vault_id: UUID, question: str, budget: int,
                         candidates: int = 10) -> ContextPackage:
        """Optimized context for a question, ranked by embedding cosine similarity.

        The evaluation found the learned reranker does not yet generalize, so it is not used.
        """
        session, notes = self._semantic_snapshot(vault_id)
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise InvalidSearchError("invalid question")
        graph = build_graph(vault_id, notes)
        documents = self._documents(session, notes)
        if not documents:
            session.storage.metadata.replace_vectors(FINGERPRINT, [])
            return optimize_context(question, (), graph, budget=budget)
        try:
            hits = SemanticIndex(session.storage.metadata, self._semantic_encoder()).search(
                question, documents, self._revisions(documents), candidates)
        except ValueError as exc:
            raise InvalidSearchError("invalid question") from exc
        return optimize_context(question, hits, graph, budget=budget)

    def list_sources(self, vault_id: UUID) -> list[SourceEntry]:
        return self._note_session(vault_id).sources.list()

    def get_source(self, vault_id: UUID, source_id: UUID) -> SourceDocument:
        if not isinstance(source_id, UUID):
            raise TypeError(f"source_id must be UUID, got {type(source_id).__name__}")
        return self._note_session(vault_id).sources.get(source_id)

    def save_web_page(self, vault_id: UUID, page: WebPage, saved_at: datetime) -> Note:
        """Create a note for a fetched page, adding -2, -3 … if the name is taken."""
        if not isinstance(page, WebPage):
            raise TypeError("page must be WebPage")
        path, content = note_for_page(page, saved_at)
        taken = {record.relative_path for record in self.list_notes(vault_id)}
        candidate, number = path, 2
        while candidate in taken:
            candidate = path.with_name(f"{path.stem}-{number}.md")
            number += 1
        return self.create_note(vault_id, candidate, content)

    def get_graph(self, vault_id: UUID) -> GraphSnapshot:
        session = self._note_session(vault_id)
        # Reconcile external file changes before resolving references. Canonical
        # IDs come only from PersistentVault; note files are never rewritten.
        session.storage.reconcile()
        records = session.storage.metadata.list_notes()
        notes = tuple(self._read(session, record.id) for record in records)
        return build_graph(vault_id, notes)

    def get_note(self, vault_id: UUID, note_id: UUID) -> Note:
        return self._read(self._note_session(vault_id), note_id)

    def create_note(self, vault_id: UUID, path: PurePosixPath, content: str) -> Note:
        session = self._note_session(vault_id)
        # Decode every stored record first, like the other mutations do through
        # _current, so corrupt metadata is reported before any file is written.
        session.storage.metadata.list_notes()
        return self._mutate(session, lambda: session.storage.create_note(path, content))

    def update_note(self, vault_id: UUID, note_id: UUID, revision: str, content: str) -> Note:
        session = self._note_session(vault_id)
        note = self._current(session, note_id, revision)
        return self._mutate(session, lambda: session.storage.update_note(note, content))

    def move_note(self, vault_id: UUID, note_id: UUID, revision: str, path: PurePosixPath) -> Note:
        session = self._note_session(vault_id)
        note = self._current(session, note_id, revision)
        return self._mutate(session, lambda: session.storage.move_note(note, path))

    def delete_note(self, vault_id: UUID, note_id: UUID, revision: str) -> None:
        session = self._note_session(vault_id)
        note = self._current(session, note_id, revision)
        self._mutate(session, lambda: session.storage.delete_note(note))

    def close(self) -> None:
        """Close every session, continuing past individual close failures."""
        self._check_thread()
        sessions = list(self._sessions.values())
        self._sessions.clear()
        self._roots.clear()
        failure: BaseException | None = None
        for session in sessions:
            try:
                session.storage.close()
            except Exception as exc:
                failure = failure or exc
        if failure is not None:
            raise failure


@contextmanager
def _invalid_vault_errors() -> Iterator[None]:
    # Only the base VaultError (invalid or unsupported manifest) and structural
    # path errors describe an invalid vault; specific subclasses pass through.
    try:
        yield
    except InvalidNotePathError as exc:
        raise InvalidVaultError("invalid vault") from exc
    except VaultError as exc:
        if type(exc) is not VaultError:
            raise
        raise InvalidVaultError("invalid vault") from exc
