import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import page_core
from api_support import (  # noqa: F401 - app, client and vault are fixtures
    API, AUTH, TOKEN, app, assert_error, call_raw, client, client_for, posix_only, vault,
)
from page_core.api import create_app, security
from page_core.api.service import LocalVaultService
from page_core.vault import FileSystemVault

NOTE = "00000000-0000-4000-8000-000000000001"
VAULT = "00000000-0000-4000-8000-000000000002"
ROUTES = [
    ("GET", f"{API}/health"),
    ("POST", f"{API}/vaults"),
    ("POST", f"{API}/vaults/open"),
    ("GET", f"{API}/vaults"),
    ("GET", f"{API}/vaults/{VAULT}"),
    ("DELETE", f"{API}/vaults/{VAULT}"),
    ("POST", f"{API}/vaults/{VAULT}/reconcile"),
    ("GET", f"{API}/vaults/{VAULT}/notes"),
    ("POST", f"{API}/vaults/{VAULT}/notes"),
    ("GET", f"{API}/vaults/{VAULT}/notes/{NOTE}"),
    ("PUT", f"{API}/vaults/{VAULT}/notes/{NOTE}"),
    ("POST", f"{API}/vaults/{VAULT}/notes/{NOTE}/move"),
    ("DELETE", f"{API}/vaults/{VAULT}/notes/{NOTE}"),
    ("GET", "/openapi.json"),
    ("GET", "/no/such/route"),
    ("PATCH", f"{API}/vaults"),
    ("OPTIONS", f"{API}/health"),
    ("GET", "/docs"),
]
BAD_CREDENTIALS: list[list[tuple[str, str]]] = [
    [],
    [("Authorization", "Bearer wrong-token")],
    [("Authorization", f"Bearer {TOKEN.lower()}")],
    [("Authorization", f"Bearer {TOKEN}x")],
    [("Authorization", f"Basic {TOKEN}")],
    [("Authorization", f"Bearer  {TOKEN}")],
    [("Authorization", f"Bearer{TOKEN}")],
    [("Authorization", "Bearer ")],
    [("Authorization", "Bearer")],
    [("Authorization", TOKEN)],
    [("Authorization", "")],
    [("Authorization", f"Bearer {TOKEN}"), ("Authorization", f"Bearer {TOKEN}")],
    [("Authorization", f"Bearer {TOKEN}, Bearer {TOKEN}")],
    [("X-Api-Key", TOKEN)],
    [("X-Authorization", f"Bearer {TOKEN}")],
    [("Cookie", f"token={TOKEN}; Authorization=Bearer {TOKEN}")],
]


def server_logs(caplog: pytest.LogCaptureFixture) -> str:
    # The test client's own httpx request log is not server output.
    records = [record for record in caplog.records if not record.name.startswith(("httpx", "httpcore"))]
    return "\n".join(f"{record.name} {record.getMessage()} {record.exc_text or ''}" for record in records)


@pytest.fixture
def storage_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    for name in ("create_vault", "open_vault", "list_vaults", "get_vault", "close_vault", "reconcile",
                 "list_notes", "get_note", "create_note", "update_note", "move_note", "delete_note"):
        original = getattr(LocalVaultService, name)

        def spy(self: LocalVaultService, *args: Any, _name: str = name, _original: Any = original) -> Any:
            calls.append(_name)
            return _original(self, *args)

        monkeypatch.setattr(LocalVaultService, name, spy)
    return calls


