import json
import os
import subprocess
import sys
from datetime import UTC
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from conftest import snapshot
from page_core.domain import Note
from page_core.vault import (
    FileSystemVault,
    NoteExistsError,
    NoteNotFoundError,
    VaultError,
    VaultExistsError,
    VaultNotFoundError,
)

P = PurePosixPath


# --- Vault creation and opening -------------------------------------------


def test_create_writes_manifest_and_domain_vault(vault_root: Path) -> None:
    fs = FileSystemVault.create(vault_root, "Research", id_factory=lambda: UUID(int=7))

    assert fs.vault.id == UUID(int=7)
    assert fs.vault.name == "Research"
    assert fs.vault.root_path == vault_root.resolve()
    manifest = json.loads((vault_root / ".page" / "vault.json").read_text())
    assert manifest == {"format": 1, "id": str(UUID(int=7)), "name": "Research"}


def test_create_adopts_existing_folder_without_touching_notes(vault_root: Path) -> None:
    vault_root.mkdir()
    (vault_root / "existing.md").write_bytes(b"keep\n")

    fs = FileSystemVault.create(vault_root, "Research")

    assert fs.list_note_paths() == [P("existing.md")]
    assert (vault_root / "existing.md").read_bytes() == b"keep\n"


def test_create_refuses_existing_vault(fs_vault: FileSystemVault, vault_root: Path) -> None:
    before = snapshot(vault_root)

    with pytest.raises(VaultExistsError):
        FileSystemVault.create(vault_root, "Other")
    assert snapshot(vault_root) == before


def test_create_validates_name_before_touching_disk(vault_root: Path) -> None:
    with pytest.raises(ValueError):
        FileSystemVault.create(vault_root, "  ")
    assert not vault_root.exists()


def test_open_reads_identity_from_manifest(fs_vault: FileSystemVault, vault_root: Path) -> None:
    reopened = FileSystemVault.open(vault_root)

    assert reopened.vault == fs_vault.vault


def test_vault_identity_survives_moving_the_folder(
    fs_vault: FileSystemVault, vault_root: Path, tmp_path: Path
) -> None:
    moved = tmp_path / "moved"
    vault_root.rename(moved)

    reopened = FileSystemVault.open(moved)

    assert reopened.vault.id == fs_vault.vault.id
    assert reopened.vault.root_path == moved.resolve()


def test_open_missing_directory_creates_nothing(tmp_path: Path) -> None:
    with pytest.raises(VaultNotFoundError):
        FileSystemVault.open(tmp_path / "typo")
    assert not (tmp_path / "typo").exists()


