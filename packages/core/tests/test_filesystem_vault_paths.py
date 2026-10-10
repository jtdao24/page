import os
from pathlib import Path, PurePosixPath

import pytest

from conftest import snapshot
from page_core.vault import FileSystemVault, InvalidNotePathError, NoteNotFoundError

P = PurePosixPath


@pytest.mark.parametrize("path", ["/etc/passwd.md", "../outside.md", "a/../../outside.md"])
def test_rejects_absolute_and_traversal_paths(fs_vault: FileSystemVault, path: str) -> None:
    with pytest.raises(ValueError):
        fs_vault.read_note(P(path))
    with pytest.raises(ValueError):
        fs_vault.create_note(P(path), "x")


@pytest.mark.parametrize(
    "path",
    [
        "..\\outside.md",
        "C:/outside.md",
        ".hidden.md",
        ".page/vault.md",
        ".obsidian/workspace.md",
        "trailing./a.md",
        "trailing /a.md",
        "what?.md",
        "pipe|.md",
        "tab\t.md",
        "CON.md",
        "lpt1.md",
        "nul.backup.md",
        "notes.MD",
        "notes.txt",
    ],
)
def test_rejects_unmanaged_or_non_portable_paths(
    fs_vault: FileSystemVault, vault_root: Path, path: str
) -> None:
    before = snapshot(vault_root)

    with pytest.raises(ValueError):
        fs_vault.create_note(P(path), "x")
    with pytest.raises(ValueError):
        fs_vault.read_note(P(path))
    assert snapshot(vault_root) == before


@pytest.mark.parametrize("path", ["notes.md", Path("notes.md"), None])
def test_rejects_non_pure_posix_paths(fs_vault: FileSystemVault, path: object) -> None:
    with pytest.raises(TypeError):
        fs_vault.create_note(path, "x")  # type: ignore[arg-type]


def test_hidden_files_cannot_be_read_or_deleted(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / ".obsidian").mkdir()
    (vault_root / ".obsidian" / "keep.md").write_text("config")

    with pytest.raises(InvalidNotePathError):
        fs_vault.read_note(P(".obsidian/keep.md"))
    assert (vault_root / ".obsidian" / "keep.md").read_text() == "config"


@pytest.mark.usefixtures("symlinks")
def test_symlinked_note_pointing_outside_is_skipped_and_rejected(
    fs_vault: FileSystemVault, vault_root: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("outside")
    os.symlink(secret, vault_root / "link.md")

    assert fs_vault.list_note_paths() == []
    with pytest.raises(InvalidNotePathError, match="symlink"):
        fs_vault.read_note(P("link.md"))
    assert secret.read_text() == "outside"


@pytest.mark.usefixtures("symlinks")
def test_symlinked_note_pointing_inside_is_not_followed(
    fs_vault: FileSystemVault, vault_root: Path
) -> None:
    fs_vault.create_note(P("real.md"), "real")
    os.symlink(vault_root / "real.md", vault_root / "alias.md")

    assert fs_vault.list_note_paths() == [P("real.md")]
    with pytest.raises(InvalidNotePathError, match="symlink"):
        fs_vault.read_note(P("alias.md"))


@pytest.mark.usefixtures("symlinks")
def test_symlinked_directory_is_skipped_and_rejected(
    fs_vault: FileSystemVault, vault_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.md").write_text("outside")
    os.symlink(outside, vault_root / "ext", target_is_directory=True)

    assert fs_vault.list_note_paths() == []
    with pytest.raises(InvalidNotePathError, match="symlink"):
        fs_vault.read_note(P("ext/o.md"))
    with pytest.raises(InvalidNotePathError, match="symlink"):
        fs_vault.create_note(P("ext/new.md"), "x")
    assert sorted(p.name for p in outside.iterdir()) == ["o.md"]


@pytest.mark.usefixtures("symlinks")
def test_move_into_symlinked_directory_is_rejected(
    fs_vault: FileSystemVault, vault_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, vault_root / "ext", target_is_directory=True)
    note = fs_vault.create_note(P("a.md"), "a")

    with pytest.raises(InvalidNotePathError, match="symlink"):
        fs_vault.move_note(note, P("ext/a.md"))
    assert list(outside.iterdir()) == []
    assert (vault_root / "a.md").read_text() == "a"


@pytest.mark.usefixtures("symlinks")
def test_symlinked_vault_root_is_resolved(tmp_path: Path) -> None:
    real = tmp_path / "real"
    FileSystemVault.create(real, "Research")
    os.symlink(real, tmp_path / "alias", target_is_directory=True)

    opened = FileSystemVault.open(tmp_path / "alias")

    assert opened.vault.root_path == real.resolve()


def test_file_in_place_of_directory_is_rejected(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / "projects").write_text("not a directory")

    with pytest.raises(InvalidNotePathError):
        fs_vault.create_note(P("projects/a.md"), "x")
    with pytest.raises(InvalidNotePathError):
        fs_vault.read_note(P("projects/a.md"))


def test_directory_case_mismatch_is_rejected(
    fs_vault: FileSystemVault, vault_root: Path, case_insensitive: bool
) -> None:
    if not case_insensitive:
        pytest.skip("filesystem is case-sensitive")
    fs_vault.create_note(P("projects/a.md"), "x")

    with pytest.raises(InvalidNotePathError):
        fs_vault.create_note(P("Projects/b.md"), "y")
    with pytest.raises(InvalidNotePathError):
        fs_vault.read_note(P("Projects/a.md"))
    assert sorted(os.listdir(vault_root / "projects")) == ["a.md"]


def test_missing_parent_directory_reads_as_not_found(fs_vault: FileSystemVault) -> None:
    with pytest.raises(NoteNotFoundError):
        fs_vault.read_note(P("nowhere/a.md"))
