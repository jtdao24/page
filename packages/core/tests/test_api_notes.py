import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_support import (  # noqa: F401 - app, client and vault are fixtures
    API, TOKEN, StorageThreads, app, assert_error, client, client_for, create_note, if_match, notes_url,
    posix_only, source_files, vault,
)
from page_core.api import create_app

pytestmark = posix_only

TRICKY = "﻿# Café ☃\r\nline two\rline three\n\n\U0001F600 no final newline"


def expected_revision(note: dict[str, Any], content: str) -> str:
    values = [note["vault_id"], note["id"], note["relative_path"], note["created_at"], note["updated_at"],
              hashlib.sha256(content.encode("utf-8")).hexdigest()]
    return hashlib.sha256(json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()


def assert_note(response: httpx.Response, status: int, content: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    note = response.json()
    assert set(note) == {"id", "vault_id", "relative_path", "created_at", "updated_at", "revision", "content"}
    assert note["content"] == content
    assert note["revision"] == expected_revision(note, content)
    assert response.headers["etag"] == f'"{note["revision"]}"'
    for field in ("created_at", "updated_at"):
        assert len(note[field]) == 32 and note[field].endswith("+00:00") and note[field][19] == "."
    return note


def test_complete_note_lifecycle_preserves_bytes_and_identity(client: TestClient, vault: dict[str, Any]) -> None:
    root = Path(vault["root_path"])
    created = client.post(notes_url(vault), json={"relative_path": "folder/sub/note.md", "content": TRICKY})
    note = assert_note(created, 201, TRICKY)
    assert created.headers["location"] == f"{API}/vaults/{vault['id']}/notes/{note['id']}"
    assert note["vault_id"] == vault["id"] and note["relative_path"] == "folder/sub/note.md"
    assert (root / "folder/sub/note.md").read_bytes() == TRICKY.encode("utf-8")
    assert assert_note(client.get(created.headers["location"]), 200, TRICKY) == note

    updated = assert_note(client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]),
                                     json={"content": "changed\r\n"}), 200, "changed\r\n")
    assert updated["id"] == note["id"] and updated["created_at"] == note["created_at"]
    assert updated["relative_path"] == note["relative_path"] and updated["revision"] != note["revision"]
    assert (root / "folder/sub/note.md").read_bytes() == b"changed\r\n"

    moved = assert_note(client.post(f"{notes_url(vault, note['id'])}/move", headers=if_match(updated["revision"]),
                                    json={"relative_path": "other/moved.md"}), 200, "changed\r\n")
    assert moved["id"] == note["id"] and moved["created_at"] == note["created_at"]
    assert not (root / "folder/sub/note.md").exists() and (root / "folder/sub").is_dir()
    renamed = assert_note(client.post(f"{notes_url(vault, note['id'])}/move", headers=if_match(moved["revision"]),
                                      json={"relative_path": "other/renamed.md"}), 200, "changed\r\n")
    assert renamed["id"] == note["id"] and (root / "other/renamed.md").read_bytes() == b"changed\r\n"
    same = assert_note(client.post(f"{notes_url(vault, note['id'])}/move", headers=if_match(renamed["revision"]),
                                   json={"relative_path": "other/renamed.md"}), 200, "changed\r\n")
    assert same["relative_path"] == "other/renamed.md"

    deleted = client.delete(notes_url(vault, note["id"]), headers=if_match(same["revision"]))
    assert deleted.status_code == 204 and deleted.content == b""
    assert not (root / "other/renamed.md").exists() and (root / "other").is_dir()
    assert_error(client.get(notes_url(vault, note["id"])), 404, "note_not_found")
    assert client.get(notes_url(vault)).json() == []
    recreated = create_note(client, vault, "other/renamed.md", "new")
    assert recreated["id"] != note["id"]
    assert client.get(f"{API}/vaults/{vault['id']}").json()["root_path"] == str(root)


def test_empty_content_is_the_default(client: TestClient, vault: dict[str, Any]) -> None:
    note = assert_note(client.post(notes_url(vault), json={"relative_path": "empty.md"}), 201, "")
    assert (Path(vault["root_path"]) / "empty.md").read_bytes() == b""
    assert assert_note(client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]),
                                  json={"content": ""}), 200, "")["id"] == note["id"]