def test_importing_and_constructing_has_no_side_effects(tmp_path: Path) -> None:
    script = """
import socket, sqlite3, sys, threading, os
def forbidden(*args, **kwargs):
    raise AssertionError("no infrastructure at import or construction")
class GuardedSocket(socket.socket):
    def bind(self, *args): forbidden()
    def listen(self, *args): forbidden()
socket.socket = GuardedSocket
sqlite3.connect = forbidden
threads = threading.active_count()
import page_core.api
from page_core.api import create_app
first, second = create_app(), create_app()
assert first is not second
assert threading.active_count() == threads
assert os.listdir(".") == []
print("uvicorn" in sys.modules, "page_core.api.server" in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"
    assert list(tmp_path.iterdir()) == []


def test_existing_imports_do_not_load_the_api() -> None:
    script = (
        "import sys, page_core, page_core.domain, page_core.vault, page_core.metadata\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'fastapi','starlette','pydantic','uvicorn','httpx','anyio'} or m == 'page_core.api'))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


def test_health_needs_no_vault_and_reports_version(client: TestClient) -> None:
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": page_core.__version__}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("token", [b"x" * 43, 43, ["x" * 43]])
def test_supplied_token_type_is_checked(token: object) -> None:
    with pytest.raises(TypeError):
        create_app(session_token=token)  # type: ignore[arg-type]


@pytest.mark.parametrize("token", ["", "x" * 42, "x" * 44, "x" * 42 + "=", "x" * 42 + "+", "x" * 42 + "é", " " + "x" * 42])
def test_supplied_token_format_is_checked(token: str) -> None:
    with pytest.raises(ValueError):
        create_app(session_token=token)


def test_default_tokens_are_independent_per_application(monkeypatch: pytest.MonkeyPatch) -> None:
    issued: list[str] = []
    generate = security.secrets.token_urlsafe

    def record(size: int) -> str:
        assert size == 32
        issued.append(generate(size))
        return issued[-1]

    monkeypatch.setattr(security.secrets, "token_urlsafe", record)
    first, second = create_app(), create_app()
    assert len(issued) == 2 and issued[0] != issued[1]
    assert all(len(token) == 43 for token in issued)
    with client_for(first, authenticated=False) as one, client_for(second, authenticated=False) as two:
        assert one.get(f"{API}/health", headers={"Authorization": f"Bearer {issued[0]}"}).status_code == 200
        assert two.get(f"{API}/health", headers={"Authorization": f"Bearer {issued[1]}"}).status_code == 200
        assert_error(one.get(f"{API}/health", headers={"Authorization": f"Bearer {issued[1]}"}), 401, "unauthorized")
        assert_error(two.get(f"{API}/health", headers={"Authorization": f"Bearer {issued[0]}"}), 401, "unauthorized")


@pytest.mark.parametrize("method,url", ROUTES)
@pytest.mark.parametrize("headers", BAD_CREDENTIALS, ids=range(len(BAD_CREDENTIALS)))
def test_every_route_requires_one_exact_bearer_token(app: FastAPI, storage_calls: list[str], method: str,
                                                    url: str, headers: list[tuple[str, str]]) -> None:
    with client_for(app, authenticated=False) as anonymous:
        # Unsupported media and malformed JSON prove the body is never parsed first.
        response = anonymous.request(method, url, headers=headers + [("Content-Type", "text/plain")],
                                     content=b"{not json")
    error = assert_error(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == "Bearer"
    assert error["details"] is None
    assert storage_calls == []


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "bEaReR"])
def test_bearer_scheme_is_case_insensitive(app: FastAPI, scheme: str) -> None:
    with client_for(app, authenticated=False) as anonymous:
        assert anonymous.get(f"{API}/health", headers={"Authorization": f"{scheme} {TOKEN}"}).status_code == 200


def test_query_body_and_cookie_tokens_do_not_authenticate(app: FastAPI, storage_calls: list[str], tmp_path: Path) -> None:
    root = tmp_path / "vault"
    with client_for(app, authenticated=False) as anonymous:
        for name in ("token", "access_token", "authorization"):
            assert_error(anonymous.get(f"{API}/vaults", params={name: TOKEN}), 401, "unauthorized")
        body = {"root_path": str(root), "name": "Vault", "token": TOKEN, "authorization": f"Bearer {TOKEN}"}
        assert_error(anonymous.post(f"{API}/vaults", json=body), 401, "unauthorized")
        anonymous.cookies.set("Authorization", f"Bearer {TOKEN}")
        anonymous.cookies.set("token", TOKEN)
        assert_error(anonymous.get(f"{API}/vaults"), 401, "unauthorized")
    assert storage_calls == []
    assert not root.exists()


@pytest.mark.parametrize("host", [
    "example.com", "127.0.0.1.example.com", "localhost.example.com", "example.com:8765", "127.0.0.2",
    "0.0.0.0", "[::1]", "localhost.", "127.0.0.1:", "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:080",
    "127.0.0.1:+80", "127.0.0.1:8a", "127.0.0.1:80:80", "user@127.0.0.1", "user:pass@localhost:8765",
    "127.0.0.1 ", " localhost", "127.0.0.1/x", "",
])
def test_invalid_host_is_rejected(app: FastAPI, storage_calls: list[str], host: str) -> None:
    with client_for(app) as authorized:
        response = authorized.get(f"{API}/vaults", headers={"Host": host})
    assert_error(response, 400, "invalid_host")
    assert storage_calls == []


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "127.0.0.1:1", "localhost:8765", "127.0.0.1:65535"])
def test_valid_loopback_hosts_are_accepted(client: TestClient, host: str) -> None:
    assert client.get(f"{API}/health", headers={"Host": host}).status_code == 200


def test_duplicate_or_missing_host_is_rejected(app: FastAPI) -> None:
    auth = [(b"authorization", f"Bearer {TOKEN}".encode())]
    status, headers, body = call_raw(app, {"headers": auth + [(b"host", b"127.0.0.1"), (b"host", b"127.0.0.1")]})
    assert status == 400 and json.loads(body)["error"]["code"] == "invalid_host"
    assert headers[b"cache-control"] == b"no-store"
    status, _, body = call_raw(app, {"headers": auth})
    assert status == 400 and json.loads(body)["error"]["code"] == "invalid_host"


@pytest.mark.parametrize("peer", [None, ("192.168.1.20", 50000), ("10.0.0.1", 1), ("testclient", 50000),
                                  ("", 1), ("::ffff:192.168.1.20", 1), ("2001:db8::1", 1)])
def test_non_loopback_or_unknown_peers_are_rejected(app: FastAPI, peer: tuple[str, int] | None) -> None:
    headers = [(b"host", b"127.0.0.1"), (b"authorization", f"Bearer {TOKEN}".encode())]
    status, response_headers, body = call_raw(app, {"headers": headers, "client": peer})
    assert status == 403 and json.loads(body)["error"]["code"] == "local_access_required"
    assert response_headers[b"cache-control"] == b"no-store"


@pytest.mark.parametrize("peer", [("127.0.0.1", 1), ("127.8.9.10", 1), ("::1", 1), ("::ffff:127.0.0.1", 1)])
def test_loopback_peers_are_accepted(app: FastAPI, peer: tuple[str, int]) -> None:
    headers = [(b"host", b"127.0.0.1"), (b"authorization", f"Bearer {TOKEN}".encode())]
    status, _, _ = call_raw(app, {"headers": headers, "client": peer})
    assert status == 200


@pytest.mark.parametrize("origin", ["null", "http://127.0.0.1:1420", "tauri://localhost", "http://localhost", ""])
def test_any_origin_is_rejected_and_cors_is_not_enabled(app: FastAPI, storage_calls: list[str], origin: str) -> None:
    preflight = {"Origin": origin, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "authorization"}
    with client_for(app, authenticated=False) as anonymous:
        rejected = [anonymous.options(f"{API}/vaults", headers=preflight),
                    anonymous.get(f"{API}/vaults", headers={"Origin": origin, **AUTH}),
                    anonymous.post(f"{API}/vaults", headers={"Origin": origin, **AUTH}, json={})]
    for response in rejected:
        assert_error(response, 403, "origin_not_allowed")
        assert not any(name.lower().startswith("access-control-") for name in response.headers)
    assert storage_calls == []


def test_authenticated_options_and_unsupported_methods_are_405(client: TestClient) -> None:
    for method in ("OPTIONS", "PATCH", "PUT"):
        response = client.request(method, f"{API}/vaults")
        assert_error(response, 405, "method_not_allowed")
        assert set(response.headers["allow"].split(", ")) == {"GET", "POST"}
        assert not any(name.lower().startswith("access-control-") for name in response.headers)
    response = client.request("PATCH", f"{API}/vaults/{VAULT}/notes/{NOTE}")
    assert_error(response, 405, "method_not_allowed")
    assert set(response.headers["allow"].split(", ")) == {"GET", "PUT", "DELETE"}


def test_unknown_routes_and_slash_variants_are_not_redirected(client: TestClient) -> None:
    for url in ("/", "/api/v1", f"{API}/vaults/", f"{API}/health/", "/no/such/route"):
        response = client.get(url, follow_redirects=False)
        assert_error(response, 404, "route_not_found")


@pytest.mark.parametrize("url", ["/docs", "/redoc", "/docs/oauth2-redirect"])
def test_documentation_user_interfaces_are_disabled(client: TestClient, url: str) -> None:
    response = client.get(url)
    assert_error(response, 404, "route_not_found")
    assert "html" not in response.headers["content-type"]


def test_openapi_is_authenticated_and_describes_the_contract(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert TOKEN not in response.text
    schema = response.json()
    assert schema["components"]["securitySchemes"] == {"bearerAuth": {"type": "http", "scheme": "bearer"}}
    assert schema["security"] == [{"bearerAuth": []}]
    names = set(schema["components"]["schemas"])
    assert {"CreateVaultRequest", "OpenVaultRequest", "CreateNoteRequest", "UpdateNoteRequest", "MoveNoteRequest",
            "ReconcileRequest", "HealthResponse", "VaultResponse", "NoteSummaryResponse", "NoteResponse",
            "ReconcileResponse", "ErrorResponse"} <= names
    paths = schema["paths"]
    assert set(paths) == {
        f"{API}/health", f"{API}/vaults", f"{API}/vaults/open", f"{API}/vaults/{{vault_id}}",
        f"{API}/vaults/{{vault_id}}/reconcile", f"{API}/vaults/{{vault_id}}/notes",
        f"{API}/vaults/{{vault_id}}/notes/{{note_id}}", f"{API}/vaults/{{vault_id}}/notes/{{note_id}}/move",
    }
    update = paths[f"{API}/vaults/{{vault_id}}/notes/{{note_id}}"]["put"]
    assert any(parameter["name"] == "If-Match" and parameter["required"] for parameter in update["parameters"])
    assert {"200", "412", "428", "401"} <= set(update["responses"])
    body = update["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/UpdateNoteRequest"}
    assert schema["components"]["schemas"]["CreateNoteRequest"]["additionalProperties"] is False


def test_unexpected_failures_are_safe_and_not_logged(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                                     caplog: pytest.LogCaptureFixture) -> None:
    def explode(self: LocalVaultService) -> None:
        raise RuntimeError(f"SECRET-DETAIL {TOKEN}")

    monkeypatch.setattr(LocalVaultService, "list_vaults", explode)
    with caplog.at_level(logging.DEBUG):
        response = client.get(f"{API}/vaults")
    error = assert_error(response, 500, "internal_error")
    assert error["details"] is None
    assert "SECRET" not in response.text and "Traceback" not in response.text
    assert "internal_error: RuntimeError" in server_logs(caplog)
    assert "SECRET" not in server_logs(caplog) and TOKEN not in server_logs(caplog)


@posix_only
def test_errors_and_logs_never_echo_inputs_content_or_credentials(client: TestClient, vault: dict[str, Any],
                                                                  caplog: pytest.LogCaptureFixture) -> None:
    secret = "SECRET-CONTENT-☃"
    url = f"{API}/vaults/{vault['id']}/notes"
    with caplog.at_level(logging.DEBUG):
        responses = [
            client.post(url, json={"relative_path": f"../{secret}.md", "content": secret}),
            client.post(url, json={"relative_path": "a.md", "content": secret, secret: secret}),
            client.post(url, json={"relative_path": "a.md", "content": 7}),
            client.post(url, content=f'{{"relative_path": "{secret}'.encode()),
            client.post(url, content=f'{{"relative_path": "{secret}'.encode(), headers={"Content-Type": "application/json"}),
            client.post(f"{API}/vaults/{vault['id']}/reconcile", json={"known_renames": {secret: 1}}),
            client.get(f"{API}/vaults/{secret}"),
            client.post(f"{API}/vaults/open", json={"root_path": f"/missing/{secret}"}),
        ]
        created = client.post(url, json={"relative_path": "a.md", "content": secret})
        responses.append(client.post(url, json={"relative_path": "a.md", "content": secret}))
        responses.append(client.put(f"{url}/{created.json()['id']}", headers={"If-Match": f'"{"0" * 64}"'},
                                    json={"content": secret}))
    for response in responses:
        assert response.status_code >= 400
        assert secret not in response.text and "SECRET" not in response.text and TOKEN not in response.text
        assert set(response.json()) == {"error"}
    assert "SECRET" not in server_logs(caplog) and TOKEN not in server_logs(caplog)
    renames = responses[5].json()["error"]["details"]["errors"]
    assert renames[0]["location"][:2] == ["body", "known_renames"] and "*" in renames[0]["location"]


@posix_only
def test_health_answers_while_storage_is_blocked(app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "vault"
    FileSystemVault.create(root, "Blocked")
    entered, release = threading.Event(), threading.Event()
    list_paths = FileSystemVault.list_note_paths

    def blocked_scan(self: FileSystemVault, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(10)
        return list_paths(self, **kwargs)

    monkeypatch.setattr(FileSystemVault, "list_note_paths", blocked_scan)
    with client_for(app) as client:
        result: dict[str, Any] = {}
        opener = threading.Thread(target=lambda: result.update(
            response=client.post(f"{API}/vaults/open", json={"root_path": str(root)})))
        opener.start()
        try:
            assert entered.wait(10)
            for _ in range(3):
                health = client.get(f"{API}/health")
                assert health.status_code == 200 and health.json()["status"] == "ok"
            assert opener.is_alive()
        finally:
            release.set()
            opener.join(10)
        assert result["response"].status_code == 200
