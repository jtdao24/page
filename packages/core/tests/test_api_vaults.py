import json
import os
import shutil
import stat
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_support import (  # noqa: F401 - app, client and vault are fixtures
    API, StorageThreads, app, assert_error, client, client_for, posix_only, source_files, vault,
)
from page_core.api import create_app
from page_core.vault import FileSystemVault

pytestmark = posix_only


def manifest(root: Path) -> bytes:
    return (root / ".page" / "vault.json").read_bytes()


def test_create_get_list_and_close_a_new_vault(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "new" / "vault"
    name = "  Research ☃ notes "
    response = client.post(f"{API}/vaults", json={"root_path": str(root), "name": name})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name", "root_path", "needs_reconciliation"}
    assert body["name"] == name
    assert body["root_path"] == str(root.resolve())
    assert body["needs_reconciliation"] is False
    assert response.headers["location"] == f"{API}/vaults/{body['id']}"
    assert json.loads(manifest(root))["id"] == body["id"]
    assert client.get(response.headers["location"]).json() == body
    assert client.get(f"{API}/vaults").json() == [body]
    before = source_files(root)

    closed = client.delete(f"{API}/vaults/{body['id']}")
    assert closed.status_code == 204 and closed.content == b""
    assert closed.headers["cache-control"] == "no-store"
    assert source_files(root) == before
    assert (root / ".page" / "metadata" / "notes.sqlite3").is_file()
    assert client.get(f"{API}/vaults").json() == []
    assert_error(client.get(f"{API}/vaults/{body['id']}"), 404, "vault_not_found")
    assert_error(client.delete(f"{API}/vaults/{body['id']}"), 404, "vault_not_found")


def test_registry_starts_empty_and_unknown_ids_are_not_found(client: TestClient) -> None:
    assert client.get(f"{API}/vaults").json() == []
    unknown = "00000000-0000-4000-8000-000000000009"
    for method, suffix in [("GET", ""), ("DELETE", ""), ("GET", "/notes"), ("POST", "/reconcile")]:
        response = client.request(method, f"{API}/vaults/{unknown}{suffix}", json={} if method == "POST" else None)
        assert_error(response, 404, "vault_not_found")


def test_adoption_and_open_preserve_existing_bytes(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "existing"
    (root / "folder").mkdir(parents=True)
    files = {"a.md": b"\xef\xbb\xbf# Title\r\nline\rlast", "folder/b.md": b"", "notes.txt": b"other",
             ".obsidian/config": b"{}", "invalid.md": b"\xff\xfe"}
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    created = client.post(f"{API}/vaults", json={"root_path": str(root), "name": "Adopted"})
    assert created.status_code == 201
    vault_id = created.json()["id"]
    paths = [note["relative_path"] for note in client.get(f"{API}/vaults/{vault_id}/notes").json()]
    assert paths == ["a.md", "folder/b.md", "invalid.md"]
    assert client.delete(f"{API}/vaults/{vault_id}").status_code == 204
    reopened = client.post(f"{API}/vaults/open", json={"root_path": str(root)})
    assert reopened.status_code == 200 and reopened.json()["id"] == vault_id
    for name, data in files.items():
        assert (root / name).read_bytes() == data


def test_creating_an_existing_vault_conflicts_without_overwriting(client: TestClient, vault: dict[str, Any]) -> None:
    root = Path(vault["root_path"])
    before = manifest(root)
    body = {"root_path": str(root), "name": "Other"}
    assert_error(client.post(f"{API}/vaults", json=body), 409, "vault_exists")
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    assert_error(client.post(f"{API}/vaults", json=body), 409, "vault_exists")
    assert manifest(root) == before
    assert client.get(f"{API}/vaults").json() == []


def test_open_missing_and_invalid_vaults(client: TestClient, tmp_path: Path) -> None:
    assert_error(client.post(f"{API}/vaults/open", json={"root_path": str(tmp_path / "missing")}),
                 404, "vault_not_found")
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.md").write_text("a")
    assert_error(client.post(f"{API}/vaults/open", json={"root_path": str(plain)}), 404, "vault_not_found")
    assert not (plain / ".page").exists()
    payloads = [b"{not json", b'{"format": 2, "id": "00000000-0000-4000-8000-000000000001", "name": "x"}',
                b'{"format": 1, "id": "nope", "name": "x"}',
                b'{"format": 1, "id": "00000000-0000-4000-8000-000000000001", "name": " "}']
    for index, data in enumerate(payloads):
        root = tmp_path / f"invalid-{index}"
        (root / ".page").mkdir(parents=True)
        (root / ".page" / "vault.json").write_bytes(data)
        assert_error(client.post(f"{API}/vaults/open", json={"root_path": str(root)}), 422, "invalid_vault")
        assert manifest(root) == data
        assert not (root / ".page" / "metadata").exists()
    assert client.get(f"{API}/vaults").json() == []


def test_vaults_are_listed_by_root_then_id(client: TestClient, tmp_path: Path) -> None:
    for name in ("b", "a", "c"):
        assert client.post(f"{API}/vaults", json={"root_path": str(tmp_path / name), "name": name}).status_code == 201
    assert [vault["name"] for vault in client.get(f"{API}/vaults").json()] == ["a", "b", "c"]


def test_root_aliases_reuse_one_session_and_connection(app: FastAPI, tmp_path: Path, symlinks: None,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    threads = StorageThreads(monkeypatch)
    root = tmp_path / "real"
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with client_for(app) as client:
        created = client.post(f"{API}/vaults", json={"root_path": str(root), "name": "Real"}).json()
        for path in (alias, root, tmp_path / "real" / ".." / "real"):
            opened = client.post(f"{API}/vaults/open", json={"root_path": str(path)})
            assert opened.status_code == 200 and opened.json() == created
        assert len(client.get(f"{API}/vaults").json()) == 1
        assert len(threads.connected) == 1


def test_case_alias_of_an_open_root_reuses_its_session(client: TestClient, tmp_path: Path, case_insensitive: bool) -> None:
    if not case_insensitive:
        pytest.skip("filesystem is case-sensitive")
    created = client.post(f"{API}/vaults", json={"root_path": str(tmp_path / "Vault"), "name": "Vault"}).json()
    opened = client.post(f"{API}/vaults/open", json={"root_path": str(tmp_path / "VAULT")})
    assert opened.status_code == 200 and opened.json() == created


def test_cloned_vault_identity_is_rejected_before_metadata(client: TestClient, vault: dict[str, Any],
                                                           tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    (clone / ".page").mkdir(parents=True)
    shutil.copy2(Path(vault["root_path"]) / ".page" / "vault.json", clone / ".page" / "vault.json")
    (clone / "note.md").write_text("cloned")
    before = source_files(clone)
    assert_error(client.post(f"{API}/vaults/open", json={"root_path": str(clone)}), 409, "vault_identity_conflict")
    assert not (clone / ".page" / "metadata").exists()
    assert source_files(clone) == before
    assert [item["id"] for item in client.get(f"{API}/vaults").json()] == [vault["id"]]
    # After the original closes, the clone can be opened; its ID is not replaced.
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    assert client.post(f"{API}/vaults/open", json={"root_path": str(clone)}).json()["id"] == vault["id"]


def test_separate_applications_have_separate_registries(client: TestClient, vault: dict[str, Any]) -> None:
    with client_for(create_app(session_token=client.headers["authorization"].split()[1])) as other:
        assert other.get(f"{API}/vaults").json() == []
        assert_error(other.get(f"{API}/vaults/{vault['id']}"), 404, "vault_not_found")
        opened = other.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]})
        assert opened.status_code == 200 and opened.json()["id"] == vault["id"]
    assert client.get(f"{API}/vaults").json() == [vault]


def test_unsupported_metadata_platform_fails_closed_before_creation(client: TestClient, vault: dict[str, Any],
                                                                     tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    monkeypatch.delattr(os, "O_NOFOLLOW")
    root = tmp_path / "unsupported"
    assert_error(client.post(f"{API}/vaults", json={"root_path": str(root), "name": "No"}), 503, "storage_unavailable")
    assert not root.exists()
    existing = tmp_path / "existing-folder"
    existing.mkdir()
    assert_error(client.post(f"{API}/vaults", json={"root_path": str(existing), "name": "No"}), 503, "storage_unavailable")
    assert list(existing.iterdir()) == []
    assert_error(client.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]}), 503, "storage_unavailable")
    assert client.get(f"{API}/vaults").json() == []