def test_identity_survives_close_reopen_and_a_fresh_application(client: TestClient, vault: dict[str, Any]) -> None:
    note = create_note(client, vault, "a.md", "first")
    note = client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]), json={"content": "x"}).json()
    note = client.post(f"{notes_url(vault, note['id'])}/move", headers=if_match(note["revision"]),
                       json={"relative_path": "b/a.md"}).json()
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    assert client.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]}).status_code == 200
    assert client.get(notes_url(vault, note["id"])).json() == note
    with client_for(create_app(session_token=TOKEN)) as fresh:
        assert fresh.post(f"{API}/vaults/open", json={"root_path": vault["root_path"]}).status_code == 200
        again = fresh.get(notes_url(vault, note["id"])).json()
    assert (again["id"], again["created_at"], again["relative_path"]) == (note["id"], note["created_at"], "b/a.md")


def test_collections_are_sorted_content_free_summaries(client: TestClient, vault: dict[str, Any]) -> None:
    for path in ("z.md", "a/b.md", "a.md", "M.md", "é.md"):
        create_note(client, vault, path, f"content of {path}")
    gone = create_note(client, vault, "gone.md", "bye")
    assert client.delete(notes_url(vault, gone["id"]), headers=if_match(gone["revision"])).status_code == 204
    summaries = client.get(notes_url(vault)).json()
    assert [item["relative_path"] for item in summaries] == ["M.md", "a.md", "a/b.md", "z.md", "é.md"]
    for summary in summaries:
        assert set(summary) == {"id", "vault_id", "relative_path", "created_at", "updated_at", "revision"}
        full = client.get(notes_url(vault, summary["id"]))
        assert full.json()["revision"] == summary["revision"]
        assert full.headers["etag"] == f'"{summary["revision"]}"'


