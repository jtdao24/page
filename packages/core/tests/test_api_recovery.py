import asyncio
import errno
import json
import os
import sqlite3
import stat
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_support import (  # noqa: F401 - app, client and vault are fixtures
    API, AUTH, BASE_URL, PEER, StorageThreads, app, assert_error, client, client_for, create_note, if_match,
    notes_url, posix_only, source_files, vault,
)
from page_core.api.service import LocalVaultService
from page_core.metadata import MetadataRepository, PersistentVault
from page_core.vault import FileSystemVault

pytestmark = posix_only


def reconcile(client: TestClient, vault: dict[str, Any], renames: dict[str, str] | None = None) -> httpx.Response:
    return client.post(f"{API}/vaults/{vault['id']}/reconcile",
                       json={} if renames is None else {"known_renames": renames})


def counts(response: httpx.Response) -> dict[str, int]:
    assert response.status_code == 200, response.text
    return response.json()


def test_reconciliation_handles_external_changes(client: TestClient, vault: dict[str, Any]) -> None:
    root = Path(vault["root_path"])
    edited = create_note(client, vault, "edited.md", "before")
    renamed = create_note(client, vault, "renamed.md", "unique bytes")
    missing = create_note(client, vault, "missing.md", "gone")
    twins = [create_note(client, vault, f"twin{index}.md", "same") for index in (1, 2)]
    confirmed = create_note(client, vault, "confirmed.md", "original")
    unchanged = create_note(client, vault, "unchanged.md", "same as ever")

    (root / "added.md").write_text("new")
    (root / "edited.md").write_text("after")
    (root / "moved").mkdir()
    (root / "renamed.md").rename(root / "moved/renamed.md")
    (root / "missing.md").unlink()
    (root / "twin1.md").rename(root / "x.md")
    (root / "twin2.md").rename(root / "y.md")
    (root / "confirmed.md").rename(root / "elsewhere.md")
    (root / "elsewhere.md").write_text("edited during the move")
    assert client.get(notes_url(vault)).json()[0]["relative_path"] == "confirmed.md"

    result = counts(reconcile(client, vault, {confirmed["id"]: "elsewhere.md"}))
    assert result == {"added": 3, "modified": 2, "renamed": 2, "missing": 3, "unchanged": 1}
    paths = {item["relative_path"]: item["id"] for item in client.get(notes_url(vault)).json()}
    assert set(paths) == {"added.md", "edited.md", "moved/renamed.md", "x.md", "y.md", "elsewhere.md", "unchanged.md"}
    assert paths["edited.md"] == edited["id"] and paths["moved/renamed.md"] == renamed["id"]
    assert paths["elsewhere.md"] == confirmed["id"] and paths["unchanged.md"] == unchanged["id"]
    assert {paths["x.md"], paths["y.md"]}.isdisjoint({twin["id"] for twin in twins})
    for note in [missing, *twins]:
        assert_error(client.get(notes_url(vault, note["id"])), 404, "note_not_found")
    again = client.get(notes_url(vault, confirmed["id"])).json()
    assert again["created_at"] == confirmed["created_at"] and again["content"] == "edited during the move"
    assert counts(reconcile(client, vault))["unchanged"] == 7


@pytest.mark.parametrize("case", ["unknown", "existing-source", "missing-target", "duplicate-target"])
def test_invalid_confirmations_are_rejected_atomically(client: TestClient, vault: dict[str, Any], case: str) -> None:
    root = Path(vault["root_path"])
    first = create_note(client, vault, "a.md", "a")
    second = create_note(client, vault, "b.md", "b")
    third = create_note(client, vault, "c.md", "c")
    (root / "c.md").unlink()
    (root / "new.md").write_text("new")
    renames = {
        "unknown": {"00000000-0000-4000-8000-000000000042": "new.md"},
        "existing-source": {first["id"]: "new.md"},
        "missing-target": {third["id"]: "absent.md"},
        "duplicate-target": {third["id"]: "new.md", second["id"]: "new.md"},
    }[case]
    before = client.get(notes_url(vault)).json()
    assert_error(reconcile(client, vault, renames), 422, "invalid_reconciliation")
    assert client.get(notes_url(vault)).json() == before
    assert client.get(notes_url(vault, third["id"])).status_code == 404


