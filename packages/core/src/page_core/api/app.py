"""FastAPI application exposing semantic search and note reading.

Route handlers are plain ``def`` functions, so FastAPI runs them in its
threadpool and embedding, FAISS and file I/O never block the event loop.
"""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from page_core.api.schemas import (
    ChunkLocation,
    ErrorResponse,
    IndexStatusResponse,
    NoteResponse,
    SemanticSearchHit,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SyncReportBody,
)
from page_core.embeddings.encoder import (
    DEFAULT_MODEL,
    Embedder,
    EmbeddingError,
    SentenceTransformerEmbedder,
)
from page_core.embeddings.index import METRIC, IndexIncompatibleError, SyncReport
from page_core.retrieval.runtime import SearchRuntime, SearchUnavailableError
from page_core.retrieval.semantic import QueryValidationError
from page_core.vault import NoteNotFoundError, UnreadableNoteError, VaultError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# The Vite dev server and the Tauri webview origins on macOS and Windows.
ALLOWED_ORIGINS = [
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]


@dataclass(frozen=True, slots=True)
class Settings:
    vault_path: Path
    embedding_model: str = DEFAULT_MODEL
    sync_interval: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        vault = os.environ.get("PAGE_VAULT_PATH")
        if not vault:
            raise RuntimeError("set PAGE_VAULT_PATH to the vault folder")
        return cls(
            vault_path=Path(vault).expanduser(),
            embedding_model=os.environ.get("PAGE_EMBEDDING_MODEL", DEFAULT_MODEL),
            sync_interval=float(os.environ.get("PAGE_INDEX_SYNC_INTERVAL", "30")),
        )


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def create_app(
    settings: Settings | None = None,
    *,
    embedder_factory: Callable[[], Embedder] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    factory = embedder_factory or (lambda: SentenceTransformerEmbedder(settings.embedding_model))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = SearchRuntime(
            settings.vault_path, factory, sync_interval=settings.sync_interval
        )
        app.state.runtime = runtime
        runtime.start()
        try:
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="Page Core", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def runtime_of(request: Request) -> SearchRuntime:
        return request.app.state.runtime

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/index/status", response_model=IndexStatusResponse)
    def index_status(request: Request) -> IndexStatusResponse:
        runtime = runtime_of(request)
        status = runtime.status()
        stats = status.stats
        return IndexStatusResponse(
            state=status.state.value,
            searchable=status.searchable,
            detail=status.detail,
            vault_name=runtime.vault.vault.name,
            model=stats.model_id if stats else None,
            dimension=stats.dimension if stats else None,
            metric=METRIC,
            notes=stats.notes if stats else 0,
            chunks=stats.chunks if stats else 0,
            last_sync_at=status.last_sync_at,
            last_sync=_report_body(status.last_sync) if status.last_sync else None,
        )

    @app.post(
        "/api/index/sync",
        response_model=SyncReportBody,
        responses={503: {"model": ErrorResponse}},
    )
    def index_sync(request: Request) -> SyncReportBody:
        try:
            report = runtime_of(request).sync_now()
        except SearchUnavailableError as exc:
            raise _error(503, "index_unavailable", str(exc)) from exc
        except EmbeddingError as exc:
            raise _error(500, "embedding_failed", str(exc)) from exc
        return _report_body(report)

    @app.post(
        "/api/search/semantic",
        response_model=SemanticSearchResponse,
        responses={500: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    def semantic_search(body: SemanticSearchRequest, request: Request) -> SemanticSearchResponse:
        runtime = runtime_of(request)
        try:
            result = runtime.search(body.query, body.limit)
        except QueryValidationError as exc:
            raise _error(422, "invalid_query", str(exc)) from exc
        except SearchUnavailableError as exc:
            raise _error(503, "index_unavailable", str(exc)) from exc
        except IndexIncompatibleError as exc:
            raise _error(503, "index_incompatible", str(exc)) from exc
        except EmbeddingError as exc:
            raise _error(500, "embedding_failed", str(exc)) from exc
        stats = runtime.status().stats
        return SemanticSearchResponse(
            query=result.query,
            limit=result.limit,
            metric=METRIC,
            model=stats.model_id if stats else "",
            results=[
                SemanticSearchHit(
                    note_id=str(match.note_id),
                    path=str(match.path),
                    title=match.title,
                    score=match.score,
                    excerpt=match.excerpt,
                    chunk=ChunkLocation(
                        id=match.chunk_id,
                        ordinal=match.chunk_ordinal,
                        start_byte=match.start_byte,
                        end_byte=match.end_byte,
                        heading=match.heading,
                    ),
                    matched_chunks=match.matched_chunks,
                )
                for match in result.matches
            ],
        )

    @app.get(
        "/api/note",
        response_model=NoteResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def read_note(path: str, request: Request) -> NoteResponse:
        try:
            note = runtime_of(request).read_note(PurePosixPath(path))
        except NoteNotFoundError as exc:
            raise _error(404, "note_not_found", str(exc)) from exc
        except UnreadableNoteError as exc:
            raise _error(422, "note_unreadable", str(exc)) from exc
        except (VaultError, ValueError, TypeError) as exc:
            raise _error(400, "invalid_path", str(exc)) from exc
        return NoteResponse(
            id=str(note.id),
            path=str(note.relative_path),
            title=note.relative_path.stem,
            content=note.content,
            updated_at=note.updated_at,
        )

    return app


def _report_body(report: SyncReport) -> SyncReportBody:
    return SyncReportBody(
        added=report.added,
        updated=report.updated,
        removed=report.removed,
        unchanged=report.unchanged,
        failed=list(report.failed),
    )
