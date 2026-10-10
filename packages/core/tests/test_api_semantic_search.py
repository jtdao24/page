import threading
from uuid import UUID
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from embedding_fakes import FailingEmbedder, KeywordEmbedder
from page_core.api import Settings, create_app
from page_core.embeddings import Embedder
from page_core.vault import FileSystemVault


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8"))


@pytest.fixture
def root(fs_vault: FileSystemVault) -> Path:
    root = fs_vault.vault.root_path
    _write(root, "logic.md", "# Logic\n\nMinimize boolean gates with a Karnaugh map.\n")
    _write(root, "baking.md", "Knead the dough.\n")
    return root


TOKEN = "test-token-0123456789abcdefghijklmnopqrstuvwxyz"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _client(
    root: Path, factory: Callable[[], Embedder] = KeywordEmbedder, *, authorized: bool = True
) -> TestClient:
    app = create_app(Settings(root, sync_interval=0, api_token=TOKEN), embedder_factory=factory)
    return TestClient(app, base_url="http://127.0.0.1", headers=AUTH if authorized else None)


@pytest.fixture
def client(root: Path) -> Iterator[TestClient]:
    with _client(root) as client:
        assert client.app.state.runtime.wait_until_settled(10)
        yield client


def test_semantic_search_returns_ranked_note_results(client: TestClient) -> None:
    response = client.post(
        "/api/search/semantic",
        json={"query": "how do I simplify a digital logic circuit?", "limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "how do I simplify a digital logic circuit?"
    assert (body["metric"], body["model"], body["limit"]) == ("cosine", "test/keywords", 5)
    top = body["results"][0]
    assert (top["path"], top["title"]) == ("logic.md", "logic")
    assert top["excerpt"].startswith("# Logic")
    assert top["chunk"]["heading"] == "Logic"
    assert top["chunk"]["start_byte"] == 0
    note = client.get("/api/note", params={"path": top["path"]}).json()
    assert note["id"] == top["note_id"]
    assert UUID(top["chunk"]["id"])
    assert note["content"].encode()[: top["chunk"]["end_byte"]].decode() == top["excerpt"]


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "   "},
        {"query": ""},
        {},
        {"query": "logic", "limit": 0},
        {"query": "logic", "limit": 51},
        {"query": "logic", "limit": "5"},
        {"query": 5},
        {"query": "logic", "extra": True},
    ],
)
def test_invalid_requests_are_422(client: TestClient, payload: dict) -> None:
    assert client.post("/api/search/semantic", json=payload).status_code == 422


def test_no_matches_is_a_successful_empty_result(fs_vault: FileSystemVault) -> None:
    with _client(fs_vault.vault.root_path) as client:
        assert client.app.state.runtime.wait_until_settled(10)
        response = client.post("/api/search/semantic", json={"query": "anything"})

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_model_load_failure_is_a_503(root: Path) -> None:
    def broken() -> Embedder:
        raise RuntimeError("model download failed")

    with _client(root, broken) as client:
        assert client.app.state.runtime.wait_until_settled(10)
        response = client.post("/api/search/semantic", json={"query": "logic"})
        status = client.get("/api/index/status").json()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "index_unavailable"
    assert "model download failed" in response.json()["detail"]["message"]
    assert (status["state"], status["searchable"]) == ("error", False)


def test_search_while_loading_is_a_503(root: Path) -> None:
    release = threading.Event()

    def slow() -> Embedder:
        release.wait(10)
        return KeywordEmbedder()

    with _client(root, slow) as client:
        response = client.post("/api/search/semantic", json={"query": "logic"})
        assert client.get("/api/index/status").json()["state"] == "loading"
        release.set()

    assert response.status_code == 503
    assert "loading" in response.json()["detail"]["message"]


def test_query_embedding_failure_is_a_500(root: Path) -> None:
    embedder = FailingEmbedder()
    with _client(root, lambda: embedder) as client:
        assert client.app.state.runtime.wait_until_settled(10)
        embedder.fail = True
        response = client.post("/api/search/semantic", json={"query": "logic"})

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "embedding_failed"