def test_initialization_failure_after_manifest_is_not_rolled_back(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    (root / "note.md").write_bytes(b"keep\r\n")
    root.chmod(0o777)
    error = assert_error(client.post(f"{API}/vaults", json={"root_path": str(root), "name": "Shared"}),
                         503, "storage_unavailable")
    assert error["details"] is None
    assert (root / ".page" / "vault.json").is_file()
    assert (root / "note.md").read_bytes() == b"keep\r\n"
    assert client.get(f"{API}/vaults").json() == []
    # Blind retry of create cannot succeed; repair and open instead.
    assert_error(client.post(f"{API}/vaults", json={"root_path": str(root), "name": "Shared"}), 409, "vault_exists")
    root.chmod(0o755)
    opened = client.post(f"{API}/vaults/open", json={"root_path": str(root)})
    assert opened.status_code == 200 and opened.json()["name"] == "Shared"
    assert [note["relative_path"] for note in client.get(f"{API}/vaults/{opened.json()['id']}/notes").json()] == ["note.md"]


@pytest.mark.parametrize("body", [
    {"root_path": "relative/vault", "name": "x"},
    {"root_path": "~/vault", "name": "x"},
    {"root_path": "$HOME/vault", "name": "x"},
    {"root_path": "", "name": "x"},
    {"root_path": "/tmp/a\u0000b", "name": "x"},
    {"root_path": None, "name": "x"},
    {"root_path": 7, "name": "x"},
    {"root_path": ["/tmp/x"], "name": "x"},
    {"name": "x"},
    {"root_path": "ABSOLUTE"},
    {"root_path": "ABSOLUTE", "name": "   "},
    {"root_path": "ABSOLUTE", "name": ""},
    {"root_path": "ABSOLUTE", "name": None},
    {"root_path": "ABSOLUTE", "name": 3},
    {"root_path": "ABSOLUTE", "name": "x", "id": "00000000-0000-4000-8000-000000000001"},
])
def test_vault_requests_are_strictly_validated(client: TestClient, tmp_path: Path, body: dict[str, Any]) -> None:
    root = tmp_path / "strict"
    body = {key: str(root) if value == "ABSOLUTE" else value for key, value in body.items()}
    error = assert_error(client.post(f"{API}/vaults", json=body), 422, "validation_error")
    assert all(item["location"][0] == "body" for item in error["details"]["errors"])
    assert not root.exists()
    assert not any(tmp_path.iterdir())


def test_unencodable_root_is_rejected(client: TestClient, tmp_path: Path) -> None:
    raw = '{"root_path": "%s/\\ud800", "name": "x"}' % tmp_path
    assert_error(client.post(f"{API}/vaults", content=raw.encode(), headers={"Content-Type": "application/json"}),
                 422, "validation_error")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded",
                                          "application/merge-patch+json", "multipart/form-data"])
