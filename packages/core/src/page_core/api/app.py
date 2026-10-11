"""Application factory, lifespan, routes and transport adaptation.

Handlers validate the wire format, convert strings explicitly to UUID/path
values, and submit each complete storage operation to the application's single
storage worker thread. Health and request validation never wait for storage.
"""

import asyncio
import re
from datetime import UTC, datetime
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

import page_core
from page_core.answering import answer_question
from page_core.llm import ChatModel, GeminiModel, LLMNotConfiguredError
from page_core.semantic import FINGERPRINT
from page_core.domain import Note, source_kind
from page_core.web import fetch_page
from page_core.metadata import NoteMetadata, ReconcileResult

from .errors import ApiError, error_response, field_error, translate, validation_error
from .schemas import (
    AskRequest, AskResponse, AskSource, AskUsage,
    GraphResponse, GraphNodeResponse, GraphLinkResponse,
    IndexRequest, IndexResponse, SearchRequest, SearchResponse, SearchHitResponse,
    REQUEST_MODELS, CreateNoteRequest, CreateVaultRequest, ErrorResponse, HealthResponse,
    MoveNoteRequest, NoteResponse, NoteSummaryResponse, OpenVaultRequest, ReconcileRequest,
    ReconcileResponse, SourceResponse, SourceSummaryResponse, UpdateNoteRequest, VaultResponse,
    WebPageRequest, parse_note_path, parse_root, parse_uuid,
)
from .security import LocalAccessMiddleware, generate_token, validate_token
from .service import (
    LocalVaultService, VaultSession, format_timestamp, revision_of_metadata, revision_of_note,
)

PREFIX = "/api/v1"


def _kind(path: object) -> str:
    """``note`` for Markdown, otherwise the source kind (pdf, code, text)."""
    return source_kind(path) or "note"
_IF_MATCH = re.compile(r'"([0-9a-f]{64})"')


@dataclass(frozen=True, slots=True)
class _Storage:
    executor: ThreadPoolExecutor
    service: LocalVaultService


async def _submit[T](executor: ThreadPoolExecutor, job: Callable[[], T]) -> T:
    # Shielded: a disconnecting client never cancels submitted storage work,
    # and nothing is retried.
    future = asyncio.wrap_future(executor.submit(job))
    future.add_done_callback(_observe)
    return await asyncio.shield(future)


def _observe(future: "asyncio.Future[object]") -> None:
    # If the waiting request was cancelled, nobody reads this future's result.
    # Retrieve its exception so asyncio never logs the unsanitized error text;
    # requests that are still waiting report errors through the API as usual.
    if not future.cancelled():
        future.exception()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="page-storage")
    try:
        # Built on the worker so the service's owning thread is the worker.
        service = await _submit(executor, LocalVaultService)
        app.state.storage = _Storage(executor, service)
        try:
            yield
        finally:
            del app.state.storage
            # Queued behind all submitted work: in-flight operations finish,
            # then every vault closes on the thread that opened it.
            await _submit(executor, service.close)
    finally:
        executor.shutdown(wait=True)


async def _run[T](request: Request, operation: Callable[[LocalVaultService], T]) -> T:
    storage: _Storage = request.app.state.storage
    try:
        return await _submit(storage.executor, lambda: operation(storage.service))
    except Exception as exc:
        raise translate(exc) from None


async def _warm_sources(request: Request, vault_id: UUID) -> None:
    """Extract source text (slow for big PDFs) off the storage worker before a search.

    The worker then finds it cached, so note reads and saves aren't held up. Errors
    are left for the real request to report.
    """
    try:
        library = await _run(request, lambda service: service.source_library(vault_id))
        await asyncio.to_thread(library.documents)
    except Exception:
        return


def _path_uuid(name: str, value: str) -> UUID:
    try:
        return parse_uuid(value)
    except ValueError:
        raise field_error(["path", name], "invalid_uuid") from None


