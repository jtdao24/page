"""Shared helpers for the local API tests (real vaults, SQLite and lifespan)."""

import asyncio
import os
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from page_core.api import create_app
from page_core.metadata import MetadataRepository

TOKEN = "PageTestToken_" + "x" * 29
BASE_URL = "http://127.0.0.1"
PEER = ("127.0.0.1", 50000)
AUTH = {"Authorization": f"Bearer {TOKEN}"}
API = "/api/v1"

posix_only = pytest.mark.skipif(os.name != "posix", reason="private metadata currently requires POSIX permissions")


def client_for(app: FastAPI, *, authenticated: bool = True) -> TestClient:
    return TestClient(app, base_url=BASE_URL, client=PEER, headers=dict(AUTH) if authenticated else None)


@pytest.fixture
def app() -> FastAPI:
    return create_app(session_token=TOKEN)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with client_for(app) as result:
        yield result


@pytest.fixture
def vault(client: TestClient, tmp_path: Path) -> dict[str, Any]:
    response = client.post(f"{API}/vaults", json={"root_path": str(tmp_path / "vault"), "name": "Research"})
    assert response.status_code == 201, response.text
    return response.json()


def notes_url(vault: dict[str, Any], note_id: str | None = None) -> str:
    url = f"{API}/vaults/{vault['id']}/notes"
    return url if note_id is None else f"{url}/{note_id}"


def create_note(client: TestClient, vault: dict[str, Any], path: str, content: str = "") -> dict[str, Any]:
    response = client.post(notes_url(vault), json={"relative_path": path, "content": content})
    assert response.status_code == 201, response.text
    return response.json()


def if_match(revision: str) -> dict[str, str]:
    return {"If-Match": f'"{revision}"'}


def assert_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    return body["error"]


def source_files(root: Path) -> dict[str, bytes]:
    """Every regular file under ``root`` except generated SQLite metadata."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink() and ".page/metadata" not in path.relative_to(root).as_posix()
    }


class StorageThreads:
    """Records which threads open and close SQLite connections."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.connected: list[int] = []
        self.closed: list[int] = []
        connect = sqlite3.connect
        close = MetadataRepository.close

        def spy_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            self.connected.append(threading.get_ident())
            return connect(*args, **kwargs)

        def spy_close(repository: MetadataRepository) -> None:
            self.closed.append(threading.get_ident())
            close(repository)

        monkeypatch.setattr(sqlite3, "connect", spy_connect)
        monkeypatch.setattr(MetadataRepository, "close", spy_close)


async def raw_request(app: FastAPI, scope: dict[str, Any]) -> tuple[int, dict[bytes, bytes], bytes]:
    """Call the ASGI app with a hand-built scope, for peers/headers a client cannot send."""
    messages: list[dict[str, Any]] = []
    base = {"type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": f"{API}/health", "raw_path": f"{API}/health".encode(), "root_path": "",
            "query_string": b"", "headers": [], "client": PEER, "server": ("127.0.0.1", 80)}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app({**base, **scope}, receive, send)
    start = messages[0]
    body = b"".join(message.get("body", b"") for message in messages[1:])
    return start["status"], dict(start["headers"]), body


def call_raw(app: FastAPI, scope: dict[str, Any]) -> tuple[int, dict[bytes, bytes], bytes]:
    return asyncio.run(raw_request(app, scope))