def test_listing_does_not_read_contents_and_survives_invalid_utf8(client: TestClient, vault: dict[str, Any],
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(vault["root_path"])
    good = create_note(client, vault, "good.md", "fine")
    (root / "bad.md").write_bytes(b"\xff\xfe broken")
    assert client.post(f"{API}/vaults/{vault['id']}/reconcile", json={}).json()["added"] == 1
    from page_core import vault as vault_module

    def forbidden(*args: Any) -> None:
        raise AssertionError("listing must not read note contents")

    with monkeypatch.context() as patch:
        patch.setattr(vault_module, "_read_regular_file", forbidden)
        summaries = client.get(notes_url(vault)).json()
    assert [item["relative_path"] for item in summaries] == ["bad.md", "good.md"]
    bad = summaries[0]
    assert_error(client.get(notes_url(vault, bad["id"])), 422, "unreadable_note")
    assert_error(client.put(notes_url(vault, bad["id"]), headers=if_match(bad["revision"]), json={"content": "x"}),
                 422, "unreadable_note")
    assert (root / "bad.md").read_bytes() == b"\xff\xfe broken"
    assert client.get(notes_url(vault, good["id"])).json()["content"] == "fine"


def test_ids_do_not_cross_vaults_or_resurrect_tombstones(client: TestClient, vault: dict[str, Any], tmp_path: Path) -> None:
    other = client.post(f"{API}/vaults", json={"root_path": str(tmp_path / "other"), "name": "Other"}).json()
    note = create_note(client, vault, "a.md", "a")
    assert_error(client.get(notes_url(other, note["id"])), 404, "note_not_found")
    assert_error(client.put(notes_url(other, note["id"]), headers=if_match(note["revision"]), json={"content": "x"}),
                 404, "note_not_found")
    assert_error(client.get(notes_url(vault, str(uuid4()))), 404, "note_not_found")
    assert client.delete(notes_url(vault, note["id"]), headers=if_match(note["revision"])).status_code == 204
    (Path(vault["root_path"]) / "a.md").write_text("a")
    assert_error(client.get(notes_url(vault, note["id"])), 404, "note_not_found")
    assert client.post(f"{API}/vaults/{vault['id']}/reconcile", json={}).json()["added"] == 1
    assert_error(client.get(notes_url(vault, note["id"])), 404, "note_not_found")
    assert (Path(vault["root_path"]) / "a.md").read_text() == "a"


def test_externally_missing_source_is_not_found(client: TestClient, vault: dict[str, Any]) -> None:
    note = create_note(client, vault, "a.md", "a")
    (Path(vault["root_path"]) / "a.md").unlink()
    assert_error(client.get(notes_url(vault, note["id"])), 404, "note_not_found")
    assert_error(client.delete(notes_url(vault, note["id"]), headers=if_match(note["revision"])), 404, "note_not_found")


BAD_PATHS = [
    "../outside.md", "a/../b.md", "..", ".hidden.md", "dir/.git/x.md", ".page/vault.md", "CON.md", "aux.md",
    "dir/LPT1.md", "a:b.md", "a\\b.md", "a<b.md", 'a"b.md', "a|b.md", "a?b.md", "a*b.md", "tab\t.md",
    "dir /a.md", "dir./a.md", "x.txt", "x.MD", "x.md.txt", "/abs.md", "a//b.md", "./a.md",
    "a/./b.md", "dir/", "a.md/", "", ".md", "nul\u0000.md",
]


@pytest.mark.parametrize("path", BAD_PATHS)
def test_unsafe_or_noncanonical_paths_are_rejected_without_mutation(client: TestClient, vault: dict[str, Any],
                                                                    tmp_path: Path, path: str) -> None:
    root = Path(vault["root_path"])
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    note = create_note(client, vault, "keep.md", "keep")
    before = source_files(root)
    error = assert_error(client.post(notes_url(vault), json={"relative_path": path, "content": "x"}),
                         422, "validation_error")
    assert error["details"]["errors"][0]["location"] == ["body", "relative_path"]
    assert_error(client.post(f"{notes_url(vault, note['id'])}/move", headers=if_match(note["revision"]),
                             json={"relative_path": path}), 422, "validation_error")
    assert source_files(root) == before
    assert outside.read_text() == "outside"


def test_symlinked_destinations_are_refused(client: TestClient, vault: dict[str, Any], tmp_path: Path,
                                            symlinks: None) -> None:
    root = Path(vault["root_path"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "existing.md").write_text("outside")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "file.md").symlink_to(outside / "existing.md")
    note = create_note(client, vault, "a.md", "a")
    for path in ("link/new.md", "link/existing.md", "file.md"):
        assert_error(client.post(notes_url(vault), json={"relative_path": path, "content": "x"}), 422, "validation_error")
        response = client.post(f"{notes_url(vault, note['id'])}/move", headers=if_match(note["revision"]),
                               json={"relative_path": path})
        assert response.status_code in (409, 422)
    assert sorted(item.name for item in outside.iterdir()) == ["existing.md"]
    assert (outside / "existing.md").read_text() == "outside"
    assert (root / "a.md").read_text() == "a"


def test_directory_case_must_match_exactly(client: TestClient, vault: dict[str, Any], case_insensitive: bool) -> None:
    create_note(client, vault, "Folder/a.md", "a")
    response = client.post(notes_url(vault), json={"relative_path": "folder/b.md", "content": "b"})
    if case_insensitive:
        assert_error(response, 422, "validation_error")
        assert not (Path(vault["root_path"]) / "Folder" / "b.md").exists()
    else:
        assert response.status_code == 201


def test_occupied_destinations_are_never_overwritten(client: TestClient, vault: dict[str, Any]) -> None:
    first = create_note(client, vault, "a.md", "a")
    create_note(client, vault, "b.md", "b")
    assert_error(client.post(notes_url(vault), json={"relative_path": "a.md", "content": "x"}), 409, "note_exists")
    assert_error(client.post(f"{notes_url(vault, first['id'])}/move", headers=if_match(first["revision"]),
                             json={"relative_path": "b.md"}), 409, "note_exists")
    root = Path(vault["root_path"])
    assert (root / "a.md").read_text() == "a" and (root / "b.md").read_text() == "b"


@pytest.mark.parametrize("body", [
    {"content": 1}, {"content": None}, {}, {"content": "x", "relative_path": "b.md"}, {"content": ["x"]},
    {"content": "x", "id": "00000000-0000-4000-8000-000000000001"}, {"content": "x", "revision": "0" * 64},
])
def test_update_bodies_are_strict(client: TestClient, vault: dict[str, Any], body: dict[str, Any]) -> None:
    note = create_note(client, vault, "a.md", "a")
    assert_error(client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]), json=body),
                 422, "validation_error")
    assert (Path(vault["root_path"]) / "a.md").read_text() == "a"


