"""HTTP API for the local Markdown vault and knowledge graph."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from page_core.models import (
    Backlink,
    GraphData,
    GraphEdge,
    GraphNode,
    Note,
    NoteCreate,
    NoteSummary,
    NoteUpdate,
)
from page_core.service import KnowledgeService
from page_core.vault import VaultError

DEFAULT_PORT = 8765


def default_vault_path() -> Path:
    override = os.environ.get("PAGE_VAULT_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Documents" / "Page"


def create_app(vault_path: Path | None = None) -> FastAPI:
    path = vault_path or default_vault_path()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service = KnowledgeService(path)
        app.state.service = service
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="Page Core", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "https://tauri.localhost",
            "http://tauri.localhost",
        ],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def service() -> KnowledgeService:
        return app.state.service

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/notes", response_model=list[NoteSummary])
    def list_notes() -> list[NoteSummary]:
        return [
            NoteSummary(id=note.id, title=note.title, path=note.path)
            for note in service().list_notes()
        ]

    @app.post("/api/notes", response_model=Note)
    def create_note(body: NoteCreate) -> Note:
        note = service().create_note(body.title, body.content)
        return Note(id=note.id, title=note.title, path=note.path, content=note.content)

    @app.get("/api/note", response_model=Note)
    def get_note(id: str) -> Note:
        try:
            note = service().get_note(id)
        except VaultError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Note not found.") from exc
        return Note(id=note.id, title=note.title, path=note.path, content=note.content)

    @app.put("/api/note", response_model=Note)
    def update_note(id: str, body: NoteUpdate) -> Note:
        try:
            note = service().update_note(id, body.content, body.title)
        except VaultError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Note not found.") from exc
        return Note(id=note.id, title=note.title, path=note.path, content=note.content)

    @app.delete("/api/note", status_code=204)
    def delete_note(id: str) -> None:
        try:
            service().delete_note(id)
        except VaultError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Note not found.") from exc

    @app.get("/api/note/backlinks", response_model=list[Backlink])
    def backlinks(id: str) -> list[Backlink]:
        try:
            records = service().backlinks(id)
        except VaultError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Note not found.") from exc
        return [
            Backlink(
                source_id=record.source_id,
                source_title=record.source_title,
                excerpt=record.excerpt,
                target_title=record.target_title,
            )
            for record in records
        ]

    @app.get("/api/graph", response_model=GraphData)
    def graph() -> GraphData:
        payload = service().graph()
        return GraphData(
            nodes=[GraphNode(**node) for node in payload.nodes],
            edges=[GraphEdge(**edge) for edge in payload.edges],
        )

    @app.post("/api/graph/rebuild", response_model=GraphData)
    def rebuild() -> GraphData:
        service().reindex()
        payload = service().graph()
        return GraphData(
            nodes=[GraphNode(**node) for node in payload.nodes],
            edges=[GraphEdge(**edge) for edge in payload.edges],
        )

    return app
