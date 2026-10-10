import hashlib
from importlib.util import find_spec
import json
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import PurePosixPath
from uuid import uuid4

import pytest

np = pytest.importorskip("numpy")
if find_spec("faiss") is None or find_spec("torch") is None:
    pytest.skip("install the ingestion extra", allow_module_level=True)

from page_core.ingestion.chunking import chunk_markdown
from page_core.ingestion.index import IngestionIndex
from page_core.ingestion.scanner import scan
from page_core.ingestion.server import create_server
from page_core.vault import FileSystemVault


class CharacterTokenizer:
    def encode(self, text, **kwargs):
        return list(text)


class FakeEmbedder:
    key = "test-v1"
    dimension = 8
    tokenizer = CharacterTokenizer()

    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.extend(texts)
        return np.array([list(hashlib.sha256(t.encode()).digest()[:8]) for t in texts], dtype="float32") + 1


@pytest.fixture
def index(fs_vault):
    return IngestionIndex(fs_vault, FakeEmbedder(), budget=40)


def rows(index, table):
    with sqlite3.connect(index.database) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]


def test_chunk_budget_unicode_provenance_and_headings():
    text = "intro 😀\n\n# First\n" + "長い文 hello " * 25 + "\n## Child\nbody\n"
    chunks = chunk_markdown(uuid4(), text, CharacterTokenizer(), budget=35)
    assert len(chunks) > 3
    for span in chunks:
        chunk = span.chunk
        assert len(chunk.text) == chunk.token_count <= 35
        assert text.encode()[chunk.start_byte:chunk.end_byte].decode() == chunk.text
        assert span.start_line <= span.end_line
    assert chunks[0].headings == ()
    assert chunks[-1].headings == ("First", "Child")


def test_fenced_headings_setext_empty_and_deterministic():
    text = "Title\n=====\n```md\n# fake\n```\ntext\n## Real\nend"
    identifier = uuid4()
    chunks = chunk_markdown(identifier, text, CharacterTokenizer(), budget=100)
    assert [c.headings for c in chunks] == [("Title",), ("Title", "Real")]
    assert chunks == chunk_markdown(identifier, text, CharacterTokenizer(), budget=100)
    assert chunk_markdown(identifier, "   \n", CharacterTokenizer()) == []
    with pytest.raises(ValueError):
        chunk_markdown(identifier, text, CharacterTokenizer(), budget=255)


def test_persistence_normalization_ids_and_source(index, fs_vault):
    note = fs_vault.create_note(PurePosixPath("a.md"), "# A\nhello world\n")
    index.update()
    assert rows(index, "notes")[0]["id"] == str(note.id)
    stored = rows(index, "vectors")[0]["vector"]
    assert np.linalg.norm(np.frombuffer(stored, dtype="<f4")) == pytest.approx(1)
    reopened_vault = FileSystemVault.open(fs_vault.vault.root_path)
    reopened = IngestionIndex(reopened_vault, FakeEmbedder(), budget=40)
    assert reopened_vault.read_note(PurePosixPath("a.md")).id == note.id
    result = reopened.search("# A\nhello world\n")[0]
    assert result["score"] == pytest.approx(1)
    assert result["note_id"] == str(note.id)
    assert result["headings"] == ["A"]
    assert note.content.encode()[result["start_byte"]:result["end_byte"]].decode() == result["text"]


def test_existing_vault_identity_is_reused(fs_vault):
    note = fs_vault.create_note(PurePosixPath("existing.md"), "existing")
    index = IngestionIndex(fs_vault, FakeEmbedder())
    index.update()
    assert rows(index, "notes")[0]["id"] == str(note.id)


def test_context_inventory_tracks_committed_notes_without_embedding(index, fs_vault):
    note = fs_vault.create_note(PurePosixPath("ideas/a.md"), "# A title\nA thought.")
    empty = fs_vault.create_note(PurePosixPath("empty.md"), "")
    index.update()
    calls = list(index.embedder.calls)
    inventory = {n["id"]: n for n in index.list_context()}
    assert inventory[str(note.id)]["title"] == "A title"
    assert inventory[str(note.id)]["excerpt"] == "A thought."
    assert inventory[str(note.id)]["chunks"] == 1
    assert inventory[str(empty.id)]["chunks"] == 0
    assert inventory[str(empty.id)]["title"] == "empty"
    assert index.embedder.calls == calls
    moved = fs_vault.move_note(note, PurePosixPath("renamed.md"))
    index.update()
    assert next(n for n in index.list_context() if n["id"] == str(note.id))["path"] == "renamed.md"
    fs_vault.delete_note(moved)
    index.update()
    assert [n["id"] for n in index.list_context()] == [str(empty.id)]