@pytest.mark.parametrize("body", [
    {"relative_path": "a.md", "content": None}, {"relative_path": "a.md", "content": 5}, {"relative_path": None},
    {"content": "x"}, {"relative_path": "a.md", "created_at": "2026-01-01T00:00:00.000000+00:00"},
    {"relative_path": "a.md", "id": "00000000-0000-4000-8000-000000000001"}, {"relative_path": 1},
])
def test_create_bodies_are_strict(client: TestClient, vault: dict[str, Any], body: dict[str, Any]) -> None:
    assert_error(client.post(notes_url(vault), json=body), 422, "validation_error")
    assert source_files(Path(vault["root_path"])) == {".page/vault.json": (Path(vault["root_path"]) / ".page/vault.json").read_bytes()}


def test_unencodable_content_is_rejected_before_mutation(client: TestClient, vault: dict[str, Any]) -> None:
    note = create_note(client, vault, "a.md", "a")
    headers = {"Content-Type": "application/json", **if_match(note["revision"])}
    for surrogate in ("\\ud800", "\\udfff", "x\\ud83d"):
        response = client.put(notes_url(vault, note["id"]), headers=headers,
                              content=('{"content": "%s"}' % surrogate).encode())
        assert_error(response, 422, "validation_error")
        response = client.post(notes_url(vault), headers={"Content-Type": "application/json"},
                               content=('{"relative_path": "b.md", "content": "%s"}' % surrogate).encode())
        assert_error(response, 422, "validation_error")
    assert source_files(Path(vault["root_path"]))["a.md"] == b"a"
    assert not (Path(vault["root_path"]) / "b.md").exists()


@pytest.mark.parametrize("value,status", [
    (None, 428), ("*", 422), ('W/"{rev}"', 422), ("{rev}", 422), ('"{rev}", "{rev}"', 422), ('"{REV}"', 422),
    ('"{rev}0"', 422), ("''", 422), ('""', 422), ("[duplicate]", 422),
])
def test_if_match_is_required_and_strict(client: TestClient, vault: dict[str, Any], value: str | None,
                                         status: int) -> None:
    note = create_note(client, vault, "a.md", "a")
    rev = note["revision"]
    if value is None:
        headers: list[tuple[str, str]] = []
    elif value == "[duplicate]":
        headers = [("If-Match", f'"{rev}"'), ("If-Match", f'"{rev}"')]
    else:
        headers = [("If-Match", value.format(rev=rev, REV=rev.upper()))]
    code = "precondition_required" if status == 428 else "validation_error"
    requests = [
        ("PUT", notes_url(vault, note["id"]), {"content": "x"}),
        ("POST", f"{notes_url(vault, note['id'])}/move", {"relative_path": "b.md"}),
        ("DELETE", notes_url(vault, note["id"]), None),
    ]
    for method, url, body in requests:
        assert_error(client.request(method, url, headers=headers, json=body), status, code)
    assert source_files(Path(vault["root_path"]))["a.md"] == b"a"


def test_if_match_allows_surrounding_whitespace(client: TestClient, vault: dict[str, Any]) -> None:
    note = create_note(client, vault, "a.md", "a")
    response = client.put(notes_url(vault, note["id"]), headers={"If-Match": f' "{note["revision"]}" '},
                          json={"content": "b"})
    assert response.status_code == 200


def test_stale_revisions_after_api_edits_and_moves(client: TestClient, vault: dict[str, Any]) -> None:
    root = Path(vault["root_path"])
    original = create_note(client, vault, "a.md", "one")
    edited = client.put(notes_url(vault, original["id"]), headers=if_match(original["revision"]),
                        json={"content": "two"}).json()
    stale = if_match(original["revision"])
    assert_error(client.put(notes_url(vault, original["id"]), headers=stale, json={"content": "three"}),
                 412, "revision_conflict")
    assert_error(client.post(f"{notes_url(vault, original['id'])}/move", headers=stale, json={"relative_path": "b.md"}),
                 412, "revision_conflict")
    assert_error(client.delete(notes_url(vault, original["id"]), headers=stale), 412, "revision_conflict")
    assert source_files(root)["a.md"] == b"two"
    moved = client.post(f"{notes_url(vault, original['id'])}/move", headers=if_match(edited["revision"]),
                        json={"relative_path": "b.md"}).json()
    for headers in (if_match(edited["revision"]), if_match(original["revision"])):
        assert_error(client.put(notes_url(vault, original["id"]), headers=headers, json={"content": "x"}),
                     412, "revision_conflict")
        assert_error(client.delete(notes_url(vault, original["id"]), headers=headers), 412, "revision_conflict")
    assert sorted(path for path in source_files(root) if path.endswith(".md")) == ["b.md"]
    assert source_files(root)["b.md"] == b"two"
    assert client.put(notes_url(vault, original["id"]), headers=if_match(moved["revision"]),
                      json={"content": "three"}).status_code == 200