@pytest.mark.parametrize("body", [
    {"known_renames": None}, {"known_renames": []}, {"known_renames": {"A0000000-0000-4000-8000-000000000001": "a.md"}},
    {"known_renames": {"00000000-0000-4000-8000-000000000001": "../a.md"}},
    {"known_renames": {"00000000-0000-4000-8000-000000000001": 1}}, {"other": {}},
])
def test_reconcile_requests_are_strict(client: TestClient, vault: dict[str, Any], body: dict[str, Any]) -> None:
    assert_error(client.post(f"{API}/vaults/{vault['id']}/reconcile", json=body), 422, "validation_error")


def test_failed_scan_keeps_the_previous_complete_snapshot(client: TestClient, vault: dict[str, Any],
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    note = create_note(client, vault, "a.md", "a")
    (Path(vault["root_path"]) / "b.md").write_text("b")
    walk = os.walk

    def unreadable(top: Any, onerror: Any = None, **kwargs: Any) -> Any:
        onerror(PermissionError(errno.EACCES, "cannot enumerate folder"))
        return walk(top, onerror=onerror, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "walk", unreadable)
        assert_error(reconcile(client, vault), 403, "filesystem_forbidden")
    assert [item["id"] for item in client.get(notes_url(vault)).json()] == [note["id"]]
    assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is False


def test_unreadable_file_aborts_reconciliation_without_changes(client: TestClient, vault: dict[str, Any]) -> None:
    root = Path(vault["root_path"])
    first = create_note(client, vault, "a.md", "a")
    create_note(client, vault, "b.md", "b")
    (root / "b.md").unlink()
    (root / "a.md").chmod(0)
    try:
        assert_error(reconcile(client, vault), 403, "filesystem_forbidden")
        assert_error(client.get(notes_url(vault, first["id"])), 403, "filesystem_forbidden")
        assert [item["relative_path"] for item in client.get(notes_url(vault)).json()] == ["a.md", "b.md"]
    finally:
        (root / "a.md").chmod(0o644)
    assert counts(reconcile(client, vault))["missing"] == 1


def failing_replace(*args: Any, **kwargs: Any) -> None:
    raise OSError(errno.ENOSPC, "No space left on device")


def test_filesystem_failures_leave_sources_and_metadata_intact(client: TestClient, vault: dict[str, Any],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(vault["root_path"])
    note = create_note(client, vault, "a.md", "original\r\n")
    create_note(client, vault, "keep/other.md", "unrelated")
    before_files = source_files(root)
    before_notes = client.get(notes_url(vault)).json()
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", failing_replace)
        assert_error(client.post(notes_url(vault), json={"relative_path": "new/b.md", "content": "x"}),
                     500, "filesystem_error")
        assert_error(client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]),
                                json={"content": "changed"}), 500, "filesystem_error")
        assert_error(client.post(f"{notes_url(vault, note['id'])}/move", headers=if_match(note["revision"]),
                                 json={"relative_path": "moved.md"}), 500, "filesystem_error")
    after = source_files(root)
    assert {path: data for path, data in after.items()} == before_files
    assert not any(name.endswith(".tmp") for name in after)
    assert not (root / "moved.md").exists()
    assert client.get(notes_url(vault)).json() == before_notes
    assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is False
    assert client.get(notes_url(vault, note["id"])).json()["revision"] == note["revision"]


def test_permission_denied_writes_are_forbidden_without_changes(client: TestClient, vault: dict[str, Any]) -> None:
    root = Path(vault["root_path"])
    note = create_note(client, vault, "locked/a.md", "a")
    before = source_files(root)
    (root / "locked").chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert_error(client.post(notes_url(vault), json={"relative_path": "locked/b.md"}), 403, "filesystem_forbidden")
        assert_error(client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]),
                                json={"content": "b"}), 403, "filesystem_forbidden")
        assert_error(client.delete(notes_url(vault, note["id"]), headers=if_match(note["revision"])),
                     403, "filesystem_forbidden")
    finally:
        (root / "locked").chmod(0o755)
    assert source_files(root) == before
    assert client.get(notes_url(vault, note["id"])).json()["revision"] == note["revision"]