def test_incremental_edit_rename_delete(index, fs_vault):
    path = PurePosixPath("a.md")
    note = fs_vault.create_note(path, "# A\nfirst\n## B\nsecond\n")
    first = index.update()
    assert first["embedded"] == 2
    assert index.update()["skipped"] == 1
    fs_vault.update_note(note, "# A\nfirst\n## B\nedited\n")
    edited = index.update()
    assert edited["embedded"] == 1 and edited["reused"] == 1
    (fs_vault.vault.root_path / "a.md").rename(fs_vault.vault.root_path / "renamed.md")
    assert index.update()["embedded"] == 0
    assert rows(index, "notes")[0]["id"] == str(note.id)
    assert index.search("first")[0]["path"] == "renamed.md"
    (fs_vault.vault.root_path / "renamed.md").unlink()
    assert index.update()["deleted"] == 1
    assert index.search("first") == []
    assert rows(index, "vectors") == []


def test_same_size_mtime_edit_detected(index, fs_vault):
    import os
    fs_vault.create_note(PurePosixPath("a.md"), "before")
    index.update()
    path = fs_vault.vault.root_path / "a.md"
    before = path.stat()
    path.write_text("after!")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert index.update()["changed"] == 1
    assert rows(index, "chunks")[0]["text"] == "after!"


def test_renamed_path_recreated_gets_new_identity(index, fs_vault):
    original = fs_vault.create_note(PurePosixPath("a.md"), "original")
    index.update()
    root = fs_vault.vault.root_path
    (root / "a.md").rename(root / "b.md")
    index.update()
    (root / "a.md").write_text("new note")
    index.update()
    stored = {r["path"]: r["id"] for r in rows(index, "notes")}
    assert stored["b.md"] == str(original.id)
    assert stored["a.md"] != str(original.id)


@pytest.mark.parametrize("damage", ["missing", "corrupt", "stale"])
def test_index_recovery(index, fs_vault, damage):
    fs_vault.create_note(PurePosixPath("a.md"), "recover me")
    empty_artifact = index.artifact.read_bytes()
    index.update()
    if damage == "missing":
        index.artifact.unlink()
    else:
        index.artifact.write_bytes(b"broken" if damage == "corrupt" else empty_artifact)
    reopened = IngestionIndex(FileSystemVault.open(fs_vault.vault.root_path), FakeEmbedder(), budget=40)
    assert reopened.search("recover me")[0]["text"] == "recover me"
    assert reopened.embedder.calls == ["recover me"]  # Query only; recovery embeds nothing.


def test_rebuild_reuses_vectors(index, fs_vault):
    fs_vault.create_note(PurePosixPath("a.md"), "hello")
    index.update()
    result = index.update(rebuild=True)
    assert result["embedded"] == 0 and result["reused"] == 1


def test_duplicate_chunk_cache_and_unchanged_generation(index, fs_vault):
    fs_vault.create_note(PurePosixPath("a.md"), "same content")
    fs_vault.create_note(PurePosixPath("b.md"), "same content")
    assert index.update()["embedded"] == 1
    assert len(rows(index, "notes")) == 2
    assert len(rows(index, "vectors")) == 1
    assert len({r["vector_id"] for r in rows(index, "chunks")}) == 2
    generation = index._generation
    index.update()
    assert index._generation == generation


def test_second_instance_refreshes_mapping(index, fs_vault):
    fs_vault.create_note(PurePosixPath("a.md"), "old")
    index.update()
    second = IngestionIndex(FileSystemVault.open(fs_vault.vault.root_path), FakeEmbedder(), budget=40)
    (fs_vault.vault.root_path / "a.md").write_text("new")
    index.update()
    assert second.search("new")[0]["text"] == "new"


@pytest.mark.parametrize("target", ["file", "directory"])
def test_scanner_symlink_swap_race(fs_vault, tmp_path, symlinks, monkeypatch, target):
    import os

    root = fs_vault.vault.root_path
    (root / "folder").mkdir()
    (root / "folder" / "a.md").write_text("safe")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.md").write_text("secret")
    original = os.open
    swapped = False
    def race(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and path == ("folder" if target == "directory" else "a.md"):
            swapped = True
            if target == "directory":
                (root / "folder").rename(root / "saved")
                (root / "folder").symlink_to(outside, target_is_directory=True)
            else:
                (root / "folder" / "a.md").unlink()
                (root / "folder" / "a.md").symlink_to(outside / "a.md")
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", race)
    # The capability check also uses function identity.
    monkeypatch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, race})
    with pytest.raises(OSError):
        scan(root)