def _if_match(request: Request) -> str:
    values = request.headers.getlist("if-match")
    if not values:
        raise ApiError(428, "precondition_required", "This request requires an If-Match revision.")
    match = _IF_MATCH.fullmatch(values[0].strip(" \t")) if len(values) == 1 else None
    if match is None:
        raise field_error(["header", "If-Match"], "invalid_if_match")
    return match.group(1)


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    content_types = request.headers.getlist("content-type")
    media_type = content_types[0].split(";", 1)[0].strip().lower() if len(content_types) == 1 else None
    if media_type != "application/json":
        raise ApiError(415, "unsupported_media_type", "The request body must be application/json.")
    raw = await request.body()
    try:
        return model.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        fields = frozenset(model.model_fields)
        raise validation_error(exc.errors(include_input=False, include_context=False, include_url=False),
                               prefix=("body",), known_fields=fields) from None


def _json(model: BaseModel | list[Any], status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    content = [item.model_dump(mode="json") for item in model] if isinstance(model, list) else model.model_dump(mode="json")
    return JSONResponse(content, status_code=status, headers=headers)


def _vault(session: VaultSession) -> VaultResponse:
    vault = session.vault
    return VaultResponse(id=str(vault.id), name=vault.name, root_path=str(vault.root_path),
                         needs_reconciliation=session.needs_reconciliation)


def _summary(record: NoteMetadata) -> NoteSummaryResponse:
    return NoteSummaryResponse(
        id=str(record.id), vault_id=str(record.vault_id), relative_path=str(record.relative_path),
        created_at=format_timestamp(record.created_at), updated_at=format_timestamp(record.updated_at),
        revision=revision_of_metadata(record))


def _note(note: Note, status: int = 200, *, location: bool = False) -> JSONResponse:
    revision = revision_of_note(note)
    body = NoteResponse(
        id=str(note.id), vault_id=str(note.vault_id), relative_path=str(note.relative_path),
        created_at=format_timestamp(note.created_at), updated_at=format_timestamp(note.updated_at),
        revision=revision, content=note.content)
    headers = {"ETag": f'"{revision}"'}
    if location:
        headers["Location"] = f"{PREFIX}/vaults/{note.vault_id}/notes/{note.id}"
    return _json(body, status, headers)


def _reconcile_response(result: ReconcileResult) -> ReconcileResponse:
    return ReconcileResponse(added=result.added, modified=result.modified, renamed=result.renamed,
                             missing=result.missing, unchanged=result.unchanged)


def _errors(*statuses: int) -> dict[int | str, dict[str, Any]]:
    common = (400, 401, 403, 500)
    return {status: {"model": ErrorResponse, "description": "Error envelope"}
            for status in sorted(set(common + statuses))}


def _json_body(model: type[BaseModel]) -> dict[str, Any]:
    return {"requestBody": {"required": True, "content": {
        "application/json": {"schema": {"$ref": f"#/components/schemas/{model.__name__}"}}}}}


_IF_MATCH_PARAMETER = {
    "name": "If-Match", "in": "header", "required": True,
    "description": "Exactly one strong quoted revision from the note's ETag or summary.",
    "schema": {"type": "string", "pattern": '^"[0-9a-f]{64}"$'},
}


def _precondition(model: type[BaseModel] | None = None) -> dict[str, Any]:
    extra = _json_body(model) if model else {}
    return {**extra, "parameters": [_IF_MATCH_PARAMETER]}


def _allowed_methods(app: FastAPI, scope: dict[str, Any]) -> str:
    methods: set[str] = set()
    for route in app.router.routes:
        match, _ = route.matches({**scope, "method": ""})
        if match is not Match.NONE:
            methods |= getattr(route, "methods", None) or set()
    return ", ".join(sorted(methods))


def create_app(*, session_token: str | None = None, chat_model: ChatModel | None = None) -> FastAPI:
    """Build an application with its own credential, registry and worker.

    Nothing is opened, started or bound until the ASGI lifespan starts. Omit
    ``session_token`` to generate one from 32 random bytes. Omit ``chat_model``
    to use Gemini when ``GEMINI_API_KEY`` is set; questions are refused otherwise.
    """
    token = generate_token() if session_token is None else validate_token(session_token)
    if chat_model is None:
        try:
            chat_model = GeminiModel.from_environment()
        except ValueError:
            chat_model = None  # an invalid PAGE_GEMINI_MODEL leaves questions unavailable
    app = FastAPI(
        title="Page Core Local API",
        version=page_core.__version__,
        debug=False,
        docs_url=None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        openapi_url="/openapi.json",
        redirect_slashes=False,
        lifespan=_lifespan,
        # No request telemetry: it can record URLs, inputs and exception text.
        telemetry={"tracing": False, "metrics": False, "logs": False,
                   "operation_spans": False, "auto_configure": False},
    )
    app.add_middleware(LocalAccessMiddleware, token=token)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> Response:
        return error_response(exc)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 404:
            return error_response(ApiError(404, "route_not_found", "No route matches this path."))
        if exc.status_code == 405:
            return error_response(ApiError(405, "method_not_allowed", "This method is not allowed here.",
                                           headers={"Allow": _allowed_methods(app, dict(request.scope))}))
        return error_response(ApiError(exc.status_code, "http_error", "The request could not be processed."))

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError) -> Response:
        return error_response(validation_error(exc.errors()))

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes,
                                 description="Authenticated loopback API for Page vaults and notes.")
            components = schema.setdefault("components", {})
            schemas = components.setdefault("schemas", {})
            for model in REQUEST_MODELS:
                definition = model.model_json_schema(ref_template="#/components/schemas/{model}")
                schemas.update(definition.pop("$defs", {}))
                schemas[model.__name__] = definition
            components["securitySchemes"] = {"bearerAuth": {"type": "http", "scheme": "bearer"}}
            schema["security"] = [{"bearerAuth": []}]
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    @app.get(f"{PREFIX}/health", response_model=HealthResponse, responses=_errors())
    async def health() -> Response:
        return _json(HealthResponse(status="ok", version=page_core.__version__))

    @app.post(f"{PREFIX}/vaults", status_code=201, response_model=VaultResponse,
              responses=_errors(404, 409, 415, 422, 503), openapi_extra=_json_body(CreateVaultRequest))
    async def create_vault(request: Request) -> Response:
        body = await _body(request, CreateVaultRequest)
        root, name = parse_root(body.root_path), body.name
        session = await _run(request, lambda service: service.create_vault(root, name))
        return _json(_vault(session), 201, {"Location": f"{PREFIX}/vaults/{session.vault.id}"})

    @app.post(f"{PREFIX}/vaults/open", response_model=VaultResponse,
              responses=_errors(404, 409, 415, 422, 503), openapi_extra=_json_body(OpenVaultRequest))
    async def open_vault(request: Request) -> Response:
        root = parse_root((await _body(request, OpenVaultRequest)).root_path)
        session = await _run(request, lambda service: service.open_vault(root))
        return _json(_vault(session))

    @app.get(f"{PREFIX}/vaults", response_model=list[VaultResponse], responses=_errors())
    async def list_vaults(request: Request) -> Response:
        sessions = await _run(request, lambda service: service.list_vaults())
        return _json([_vault(session) for session in sessions])

    @app.get(f"{PREFIX}/vaults/{{vault_id}}", response_model=VaultResponse, responses=_errors(404, 422))
    async def get_vault(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        return _json(_vault(await _run(request, lambda service: service.get_vault(identifier))))

    @app.delete(f"{PREFIX}/vaults/{{vault_id}}", status_code=204, response_class=Response,
                responses=_errors(404, 422))
    async def close_vault(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        await _run(request, lambda service: service.close_vault(identifier))
        return Response(status_code=204)

    @app.post(f"{PREFIX}/vaults/{{vault_id}}/reconcile", response_model=ReconcileResponse,
              responses=_errors(404, 415, 422, 503), openapi_extra=_json_body(ReconcileRequest))
    async def reconcile(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        body = await _body(request, ReconcileRequest)
        renames = {parse_uuid(key): parse_note_path(value) for key, value in body.known_renames.items()}
        result = await _run(request, lambda service: service.reconcile(identifier, renames))
        return _json(_reconcile_response(result))

    @app.post(f"{PREFIX}/vaults/{{vault_id}}/index", response_model=IndexResponse,
              responses=_errors(404, 409, 415, 422, 503), openapi_extra=_json_body(IndexRequest))
    async def index_vault(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        body = await _body(request, IndexRequest)
        await _warm_sources(request, identifier)
        result = await _run(request, lambda service: service.index_vault(identifier, body.rebuild))
        return _json(IndexResponse(vault_id=str(identifier), model=FINGERPRINT,
            notes=result.notes, chunks=result.chunks, generated=result.generated,
            reused=result.reused, removed=result.removed))

    @app.post(f"{PREFIX}/vaults/{{vault_id}}/search", response_model=SearchResponse,
              responses=_errors(404, 409, 415, 422, 503), openapi_extra=_json_body(SearchRequest))
    async def search_vault(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        body = await _body(request, SearchRequest)
        await _warm_sources(request, identifier)
        hits = await _run(request, lambda service: service.search_vault(identifier, body.query, body.limit))
        return _json(SearchResponse(vault_id=str(identifier), model=FINGERPRINT,
            hits=[SearchHitResponse(chunk_id=str(hit.chunk.id), note_id=str(hit.chunk.note_id),
                relative_path=str(hit.relative_path), kind=_kind(hit.relative_path), revision=hit.revision,
                ordinal=hit.chunk.ordinal,
                text=hit.chunk.text, start_byte=hit.chunk.start_byte, end_byte=hit.chunk.end_byte,
                start_line=hit.start_line, end_line=hit.end_line, score=hit.score) for hit in hits]))

    @app.post(f"{PREFIX}/vaults/{{vault_id}}/ask", response_model=AskResponse,
              responses=_errors(404, 409, 415, 422, 429, 502, 503), openapi_extra=_json_body(AskRequest))
    async def ask(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        body = await _body(request, AskRequest)
        model = chat_model
        if model is None:
            raise translate(LLMNotConfiguredError("no API key"))
        # Context is built on the storage worker; the model call runs elsewhere so a
        # slow provider never blocks note editing.
        await _warm_sources(request, identifier)
        prepared = await _run(request, lambda service: service.question_context(
            identifier, body.question, body.budget))
        package = prepared.package
        try:
            answer = await asyncio.to_thread(answer_question, body.question, package, model)
        except Exception as exc:
            raise translate(exc) from None
        return _json(AskResponse(
            vault_id=str(identifier), model=answer.model, answer=answer.text,
            answered_by_model=answer.called_model, finish_reason=answer.finish_reason,
            sources=[AskSource(number=block.number, note_id=str(block.note_id),
                               relative_path=str(block.relative_path), kind=_kind(block.relative_path),
                               start_line=block.start_line,
                               end_line=block.end_line, text=block.text, excerpt=block.compressed)
                     for block in package.blocks],
            cited=[block.number for block in answer.citations],
            usage=AskUsage(context_tokens=package.usage.tokens, budget=package.usage.budget,
                           counter=package.usage.counter, input_tokens=answer.input_tokens,
                           output_tokens=answer.output_tokens, vault_tokens=prepared.vault_tokens)))

    @app.get(f"{PREFIX}/vaults/{{vault_id}}/sources", response_model=list[SourceSummaryResponse],
             responses=_errors(404, 409, 422, 503))
    async def list_sources(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        entries = await _run(request, lambda service: service.list_sources(identifier))
        return _json([SourceSummaryResponse(id=str(entry.id), relative_path=str(entry.relative_path),
                                            kind=entry.kind, size_bytes=entry.size_bytes) for entry in entries])

    @app.get(f"{PREFIX}/vaults/{{vault_id}}/sources/{{source_id}}", response_model=SourceResponse,
             responses=_errors(404, 409, 422, 503))
    async def get_source(request: Request, vault_id: str, source_id: str) -> Response:
        identifiers = _path_uuid("vault_id", vault_id), _path_uuid("source_id", source_id)
        source = await _run(request, lambda service: service.get_source(*identifiers))
        return _json(SourceResponse(id=str(source.id), vault_id=str(source.vault_id),
                                    relative_path=str(source.relative_path), kind=source.kind,
                                    revision=source.revision, content=source.content))

    @app.post(f"{PREFIX}/vaults/{{vault_id}}/web-pages", status_code=201, response_model=NoteResponse,
              responses=_errors(404, 409, 415, 422, 502, 503), openapi_extra=_json_body(WebPageRequest))
    async def save_web_page(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        body = await _body(request, WebPageRequest)
        # Fetch off the storage worker so a slow site never blocks note editing.
        try:
            page = await asyncio.to_thread(fetch_page, body.url)
        except Exception as exc:
            raise translate(exc) from None
        saved_at = datetime.now(UTC)
        note = await _run(request, lambda service: service.save_web_page(identifier, page, saved_at))
        return _note(note, 201, location=True)

    @app.get(f"{PREFIX}/vaults/{{vault_id}}/graph", response_model=GraphResponse,
             responses=_errors(404, 409, 422, 503))
    async def get_graph(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        graph = await _run(request, lambda service: service.get_graph(identifier))
        return _json(GraphResponse(
            vault_id=str(graph.vault_id),
            nodes=[GraphNodeResponse(id=str(node.id), relative_path=str(node.relative_path))
                   for node in graph.nodes],
            links=[GraphLinkResponse(source_note_id=str(edge.link.source_note_id),
                    target_reference=edge.link.target_reference,
                    target_note_id=str(edge.link.target_note_id) if edge.link.target_note_id else None,
                    alias=edge.alias, line=edge.line, unresolved_reason=edge.unresolved_reason)
                   for edge in graph.links]))

    @app.get(f"{PREFIX}/vaults/{{vault_id}}/notes", response_model=list[NoteSummaryResponse],
             responses=_errors(404, 409, 422, 503))
    async def list_notes(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        records = await _run(request, lambda service: service.list_notes(identifier))
        return _json([_summary(record) for record in records])

    @app.post(f"{PREFIX}/vaults/{{vault_id}}/notes", status_code=201, response_model=NoteResponse,
              responses=_errors(404, 409, 415, 422, 503), openapi_extra=_json_body(CreateNoteRequest))
    async def create_note(request: Request, vault_id: str) -> Response:
        identifier = _path_uuid("vault_id", vault_id)
        body = await _body(request, CreateNoteRequest)
        path, content = parse_note_path(body.relative_path), body.content
        note = await _run(request, lambda service: service.create_note(identifier, path, content))
        return _note(note, 201, location=True)

    @app.get(f"{PREFIX}/vaults/{{vault_id}}/notes/{{note_id}}", response_model=NoteResponse,
             responses=_errors(404, 409, 422, 503))
    async def get_note(request: Request, vault_id: str, note_id: str) -> Response:
        identifiers = _path_uuid("vault_id", vault_id), _path_uuid("note_id", note_id)
        return _note(await _run(request, lambda service: service.get_note(*identifiers)))

    @app.put(f"{PREFIX}/vaults/{{vault_id}}/notes/{{note_id}}", response_model=NoteResponse,
             responses=_errors(404, 409, 412, 415, 422, 428, 503), openapi_extra=_precondition(UpdateNoteRequest))
    async def update_note(request: Request, vault_id: str, note_id: str) -> Response:
        identifiers = _path_uuid("vault_id", vault_id), _path_uuid("note_id", note_id)
        revision = _if_match(request)
        content = (await _body(request, UpdateNoteRequest)).content
        return _note(await _run(request, lambda service: service.update_note(*identifiers, revision, content)))

    @app.post(f"{PREFIX}/vaults/{{vault_id}}/notes/{{note_id}}/move", response_model=NoteResponse,
              responses=_errors(404, 409, 412, 415, 422, 428, 503), openapi_extra=_precondition(MoveNoteRequest))
    async def move_note(request: Request, vault_id: str, note_id: str) -> Response:
        identifiers = _path_uuid("vault_id", vault_id), _path_uuid("note_id", note_id)
        revision = _if_match(request)
        path = parse_note_path((await _body(request, MoveNoteRequest)).relative_path)
        return _note(await _run(request, lambda service: service.move_note(*identifiers, revision, path)))

    @app.delete(f"{PREFIX}/vaults/{{vault_id}}/notes/{{note_id}}", status_code=204, response_class=Response,
                responses=_errors(404, 409, 412, 422, 428, 503), openapi_extra=_precondition())
    async def delete_note(request: Request, vault_id: str, note_id: str) -> Response:
        identifiers = _path_uuid("vault_id", vault_id), _path_uuid("note_id", note_id)
        revision = _if_match(request)
        await _run(request, lambda service: service.delete_note(*identifiers, revision))
        return Response(status_code=204)

    return app