class MetadataOutage:
    """Fail metadata writes once a chosen filesystem mutation has succeeded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, operation: str | None = None) -> None:
        self.active = operation is None
        for name in ("insert", "update"):
            original = getattr(MetadataRepository, name)

            def write(repository: MetadataRepository, record: Any, _original: Any = original) -> None:
                if self.active:
                    raise sqlite3.OperationalError("disk I/O error")
                _original(repository, record)

            monkeypatch.setattr(MetadataRepository, name, write)
        if operation is not None:
            mutation = getattr(FileSystemVault, f"{operation}_note")

            def mutate(files: FileSystemVault, *args: Any) -> Any:
                result = mutation(files, *args)
                self.active = True
                return result

            monkeypatch.setattr(FileSystemVault, f"{operation}_note", mutate)


def assert_blocked(client: TestClient, vault: dict[str, Any], note: dict[str, Any]) -> None:
    requests = [
        ("GET", notes_url(vault), None, {}),
        ("POST", notes_url(vault), {"relative_path": "other.md"}, {}),
        ("GET", notes_url(vault, note["id"]), None, {}),
        ("PUT", notes_url(vault, note["id"]), {"content": "x"}, if_match(note["revision"])),
        ("POST", f"{notes_url(vault, note['id'])}/move", {"relative_path": "z.md"}, if_match(note["revision"])),
        ("DELETE", notes_url(vault, note["id"]), None, if_match(note["revision"])),
    ]
    for method, url, body, headers in requests:
        assert_error(client.request(method, url, json=body, headers=headers), 409, "reconciliation_required")
    assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is True
    assert client.get(f"{API}/vaults").json()[0]["needs_reconciliation"] is True


@pytest.mark.parametrize("operation", ["create", "update", "move", "delete"])
def test_metadata_failure_after_filesystem_success_requires_reconciliation(
        client: TestClient, vault: dict[str, Any], monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    root = Path(vault["root_path"])
    note = create_note(client, vault, "a.md", "before")
    create_note(client, vault, "unrelated.md", "unrelated")
    request = {
        "create": ("POST", notes_url(vault), {"relative_path": "new.md", "content": "created"}, {}),
        "update": ("PUT", notes_url(vault, note["id"]), {"content": "after"}, if_match(note["revision"])),
        "move": ("POST", f"{notes_url(vault, note['id'])}/move", {"relative_path": "b/moved.md"},
                 if_match(note["revision"])),
        "delete": ("DELETE", notes_url(vault, note["id"]), None, if_match(note["revision"])),
    }[operation]
    with monkeypatch.context() as patch:
        outage = MetadataOutage(patch, operation)
        method, url, body, headers = request
        error = assert_error(client.request(method, url, json=body, headers=headers), 503, "metadata_sync_failed")
        expected_path = {"create": "new.md", "update": "a.md", "move": "b/moved.md", "delete": "a.md"}[operation]
        assert error["details"] == {
            "filesystem_changed": True, "operation": operation, "relative_path": expected_path,
            "note_id": None if operation == "create" else note["id"], "reconciliation_required": True,
        }
        files = source_files(root)
        assert files["unrelated.md"] == b"unrelated"
        if operation == "create":
            assert files["new.md"] == b"created" and files["a.md"] == b"before"
        elif operation == "update":
            assert files["a.md"] == b"after"
        elif operation == "move":
            assert files["b/moved.md"] == b"before" and "a.md" not in files
        else:
            assert "a.md" not in files
        assert_blocked(client, vault, note)
        # Recovery while storage is still failing keeps the session gated.
        assert_error(reconcile(client, vault), 500, "storage_error")
        assert_blocked(client, vault, note)
        assert source_files(root) == files
        outage.active = False
    result = counts(reconcile(client, vault))
    assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is False
    current = client.get(notes_url(vault, note["id"]))
    if operation == "create":
        assert result["added"] == 1
        assert "new.md" in [item["relative_path"] for item in client.get(notes_url(vault)).json()]
    elif operation == "update":
        assert result["modified"] == 1 and current.json()["content"] == "after"
    elif operation == "move":
        assert result["renamed"] == 1 and current.json()["relative_path"] == "b/moved.md"
        assert current.json()["created_at"] == note["created_at"]
    else:
        assert result["missing"] == 1 and current.status_code == 404


def stored_notes(vault: dict[str, Any]) -> list[tuple[Any, ...]]:
    with sqlite3.connect(database_of(vault)) as db:
        rows = db.execute("SELECT * FROM notes ORDER BY id").fetchall()
    db.close()
    return rows


@pytest.mark.parametrize("corruption", ["uuid", "path"])
@pytest.mark.parametrize("confirm", [False, True])
def test_corrupt_metadata_during_reconciliation_is_a_storage_error(
        client: TestClient, vault: dict[str, Any], monkeypatch: pytest.MonkeyPatch, corruption: str,
        confirm: bool) -> None:
    root = Path(vault["root_path"])
    first = create_note(client, vault, "a.md", "a")
    moved = create_note(client, vault, "b.md", "b")
    with monkeypatch.context() as patch:
        MetadataOutage(patch, "update")
        assert_error(client.put(notes_url(vault, first["id"]), headers=if_match(first["revision"]),
                                json={"content": "after"}), 503, "metadata_sync_failed")
    # A well-formed confirmation: b.md was moved and edited externally.
    (root / "b.md").rename(root / "c.md")
    (root / "c.md").write_text("edited")
    # Values that satisfy the SQL constraints but fail record decoding.
    statement = {"uuid": "UPDATE notes SET id=? WHERE id=?",
                 "path": "UPDATE notes SET relative_path=? WHERE id=?"}[corruption]
    value = {"uuid": "x" * 36, "path": "CON.md"}[corruption]
    with sqlite3.connect(database_of(vault)) as db:
        db.execute(statement, (value, first["id"]))
    db.close()
    rows, files = stored_notes(vault), source_files(root)
    error = assert_error(reconcile(client, vault, {moved["id"]: "c.md"} if confirm else None), 500, "storage_error")
    assert error["details"] is None and value not in json.dumps(error)
    assert stored_notes(vault) == rows
    assert source_files(root) == files
    assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is True


CORRUPTIONS = {"uuid": ("UPDATE notes SET id=? WHERE id=?", "x" * 36),
               "path": ("UPDATE notes SET relative_path=? WHERE id=?", "CON.md")}


def corrupt(vault: dict[str, Any], note_id: str, corruption: str) -> None:
    statement, value = CORRUPTIONS[corruption]
    with sqlite3.connect(database_of(vault)) as db:
        db.execute(statement, (value, note_id))
    db.close()


@pytest.mark.parametrize("corruption", sorted(CORRUPTIONS))
def test_opening_corrupt_metadata_is_a_storage_error(client: TestClient, vault: dict[str, Any],
                                                     monkeypatch: pytest.MonkeyPatch, corruption: str) -> None:
    root = Path(vault["root_path"])
    first = create_note(client, vault, "a.md", "a")
    create_note(client, vault, "b.md", "b")
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    corrupt(vault, first["id"], corruption)
    rows, files, database = stored_notes(vault), source_files(root), database_of(vault).read_bytes()
    threads = StorageThreads(monkeypatch)
    error = assert_error(client.post(f"{API}/vaults/open", json={"root_path": str(root)}), 500, "storage_error")
    assert error["details"] is None and CORRUPTIONS[corruption][1] not in json.dumps(error)
    assert len(threads.connected) == len(threads.closed) == 1
    assert client.get(f"{API}/vaults").json() == []
    assert stored_notes(vault) == rows and database_of(vault).read_bytes() == database
    assert source_files(root) == files


@pytest.mark.parametrize("corruption", sorted(CORRUPTIONS))
def test_unrelated_corrupt_record_blocks_operations_before_mutation(client: TestClient, vault: dict[str, Any],
                                                                    corruption: str) -> None:
    root = Path(vault["root_path"])
    healthy = create_note(client, vault, "a.md", "a")
    broken = create_note(client, vault, "b.md", "b")
    corrupt(vault, broken["id"], corruption)
    rows, files = stored_notes(vault), source_files(root)
    requests = [
        ("GET", notes_url(vault), None, {}),
        ("GET", notes_url(vault, healthy["id"]), None, {}),
        ("PUT", notes_url(vault, healthy["id"]), {"content": "changed"}, if_match(healthy["revision"])),
        ("POST", f"{notes_url(vault, healthy['id'])}/move", {"relative_path": "moved.md"},
         if_match(healthy["revision"])),
        ("DELETE", notes_url(vault, healthy["id"]), None, if_match(healthy["revision"])),
    ]
    for method, url, body, headers in requests:
        error = assert_error(client.request(method, url, json=body, headers=headers), 500, "storage_error")
        assert error["details"] is None
    assert source_files(root) == files
    assert stored_notes(vault) == rows
    assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is False


def test_ambiguous_failed_move_is_recovered_with_known_renames(client: TestClient, vault: dict[str, Any],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(vault["root_path"])
    first = create_note(client, vault, "a.md", "same")
    second = create_note(client, vault, "c.md", "same")
    with monkeypatch.context() as patch:
        MetadataOutage(patch, "move")
        error = assert_error(client.post(f"{notes_url(vault, first['id'])}/move", headers=if_match(first["revision"]),
                                         json={"relative_path": "b.md"}), 503, "metadata_sync_failed")
    assert error["details"]["note_id"] == first["id"] and error["details"]["relative_path"] == "b.md"
    (root / "c.md").rename(root / "d.md")
    result = counts(reconcile(client, vault, {first["id"]: "b.md"}))
    assert result["renamed"] == 2 and result["added"] == result["missing"] == 0
    assert client.get(notes_url(vault, first["id"])).json()["relative_path"] == "b.md"
    assert client.get(notes_url(vault, second["id"])).json()["relative_path"] == "d.md"
    assert client.get(notes_url(vault, first["id"])).json()["created_at"] == first["created_at"]


def test_flagged_session_can_be_closed_and_reopened_after_repair(client: TestClient, vault: dict[str, Any],
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    note = create_note(client, vault, "a.md", "before")
    with monkeypatch.context() as patch:
        MetadataOutage(patch, "update")
        assert_error(client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]),
                                json={"content": "after"}), 503, "metadata_sync_failed")
        assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
        assert_error(client.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]}), 500, "storage_error")
        assert client.get(f"{API}/vaults").json() == []
    reopened = client.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]})
    assert reopened.status_code == 200 and reopened.json()["needs_reconciliation"] is False
    current = client.get(notes_url(vault, note["id"])).json()
    assert current["content"] == "after" and current["created_at"] == note["created_at"]


def test_read_refresh_failure_is_not_reported_as_filesystem_success(client: TestClient, vault: dict[str, Any],
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    note = create_note(client, vault, "a.md", "before")
    path = Path(vault["root_path"]) / "a.md"
    path.write_text("edited outside")
    with monkeypatch.context() as patch:
        MetadataOutage(patch)
        assert_error(client.get(notes_url(vault, note["id"])), 500, "storage_error")
        assert_error(client.delete(notes_url(vault, note["id"]), headers=if_match(note["revision"])),
                     500, "storage_error")
    assert path.read_text() == "edited outside"
    assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is False


def test_metadata_privacy_refusal_during_a_session(client: TestClient, vault: dict[str, Any]) -> None:
    note = create_note(client, vault, "a.md", "before")
    database = Path(vault["root_path"]) / ".page" / "metadata" / "notes.sqlite3"
    database.chmod(0o644)
    assert_error(client.get(notes_url(vault, note["id"])), 503, "storage_unavailable")
    assert_error(client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]),
                            json={"content": "after"}), 503, "storage_unavailable")
    assert (Path(vault["root_path"]) / "a.md").read_text() == "before"
    assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is False
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    assert client.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]}).status_code == 200
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def database_of(vault: dict[str, Any]) -> Path:
    return Path(vault["root_path"]) / ".page" / "metadata" / "notes.sqlite3"


@pytest.mark.parametrize("damage,status,code", [
    ("future-schema", 503, "storage_unavailable"),
    ("other-vault", 503, "storage_unavailable"),
    ("corrupt", 500, "storage_error"),
])
def test_incompatible_or_corrupt_metadata_is_never_reset(client: TestClient, vault: dict[str, Any], damage: str,
                                                         status: int, code: str) -> None:
    create_note(client, vault, "a.md", "keep")
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    database = database_of(vault)
    if damage == "corrupt":
        database.write_bytes(b"this is not a sqlite database" * 100)
    else:
        with sqlite3.connect(database) as db:
            if damage == "future-schema":
                db.execute("PRAGMA user_version=100")
            else:
                db.execute("UPDATE vaults SET id='00000000-0000-4000-8000-000000000077'")
        db.close()
    before = database.read_bytes()
    error = assert_error(client.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]}), status, code)
    assert error["details"] is None
    assert database.read_bytes() == before
    assert (Path(vault["root_path"]) / "a.md").read_bytes() == b"keep"
    assert client.get(f"{API}/vaults").json() == []


def test_hardlinked_metadata_is_refused(client: TestClient, vault: dict[str, Any], tmp_path: Path,
                                        hardlinks: None) -> None:
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    linked = tmp_path / "linked.sqlite3"
    os.link(database_of(vault), linked)
    linked.chmod(0o644)
    assert_error(client.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]}), 503, "storage_unavailable")
    assert stat.S_IMODE(linked.stat().st_mode) == 0o644


def test_locked_database_is_busy_not_failed(app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connect = sqlite3.connect

    def short_timeout(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        kwargs["timeout"] = 0.05
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", short_timeout)
    with client_for(app) as client:
        vault = client.post(f"{API}/vaults", json={"root_path": str(tmp_path / "v"), "name": "v"}).json()
        note = create_note(client, vault, "a.md", "a")
        holder = connect(database_of(vault), isolation_level=None)
        try:
            holder.execute("BEGIN IMMEDIATE")
            assert_error(client.get(notes_url(vault, note["id"])), 503, "storage_busy")
            assert_error(client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]),
                                    json={"content": "b"}), 503, "storage_busy")
            assert (Path(vault["root_path"]) / "a.md").read_text() == "a"
        finally:
            holder.rollback()
            holder.close()
        assert client.get(notes_url(vault, note["id"])).json()["revision"] == note["revision"]
        assert client.get(f"{API}/vaults/{vault['id']}").json()["needs_reconciliation"] is False


def test_failed_candidate_releases_its_connection(app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "v"
    FileSystemVault.create(root, "v")
    threads = StorageThreads(monkeypatch)
    with client_for(app) as client:
        with monkeypatch.context() as patch:
            def broken(self: PersistentVault, **kwargs: Any) -> None:
                raise sqlite3.OperationalError("disk I/O error")
            patch.setattr(PersistentVault, "reconcile", broken)
            assert_error(client.post(f"{API}/vaults/open", json={"root_path": str(root)}), 500, "storage_error")
            assert len(threads.connected) == len(threads.closed) == 1
        assert client.get(f"{API}/vaults").json() == []
        assert client.post(f"{API}/vaults/open", json={"root_path": str(root)}).status_code == 200
    assert len(threads.connected) == len(threads.closed) == 2
    assert len(set(threads.connected + threads.closed)) == 1


def storage_workers() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name.startswith("page-storage")]


def test_shutdown_closes_every_session_on_the_worker(app: FastAPI, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    threads = StorageThreads(monkeypatch)
    with client_for(app) as client:
        for name in ("a", "b", "c"):
            client.post(f"{API}/vaults", json={"root_path": str(tmp_path / name), "name": name})
        assert len(client.get(f"{API}/vaults").json()) == 3
        assert threads.closed == [] and len(storage_workers()) == 1
    assert len(threads.connected) == len(threads.closed) == 3
    assert len(set(threads.connected + threads.closed)) == 1
    assert threading.get_ident() not in threads.connected
    assert storage_workers() == []
    with client_for(app) as client:
        assert client.get(f"{API}/vaults").json() == []
    for name in ("a", "b", "c"):
        assert (tmp_path / name / ".page" / "vault.json").is_file()


def test_shutdown_waits_for_active_storage_work(app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "v"
    FileSystemVault.create(root, "v")
    (root / "a.md").write_text("a")
    entered, release = threading.Event(), threading.Event()
    events: list[str] = []
    list_paths = FileSystemVault.list_note_paths
    close = MetadataRepository.close

    def blocked_scan(self: FileSystemVault, **kwargs: Any) -> Any:
        if not entered.is_set():
            entered.set()
            assert release.wait(10)
        return list_paths(self, **kwargs)

    def record_close(repository: MetadataRepository) -> None:
        events.append("closed")
        close(repository)

    open_vault = LocalVaultService.open_vault

    def record_open(service: LocalVaultService, path: Path) -> Any:
        result = open_vault(service, path)
        events.append("opened")
        return result

    monkeypatch.setattr(FileSystemVault, "list_note_paths", blocked_scan)
    monkeypatch.setattr(MetadataRepository, "close", record_close)
    monkeypatch.setattr(LocalVaultService, "open_vault", record_open)
    statuses: list[int] = []

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app, client=PEER)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL, headers=AUTH) as client:
            lifespan = app.router.lifespan_context(app)
            await lifespan.__aenter__()
            request = asyncio.create_task(client.post(f"{API}/vaults/open", json={"root_path": str(root)}))
            assert await asyncio.to_thread(entered.wait, 10)
            shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
            for _ in range(20):
                await asyncio.sleep(0)
            assert not shutdown.done() and events == []
            release.set()
            statuses.append((await request).status_code)
            await shutdown

    asyncio.run(scenario())
    assert statuses == [200]
    assert events == ["opened", "closed"]
    assert storage_workers() == []