def test_external_change_with_same_size_and_mtime_conflicts(client: TestClient, vault: dict[str, Any]) -> None:
    path = Path(vault["root_path"]) / "a.md"
    note = create_note(client, vault, "a.md", "before")
    info = path.stat()
    path.write_bytes(b"after!")
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert path.stat().st_size == info.st_size and path.stat().st_mtime_ns == info.st_mtime_ns
    for method, url, body in [("PUT", notes_url(vault, note["id"]), {"content": "mine"}),
                              ("POST", f"{notes_url(vault, note['id'])}/move", {"relative_path": "b.md"}),
                              ("DELETE", notes_url(vault, note["id"]), None)]:
        assert_error(client.request(method, url, headers=if_match(note["revision"]), json=body),
                     412, "revision_conflict")
    assert path.read_bytes() == b"after!"
    fresh = client.get(notes_url(vault, note["id"])).json()
    assert fresh["content"] == "after!" and fresh["id"] == note["id"] and fresh["created_at"] == note["created_at"]
    assert client.put(notes_url(vault, note["id"]), headers=if_match(fresh["revision"]),
                      json={"content": "mine"}).status_code == 200
    assert path.read_bytes() == b"mine"


def test_external_edit_invalidates_revision_and_reread_succeeds(client: TestClient, vault: dict[str, Any]) -> None:
    path = Path(vault["root_path"]) / "a.md"
    note = create_note(client, vault, "a.md", "before")
    path.write_text("edited elsewhere, longer")
    assert_error(client.delete(notes_url(vault, note["id"]), headers=if_match(note["revision"])),
                 412, "revision_conflict")
    assert path.read_text() == "edited elsewhere, longer"
    fresh = client.get(notes_url(vault, note["id"])).json()
    assert client.delete(notes_url(vault, note["id"]), headers=if_match(fresh["revision"])).status_code == 204
    assert not path.exists()


def test_concurrent_mutations_serialize_with_one_winner(app: FastAPI, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    threads = StorageThreads(monkeypatch)
    with client_for(app) as client:
        vault = client.post(f"{API}/vaults", json={"root_path": str(tmp_path / "v"), "name": "v"}).json()
        note = create_note(client, vault, "a.md", "original")
        barrier = threading.Barrier(2)

        def update(content: str) -> httpx.Response:
            barrier.wait(10)
            return client.put(notes_url(vault, note["id"]), headers=if_match(note["revision"]),
                              json={"content": content})

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(update, ["first", "second"]))
        assert sorted(response.status_code for response in results) == [200, 412]
        winner = next(response for response in results if response.status_code == 200).json()
        assert (Path(vault["root_path"]) / "a.md").read_text() == winner["content"]
        assert client.get(notes_url(vault)).json()[0]["revision"] == winner["revision"]

        barrier = threading.Barrier(2)

        def create(content: str) -> httpx.Response:
            barrier.wait(10)
            return client.post(notes_url(vault), json={"relative_path": "same.md", "content": content})

        with ThreadPoolExecutor(2) as pool:
            created = list(pool.map(create, ["one", "two"]))
        assert sorted(response.status_code for response in created) == [201, 409]
        loser = next(response for response in created if response.status_code == 409)
        assert loser.json()["error"]["code"] == "note_exists"
        winner = next(response for response in created if response.status_code == 201).json()
        assert (Path(vault["root_path"]) / "same.md").read_text() == winner["content"]
        assert [item["relative_path"] for item in client.get(notes_url(vault)).json()] == ["a.md", "same.md"]
    owners = set(threads.connected) | set(threads.closed)
    assert len(owners) == 1 and threading.get_ident() not in owners
    assert len(threads.connected) == len(threads.closed) == 1
