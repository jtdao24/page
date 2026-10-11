"""Sources and web pages through the local API: listing, reading, search, ask."""
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_support import API, TOKEN, client, create_note, posix_only, vault
from page_core.api import create_app
from page_core.web import InvalidUrlError, WebFetchError, WebPage
from test_api_ask import FakeModel
from test_semantic import CountingEncoder
from test_sources import make_pdf

__all__ = ["client", "vault"]
pytestmark = posix_only


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def app(model, monkeypatch):
    from page_core.api import service
    encoder = CountingEncoder()
    monkeypatch.setattr(service, "SentenceEncoder", lambda: encoder)
    return create_app(session_token=TOKEN, chat_model=model)


def root(vault: dict[str, Any]) -> Path:
    return Path(vault["root_path"])


def add_files(vault: dict[str, Any]) -> None:
    (root(vault) / "papers").mkdir()
    (root(vault) / "papers" / "fruit-study.pdf").write_bytes(make_pdf(["fruit apples study results"]))
    (root(vault) / "code").mkdir()
    (root(vault) / "code" / "space.py").write_text("# space stars far away\nDISTANCE = 4.2\n")


def test_sources_are_listed_and_readable(client, vault):
    add_files(vault)
    create_note(client, vault, "plan.md", "a note, not a source")
    listed = client.get(f"{API}/vaults/{vault['id']}/sources")
    assert listed.status_code == 200, listed.text
    assert [(item["relative_path"], item["kind"]) for item in listed.json()] == [
        ("code/space.py", "code"), ("papers/fruit-study.pdf", "pdf")]
    pdf = listed.json()[1]
    read = client.get(f"{API}/vaults/{vault['id']}/sources/{pdf['id']}")
    assert read.status_code == 200
    body = read.json()
    assert body["content"] == "[Page 1]\nfruit apples study results\n" and body["kind"] == "pdf"
    assert len(body["revision"]) == 64
    missing = client.get(f"{API}/vaults/{vault['id']}/sources/{vault['id']}")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "source_not_found")
    (root(vault) / "bad.txt").write_bytes(b"\xff\xfe")
    bad = next(item for item in client.get(f"{API}/vaults/{vault['id']}/sources").json() if item["relative_path"] == "bad.txt")
    unreadable = client.get(f"{API}/vaults/{vault['id']}/sources/{bad['id']}")
    assert (unreadable.status_code, unreadable.json()["error"]["code"]) == (422, "source_unreadable")


def test_search_and_ask_include_sources_with_their_kind(client, vault, model):
    add_files(vault)
    note = create_note(client, vault, "fruit.md", "fruit apples are sweet")
    hits = client.post(f"{API}/vaults/{vault['id']}/search", json={"query": "fruit apples", "limit": 5}).json()["hits"]
    kinds = {hit["relative_path"]: hit["kind"] for hit in hits}
    assert kinds["papers/fruit-study.pdf"] == "pdf" and kinds["fruit.md"] == "note"
    pdf_hit = next(hit for hit in hits if hit["kind"] == "pdf")
    assert pdf_hit["note_id"] != note["id"] and pdf_hit["start_line"] >= 1
    answer = client.post(f"{API}/vaults/{vault['id']}/ask", json={"question": "fruit apples?", "budget": 500}).json()
    assert {source["kind"] for source in answer["sources"]} >= {"note", "pdf"}
    assert "papers/fruit-study.pdf" in model.calls[0]


def test_web_pages_are_saved_as_notes_with_unique_names(client, vault, monkeypatch):
    from page_core.api import app as app_module
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return WebPage("https://example.com/espresso", "Espresso Guide", "A double uses 18 g.\n")
    monkeypatch.setattr(app_module, "fetch_page", fake_fetch)
    first = client.post(f"{API}/vaults/{vault['id']}/web-pages", json={"url": "https://example.com/espresso"})
    assert first.status_code == 201, first.text
    assert first.json()["relative_path"] == "web/example.com/espresso-guide.md"
    assert "source: https://example.com/espresso" in first.json()["content"]
    assert first.headers["ETag"] == f'"{first.json()["revision"]}"'
    second = client.post(f"{API}/vaults/{vault['id']}/web-pages", json={"url": "https://example.com/espresso"})
    assert second.json()["relative_path"] == "web/example.com/espresso-guide-2.md"
    # A file added outside Page takes the next name too.
    (root(vault) / "web" / "example.com" / "espresso-guide-3.md").write_text("mine")
    third = client.post(f"{API}/vaults/{vault['id']}/web-pages", json={"url": "https://example.com/espresso"})
    assert third.json()["relative_path"] == "web/example.com/espresso-guide-4.md"
    assert (root(vault) / "web" / "example.com" / "espresso-guide-3.md").read_text() == "mine"
    assert (root(vault) / "web" / "example.com" / "espresso-guide.md").read_text().endswith("A double uses 18 g.\n")


@pytest.mark.parametrize(("error", "status", "code"), [
    (InvalidUrlError("x"), 422, "invalid_url"), (WebFetchError("secret"), 502, "web_fetch_failed")])
def test_web_page_errors_are_safe(client, vault, monkeypatch, error, status, code):
    from page_core.api import app as app_module

    def failing(url):
        raise error
    monkeypatch.setattr(app_module, "fetch_page", failing)
    response = client.post(f"{API}/vaults/{vault['id']}/web-pages", json={"url": "https://example.com/"})
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert "secret" not in response.text
    assert not (root(vault) / "web").exists()


def test_existing_vector_caches_migrate_and_accept_source_vectors(tmp_path):
    import sqlite3
    from uuid import uuid4
    from page_core.metadata import PersistentVault
    from page_core.metadata.repository import MIGRATIONS
    with PersistentVault.create(tmp_path / "v", "Old") as storage:
        note = storage.create_note(PurePosixPath("a.md"), "x")
        chunk = uuid4()
        storage.metadata.replace_vectors("fp", [(chunk, note.id, b"vec")])
        database = storage.metadata.database
    # Rewind the schema to version 3 with the old foreign-keyed table, as an older Page left it.
    with sqlite3.connect(database) as db:
        db.execute("DROP TABLE semantic_vectors")
        db.execute(MIGRATIONS[2][0])
        db.execute("INSERT INTO semantic_vectors VALUES (?,?,?,?)", (str(chunk), str(note.id), "fp", b"vec"))
        db.execute("DELETE FROM schema_migrations WHERE version=4")
        db.execute("PRAGMA user_version=3")
    with PersistentVault.open(tmp_path / "v") as storage:
        assert storage.metadata.read_vectors("fp") == {str(chunk): b"vec"}
        storage.metadata.replace_vectors("fp", [(uuid4(), uuid4(), b"source-vector")])
        assert len(storage.metadata.read_vectors("fp")) == 1