def test_changed_chunk_configuration_reuses_vectors(index, fs_vault):
    fs_vault.create_note(PurePosixPath("a.md"), "short")
    index.update()
    other = IngestionIndex(fs_vault, FakeEmbedder(), budget=30)
    with pytest.raises(ValueError, match="configuration changed"):
        other.search("short")
    assert other.update()["reused"] == 1
    assert other.search("short")[0]["text"] == "short"


def test_failed_embedding_preserves_previous_index(index, fs_vault):
    note = fs_vault.create_note(PurePosixPath("a.md"), "hello")
    index.update()
    fs_vault.update_note(note, "changed")
    encode = index.embedder.encode
    index.embedder.encode = lambda texts: np.zeros((len(texts), 8))
    with pytest.raises(RuntimeError, match="zero embedding"):
        index.update()
    assert rows(index, "chunks")[0]["text"] == "hello"
    index.embedder.encode = encode
    assert index.search("hello")[0]["text"] == "hello"
    assert index.update()["state"] == "complete"


def test_artifact_publication_failure_recovers_committed_vectors(index, fs_vault, monkeypatch):
    note = fs_vault.create_note(PurePosixPath("a.md"), "old")
    index.update()
    fs_vault.update_note(note, "committed new text")
    rebuild = index._rebuild
    def fail(db):
        raise OSError("simulated artifact publication failure")
    monkeypatch.setattr(index, "_rebuild", fail)
    with pytest.raises(RuntimeError, match="publication failure"):
        index.update()
    assert rows(index, "chunks")[0]["text"] == "committed new text"
    monkeypatch.setattr(index, "_rebuild", rebuild)
    assert index.search("committed new text")[0]["text"] == "committed new text"


def test_invalid_utf8_aborts_without_deleting(index, fs_vault):
    fs_vault.create_note(PurePosixPath("a.md"), "hello")
    index.update()
    (fs_vault.vault.root_path / "a.md").write_bytes(b"\xff")
    with pytest.raises(RuntimeError, match="UnicodeDecodeError"):
        index.update()
    assert len(rows(index, "notes")) == 1


def test_scanner_skips_symlinks_hidden_unsafe_and_special(fs_vault, tmp_path, symlinks):
    root = fs_vault.vault.root_path
    fs_vault.create_note(PurePosixPath("good.md"), "good")
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    (root / "link.md").symlink_to(outside)
    (root / "directory").symlink_to(tmp_path, target_is_directory=True)
    (root / ".hidden.md").write_text("hidden")
    (root / "CON.md").write_text("unsafe")
    import os
    os.mkfifo(root / "pipe.md")
    assert [str(d.path) for d in scan(root)] == ["good.md"]
    with pytest.raises(ValueError, match="exceeds"):
        scan(root, max_bytes=1)


def test_metadata_symlink_rejected(fs_vault, tmp_path, symlinks):
    (fs_vault.vault.root_path / ".page" / "ingestion").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        IngestionIndex(fs_vault, FakeEmbedder())


def test_background_status_and_single_writer(index, fs_vault):
    fs_vault.create_note(PurePosixPath("a.md"), "hello")
    entered = threading.Event()
    release = threading.Event()
    encode = index.embedder.encode
    def slow(texts):
        entered.set()
        assert release.wait(5)
        return encode(texts)
    index.embedder.encode = slow
    assert index.start()
    assert entered.wait(5)
    assert index.status()["state"] == "running"
    assert not index.start()
    release.set()
    index.wait(5)
    assert index.status()["state"] == "complete"


def test_api_auth_origin_and_development_gate(index):
    token = "x" * 32
    server = create_server(index, token=token, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url + "/api/index/status")
        assert error.value.code == 401
        headers = {"Authorization": f"Bearer {token}"}
        request = urllib.request.Request(url + "/api/index/status", headers=headers)
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["state"] == "idle"
        request = urllib.request.Request(url + "/api/context", headers=headers)
        with urllib.request.urlopen(request) as response:
            assert json.load(response) == {"notes": []}
        request = urllib.request.Request(url + "/api/dev/search", data=b'{}', headers=headers)
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 404
        request = urllib.request.Request(url + "/api/index/status", headers={**headers, "Origin": "https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