def test_json_bodies_require_application_json(client: TestClient, tmp_path: Path, content_type: str | None) -> None:
    payload = json.dumps({"root_path": str(tmp_path / "v"), "name": "x"}).encode()
    headers = {} if content_type is None else {"Content-Type": content_type}
    assert_error(client.post(f"{API}/vaults", content=payload, headers=headers), 415, "unsupported_media_type")
    assert list(tmp_path.iterdir()) == []


def test_json_media_type_parameters_are_allowed(client: TestClient, tmp_path: Path) -> None:
    payload = json.dumps({"root_path": str(tmp_path / "v"), "name": "x"}).encode()
    response = client.post(f"{API}/vaults", content=payload, headers={"Content-Type": "Application/JSON; charset=utf-8"})
    assert response.status_code == 201


@pytest.mark.parametrize("payload", [b"", b"{", b"[]", b"null", b'"text"', b"{'a': 1}", b"\xff"])
def test_malformed_json_is_a_validation_error(client: TestClient, payload: bytes) -> None:
    response = client.post(f"{API}/vaults/open", content=payload, headers={"Content-Type": "application/json"})
    assert_error(response, 422, "validation_error")


@pytest.mark.parametrize("identifier", [
    "00000000-0000-4000-8000-00000000000A", "000000000000400080000000000000a0", "{00000000-0000-4000-8000-000000000001}",
    "urn:uuid:00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-0000000000011", "x",
])
def test_route_ids_must_be_canonical(client: TestClient, identifier: str) -> None:
    error = assert_error(client.get(f"{API}/vaults/{identifier}"), 422, "validation_error")
    assert error["details"]["errors"] == [{"location": ["path", "vault_id"], "code": "invalid_uuid",
                                           "message": "Expected a canonical lowercase UUID"}]


def test_permission_denied_root_is_forbidden(client: TestClient, tmp_path: Path) -> None:
    parent = tmp_path / "locked"
    parent.mkdir()
    parent.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert_error(client.post(f"{API}/vaults", json={"root_path": str(parent / "v"), "name": "x"}),
                     403, "filesystem_forbidden")
    finally:
        parent.chmod(0o755)
    assert list(parent.iterdir()) == []


def test_open_of_a_standalone_stage_three_vault(client: TestClient, tmp_path: Path) -> None:
    files = FileSystemVault.create(tmp_path / "stage3", "Stage 3")
    files.create_note(PurePosixPath("a.md"), "hello")
    opened = client.post(f"{API}/vaults/open", json={"root_path": str(tmp_path / "stage3")})
    assert opened.status_code == 200 and opened.json()["id"] == str(files.vault.id)
    notes = client.get(f"{API}/vaults/{opened.json()['id']}/notes").json()
    assert [note["relative_path"] for note in notes] == ["a.md"]