def test_sync_endpoint_reflects_edits_and_deletes(client: TestClient, root: Path) -> None:
    (root / "logic.md").unlink()
    _write(root, "garden.md", "Compost the soil.\n")

    report = client.post("/api/index/sync").json()
    results = client.post("/api/search/semantic", json={"query": "seeds and soil"}).json()["results"]

    assert (report["added"], report["moved"], report["removed"]) == (1, 0, 1)
    assert [r["path"] for r in results] == ["garden.md", "baking.md"]
    assert client.get("/api/index/status").json()["notes"] == 2


def test_index_survives_restart(root: Path) -> None:
    with _client(root) as client:
        assert client.app.state.runtime.wait_until_settled(10)
        first = client.post("/api/search/semantic", json={"query": "boolean"}).json()["results"][0]
    embedder = KeywordEmbedder()
    with _client(root, lambda: embedder) as client:
        assert client.app.state.runtime.wait_until_settled(10)
        response = client.post("/api/search/semantic", json={"query": "boolean"})

    top = response.json()["results"][0]
    assert top["path"] == "logic.md"
    assert (top["note_id"], top["chunk"]["id"]) == (first["note_id"], first["chunk"]["id"])
    # Only the query was embedded: the persisted index was reused, not rebuilt.
    assert embedder.embedded_texts() == ["boolean"]


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [("missing.md", 404, "note_not_found"), ("../escape.md", 400, "invalid_path"), ("x.txt", 400, "invalid_path")],
)
def test_read_note_errors(client: TestClient, path: str, status: int, code: str) -> None:
    response = client.get("/api/note", params={"path": path})

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_cors_allows_the_desktop_origin(client: TestClient) -> None:
    response = client.options(
        "/api/search/semantic",
        headers={"Origin": "http://tauri.localhost", "Access-Control-Request-Method": "POST"},
    )

    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


# --- Access control -----------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token-0123456789abcdefghijklmnopqrstuv"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": TOKEN},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"Authorization": "Bearer "},
    ],
)
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/health", None),
        ("GET", "/api/index/status", None),
        ("POST", "/api/index/sync", None),
        ("POST", "/api/search/semantic", {"query": "logic"}),
        ("GET", "/api/note?path=logic.md", None),
    ],
)
def test_every_endpoint_requires_the_token(
    root: Path, headers: dict, method: str, path: str, body: dict | None
) -> None:
    with _client(root, authorized=False) as client:
        assert client.app.state.runtime.wait_until_settled(10)
        response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"
    assert "Karnaugh" not in response.text


def test_valid_token_is_accepted_case_insensitively_by_scheme(root: Path) -> None:
    with _client(root, authorized=False) as client:
        response = client.get("/api/health", headers={"Authorization": f"bearer {TOKEN}"})

    assert response.status_code == 200


def test_unauthorized_response_is_readable_by_the_desktop_origin(root: Path) -> None:
    with _client(root, authorized=False) as client:
        response = client.get("/api/health", headers={"Origin": "http://tauri.localhost"})

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_preflight_needs_no_token_and_allows_authorization(root: Path) -> None:
    with _client(root, authorized=False) as client:
        response = client.options(
            "/api/search/semantic",
            headers={
                "Origin": "http://localhost:1420",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, content-type",
            },
        )

    assert response.status_code == 200
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_other_origins_get_no_cors_access(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "192.168.1.5"])
def test_non_loopback_host_headers_are_refused(client: TestClient, host: str) -> None:
    response = client.get("/api/health", headers={"Host": host})

    assert response.status_code == 400


def test_docs_and_schema_are_not_served(client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_each_launch_gets_a_different_token(root: Path) -> None:
    first, second = Settings(root), Settings(root)

    assert first.api_token != second.api_token
    assert len(first.api_token) >= 32
    assert first.api_token not in repr(first)


@pytest.mark.parametrize("token", ["short", "x" * 31, "has space " * 4, "café" * 10])
def test_weak_tokens_are_refused(root: Path, token: str) -> None:
    with pytest.raises(ValueError, match="API token"):
        Settings(root, api_token=token)


def test_token_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("PAGE_VAULT_PATH", str(root))
    monkeypatch.setenv("PAGE_API_TOKEN", TOKEN)

    assert Settings.from_env().api_token == TOKEN
