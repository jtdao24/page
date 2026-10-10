"""Long-running semantic search for one vault.

``SearchRuntime`` loads the embedding model and the persisted index on a
background thread, keeps the index in step with the vault by re-syncing
periodically or on request, and serves searches. It is the piece a server, a
desktop backend or an agent integration runs; it has no FastAPI dependency.
"""

import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from uuid import UUID

from page_core.domain import Note
from page_core.embeddings.encoder import Embedder
from page_core.embeddings.index import IndexStats, SemanticIndex, SyncReport
from page_core.retrieval.semantic import SemanticSearchResult, SemanticSearchService
from page_core.vault import FileSystemVault, NoteNotFoundError, VaultError

logger = logging.getLogger(__name__)


def validate_sync_interval(seconds: object) -> float:
    """Return ``seconds`` if it is a finite number >= 0, else raise ``ValueError``.

    ``0`` means sync only at startup and on request.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        raise ValueError(f"sync interval must be a number of seconds, got {seconds!r}")
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"sync interval must be a finite number >= 0, got {seconds!r}")
    return float(seconds)


class RuntimeState(StrEnum):
    LOADING = "loading"
    """Loading the embedding model and the persisted index."""
    INDEXING = "indexing"
    """Building the index for the first time; searches are not served yet."""
    READY = "ready"
    ERROR = "error"


class SearchUnavailableError(RuntimeError):
    """The index cannot serve searches right now (still loading, or failed)."""

    def __init__(self, state: RuntimeState, message: str) -> None:
        super().__init__(message)
        self.state = state


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    state: RuntimeState
    searchable: bool
    detail: str | None
    stats: IndexStats | None
    last_sync_at: datetime | None
    last_sync: SyncReport | None


class SearchRuntime:
    """Semantic search over the vault at ``vault_root``.

    ``sync_interval`` is the number of seconds between background syncs;
    ``0`` syncs only at startup and when ``request_sync`` is called.
    """

    def __init__(
        self,
        vault_root: Path,
        embedder_factory: Callable[[], Embedder],
        *,
        sync_interval: float = 30.0,
    ) -> None:
        # The vault instance used to read notes for callers. FileSystemVault is not
        # thread-safe, so it is guarded by a lock; syncing uses its own instance.
        self._vault = FileSystemVault.open(vault_root)
        self._sync_vault = FileSystemVault.open(vault_root)
        self._vault_lock = threading.Lock()
        self._embedder_factory = embedder_factory
        self._sync_interval = validate_sync_interval(sync_interval)
        self._state = RuntimeState.LOADING
        self._detail: str | None = None
        self._searchable = False
        self._index: SemanticIndex | None = None
        self._service: SemanticSearchService | None = None
        self._last_sync_at: datetime | None = None
        self._last_sync: SyncReport | None = None
        self._settled = threading.Event()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def vault(self) -> FileSystemVault:
        return self._vault

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="page-search", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
        if self._index is not None:
            self._index.close()

    def wait_until_settled(self, timeout: float | None = None) -> bool:
        """Block until searches can be served or startup has failed."""
        return self._settled.wait(timeout)

    def request_sync(self) -> None:
        """Ask the background thread to sync soon."""
        self._wake.set()

    def status(self) -> RuntimeStatus:
        index = self._index
        return RuntimeStatus(
            state=self._state,
            searchable=self._searchable,
            detail=self._detail,
            stats=index.stats() if index is not None else None,
            last_sync_at=self._last_sync_at,
            last_sync=self._last_sync,
        )

    def sync_now(self) -> SyncReport:
        index = self._index
        if index is None:
            raise SearchUnavailableError(self._state, self._unavailable_message())
        report = index.sync(self._sync_vault)
        self._record_sync(report)
        # A successful sync proves the index is usable again, so recover from a
        # failed first build: serve searches and resume background syncing.
        self._mark_ready()
        self._resume_background(index)
        return report

    def search(self, query: str, limit: int) -> SemanticSearchResult:
        service = self._service
        if service is None or not self._searchable:
            raise SearchUnavailableError(self._state, self._unavailable_message())
        result = service.search(query, limit)
        if result.stale_paths:
            self.request_sync()
        return result

    def note_id_for(self, path: PurePosixPath) -> UUID | None:
        """The note's persistent index ID, or None if it is not indexed (yet)."""
        index = self._index
        return index.note_id_for(path) if index is not None else None

    def read_note(self, path: PurePosixPath) -> Note:
        with self._vault_lock:
            return self._vault.read_note(path)

    def _read_note_or_none(self, path: PurePosixPath) -> Note | None:
        try:
            return self.read_note(path)
        except (NoteNotFoundError, VaultError, ValueError):
            return None

    def _unavailable_message(self) -> str:
        if self._state is RuntimeState.ERROR:
            return f"semantic index failed: {self._detail}"
        if self._state is RuntimeState.INDEXING:
            return "the semantic index is being built for the first time"
        return "the embedding model and semantic index are still loading"

    def _record_sync(self, report: SyncReport) -> None:
        self._last_sync = report
        self._last_sync_at = datetime.now(UTC)
        if report.added or report.updated or report.removed:
            logger.info("semantic index synced: %s", report)

    def _run(self) -> None:
        try:
            embedder = self._embedder_factory()
            index = SemanticIndex.for_vault(self._vault.vault.root_path, embedder)
            self._index = index
            self._service = SemanticSearchService(index, embedder, self._read_note_or_none)
        except Exception as exc:
            logger.exception("semantic search failed to start")
            self._fail(exc)
            return
        if index.loaded_from_disk:
            # A persisted index serves searches while it catches up with the vault.
            self._searchable = True
            self._state = RuntimeState.READY
            self._settled.set()
        else:
            self._state = RuntimeState.INDEXING

        self._loop(index, first=True)

    def _loop(self, index: SemanticIndex, *, first: bool) -> None:
        while not self._stop.is_set():
            try:
                self._record_sync(index.sync(self._sync_vault))
                self._mark_ready()
            except Exception as exc:
                logger.exception("semantic index sync failed")
                if not self._searchable:
                    self._fail(exc)
                    return
                # Keep serving the last consistent index and report the failure.
                self._detail = f"last sync failed: {exc}"
            if first:
                self._settled.set()
                first = False
            self._wake.wait(self._sync_interval or None)
            self._wake.clear()

    def _mark_ready(self) -> None:
        self._searchable = True
        self._state = RuntimeState.READY
        self._detail = None

    def _resume_background(self, index: SemanticIndex) -> None:
        thread = self._thread
        if self._stop.is_set() or thread is None or thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, args=(index,), kwargs={"first": False},
            name="page-search", daemon=True,
        )
        self._thread.start()

    def _fail(self, exc: Exception) -> None:
        self._state = RuntimeState.ERROR
        self._detail = str(exc)
        self._settled.set()