def test_open_plain_folder_is_not_a_vault(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("x")

    with pytest.raises(VaultNotFoundError):
        FileSystemVault.open(tmp_path)
    assert not (tmp_path / ".page").exists()


@pytest.mark.parametrize(
    "manifest",
    [b"not json", b"[]", b'{"format": 1, "id": "bad", "name": "x"}', b'{"format": 2}'],
)
def test_open_rejects_invalid_manifest(tmp_path: Path, manifest: bytes) -> None:
    (tmp_path / ".page").mkdir()
    (tmp_path / ".page" / "vault.json").write_bytes(manifest)

    with pytest.raises(VaultError):
        FileSystemVault.open(tmp_path)


def test_rejects_non_path_root(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        FileSystemVault.create(str(tmp_path), "Research")  # type: ignore[arg-type]


# --- Listing ----------------------------------------------------------------


def test_lists_markdown_recursively_and_sorted(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / "b.md").write_text("")
    (vault_root / "projects" / "deep").mkdir(parents=True)
    (vault_root / "projects" / "deep" / "a.md").write_text("")
    (vault_root / "projects" / "readme.txt").write_text("")
    (vault_root / "Upper.MD").write_text("")
    (vault_root / ".obsidian").mkdir()
    (vault_root / ".obsidian" / "hidden.md").write_text("")
    (vault_root / ".dotfile.md").write_text("")

    assert fs_vault.list_note_paths() == [P("b.md"), P("projects/deep/a.md")]


def test_listing_does_not_read_or_decode_notes(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / "latin1.md").write_bytes("café".encode("latin-1"))

    assert fs_vault.list_note_paths() == [P("latin1.md")]


# --- CRUD ------------------------------------------------------------------


def test_create_and_read_note(fs_vault: FileSystemVault, vault_root: Path) -> None:
    created = fs_vault.create_note(P("projects/plan.md"), "# Plan\n")

    assert (vault_root / "projects" / "plan.md").read_bytes() == b"# Plan\n"
    assert isinstance(created, Note)
    assert created.id == UUID(int=2)  # 1 is the vault
    assert created.vault_id == fs_vault.vault.id
    assert created.relative_path == P("projects/plan.md")
    assert created.content == "# Plan\n"
    assert created.created_at.tzinfo is UTC
    assert created.created_at <= created.updated_at
    assert fs_vault.read_note(P("projects/plan.md")) == created


def test_empty_note(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("empty.md"))

    assert note.content == ""
    assert (vault_root / "empty.md").read_bytes() == b""


def test_unicode_round_trip(fs_vault: FileSystemVault, vault_root: Path) -> None:
    text = "Ünïcødé ✓ 日本語 🚀\n"

    note = fs_vault.create_note(P("日本/ノート.md"), text)

    assert (vault_root / "日本" / "ノート.md").read_bytes() == text.encode("utf-8")
    assert fs_vault.read_note(note.relative_path).content == text


def test_duplicate_create_does_not_overwrite(fs_vault: FileSystemVault, vault_root: Path) -> None:
    fs_vault.create_note(P("plan.md"), "original")

    with pytest.raises(NoteExistsError):
        fs_vault.create_note(P("plan.md"), "replacement")
    assert (vault_root / "plan.md").read_text() == "original"


def test_create_refuses_existing_non_markdown_target(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / "folder.md").mkdir()

    with pytest.raises(NoteExistsError):
        fs_vault.create_note(P("folder.md"), "x")


def test_read_missing_note(fs_vault: FileSystemVault) -> None:
    with pytest.raises(NoteNotFoundError):
        fs_vault.read_note(P("missing.md"))


def test_update_note(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("plan.md"), "v1")

    updated = fs_vault.update_note(note, "v2")

    assert updated.id == note.id
    assert updated.content == "v2"
    assert (vault_root / "plan.md").read_text() == "v2"


def test_delete_note_removes_only_that_file(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("projects/plan.md"), "x")
    fs_vault.create_note(P("projects/other.md"), "y")
    (vault_root / "projects" / "image.png").write_bytes(b"\x89PNG")
    before = snapshot(vault_root)

    fs_vault.delete_note(note)

    del before["projects/plan.md"]
    assert snapshot(vault_root) == before
    assert (vault_root / "projects").is_dir()
    with pytest.raises(NoteNotFoundError):
        fs_vault.read_note(P("projects/plan.md"))


def test_operations_do_not_modify_unrelated_files(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / "unrelated.md").write_bytes(b"untouched\r\n")
    (vault_root / "notes.txt").write_bytes(b"text")
    unrelated = {k: v for k, v in snapshot(vault_root).items() if not k.startswith("work")}

    note = fs_vault.create_note(P("work/a.md"), "a")
    note = fs_vault.update_note(note, "b")
    note = fs_vault.move_note(note, P("work/sub/b.md"))
    fs_vault.delete_note(note)

    after = snapshot(vault_root)
    assert {k: v for k, v in after.items() if not k.startswith("work")} == unrelated
    assert not any(name.endswith(".tmp") for name in after)


# --- Identity, rename, move -----------------------------------------------


def test_reading_twice_returns_same_identity(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / "plan.md").write_text("x")

    assert fs_vault.read_note(P("plan.md")).id == fs_vault.read_note(P("plan.md")).id


def test_rename_keeps_identity_directory_and_content(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("projects/alpha.md"), "body")

    renamed = fs_vault.rename_note(note, "beta.md")

    assert renamed.relative_path == P("projects/beta.md")
    assert renamed.id == note.id
    assert renamed.content == "body"
    assert not (vault_root / "projects" / "alpha.md").exists()
    assert fs_vault.read_note(P("projects/beta.md")).id == note.id


def test_move_between_directories(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("inbox/idea.md"), "body")

    moved = fs_vault.move_note(note, P("archive/2026/idea.md"))

    assert moved.id == note.id
    assert moved.content == "body"
    assert moved.updated_at == note.updated_at
    assert (vault_root / "archive" / "2026" / "idea.md").read_text() == "body"
    assert not (vault_root / "inbox" / "idea.md").exists()
    assert (vault_root / "inbox").is_dir()


def test_move_never_overwrites_destination(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("a.md"), "a")
    fs_vault.create_note(P("b.md"), "b")

    with pytest.raises(NoteExistsError):
        fs_vault.move_note(note, P("b.md"))
    assert (vault_root / "a.md").read_text() == "a"
    assert (vault_root / "b.md").read_text() == "b"
    assert fs_vault.read_note(P("a.md")) == note
    assert fs_vault.move_note(note, P("c.md")).id == note.id


@pytest.mark.usefixtures("hardlinks")
@pytest.mark.parametrize(
    ("operation", "destination"),
    [("move", "b.md"), ("move", "archive/a.md"), ("rename", "b.md")],
)
def test_hard_link_to_same_file_is_an_occupied_destination(
    fs_vault: FileSystemVault, vault_root: Path, destination: str, operation: str
) -> None:
    note = fs_vault.create_note(P("a.md"), "body")
    other = vault_root / destination
    other.parent.mkdir(exist_ok=True)
    os.link(vault_root / "a.md", other)
    before = snapshot(vault_root)

    with pytest.raises(NoteExistsError):
        if operation == "move":
            fs_vault.move_note(note, P(destination))
        else:
            fs_vault.rename_note(note, P(destination).name)

    assert snapshot(vault_root) == before
    assert os.path.samefile(vault_root / "a.md", other)
    assert fs_vault.read_note(P("a.md")) == note
    assert fs_vault.read_note(P(destination)).id != note.id
    moved = fs_vault.move_note(note, P("c.md"))
    assert moved.id == note.id
    assert not (vault_root / "a.md").exists()
    assert other.read_text() == "body"


def test_move_to_same_path_is_a_no_op(fs_vault: FileSystemVault) -> None:
    note = fs_vault.create_note(P("a.md"), "a")

    assert fs_vault.move_note(note, P("a.md")) == note


def test_case_only_rename(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("Gamma.md"), "g")

    renamed = fs_vault.rename_note(note, "gamma.md")

    assert renamed.id == note.id
    assert renamed.relative_path == P("gamma.md")
    assert renamed.content == "g"
    assert sorted(os.listdir(vault_root)) == [".page", "gamma.md"]
    with pytest.raises(NoteNotFoundError):
        fs_vault.read_note(P("Gamma.md"))


def test_case_variant_cannot_duplicate_on_case_insensitive_fs(
    fs_vault: FileSystemVault, case_insensitive: bool
) -> None:
    if not case_insensitive:
        pytest.skip("filesystem is case-sensitive")
    fs_vault.create_note(P("Alpha.md"), "a")

    with pytest.raises(NoteExistsError):
        fs_vault.create_note(P("alpha.md"), "b")
    with pytest.raises(NoteNotFoundError):
        fs_vault.read_note(P("alpha.md"))


@pytest.mark.parametrize("name", ["", "a/b.md", ".", ".."])
def test_rename_rejects_non_file_names(fs_vault: FileSystemVault, name: str) -> None:
    note = fs_vault.create_note(P("a.md"), "a")

    with pytest.raises(ValueError):
        fs_vault.rename_note(note, name)


def test_identities_are_not_persisted_across_instances(
    fs_vault: FileSystemVault, vault_root: Path
) -> None:
    note = fs_vault.create_note(P("a.md"), "a")

    reopened = FileSystemVault.open(vault_root, id_factory=lambda: UUID(int=99))

    assert reopened.read_note(P("a.md")).id != note.id


# --- Boundaries -------------------------------------------------------------


def test_vault_module_loads_no_database_or_network_modules() -> None:
    forbidden = ["sqlite3", "socket", "ssl", "http.client", "urllib.request", "fastapi", "asyncio"]
    script = f"import sys, page_core.vault\nprint(sorted(set({forbidden!r}) & set(sys.modules)))\n"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]"


def test_core_package_does_not_import_vault() -> None:
    script = "import sys, page_core, page_core.domain\nprint('page_core.vault' in sys.modules)\n"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "False"
