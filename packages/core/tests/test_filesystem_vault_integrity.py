import os
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from conftest import snapshot
from page_core.domain import Note
from page_core.vault import (
    FileSystemVault,
    NoteConflictError,
    NoteNotFoundError,
    UnreadableNoteError,
    VaultError,
)

P = PurePosixPath


def leftover_temporaries(root: Path) -> list[str]:
    return [name for name in snapshot(root) if name.endswith(".tmp")]


# --- Byte-exact content -----------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [b"line one\r\nline two\r\n", b"old mac\rline\r", b"\xef\xbb\xbfwith BOM\n", b"no newline"],
)
def test_read_preserves_exact_bytes(fs_vault: FileSystemVault, vault_root: Path, raw: bytes) -> None:
    (vault_root / "note.md").write_bytes(raw)

    assert fs_vault.read_note(P("note.md")).content.encode("utf-8") == raw


def test_update_does_not_rewrite_line_endings(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / "crlf.md").write_bytes(b"one\r\ntwo\r\n")
    note = fs_vault.read_note(P("crlf.md"))

    fs_vault.update_note(note, note.content + "three\r\n")

    assert (vault_root / "crlf.md").read_bytes() == b"one\r\ntwo\r\nthree\r\n"


def test_non_utf8_note_is_reported_without_breaking_the_vault(
    fs_vault: FileSystemVault, vault_root: Path
) -> None:
    (vault_root / "latin1.md").write_bytes("café".encode("latin-1"))
    fs_vault.create_note(P("good.md"), "ok")

    with pytest.raises(UnreadableNoteError):
        fs_vault.read_note(P("latin1.md"))
    assert fs_vault.read_note(P("good.md")).content == "ok"
    assert fs_vault.list_note_paths() == [P("good.md"), P("latin1.md")]


# --- Atomic writes ----------------------------------------------------------


def test_unencodable_content_never_touches_the_file(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("important.md"), "years of notes\n")

    with pytest.raises(UnicodeEncodeError):
        fs_vault.update_note(note, "edit \ud800")
    with pytest.raises(UnicodeEncodeError):
        fs_vault.create_note(P("new.md"), "\ud800")
    assert (vault_root / "important.md").read_text() == "years of notes\n"
    assert not (vault_root / "new.md").exists()


@pytest.mark.parametrize("failing", ["fsync", "replace"])
def test_failed_update_keeps_original_and_cleans_up(
    fs_vault: FileSystemVault, vault_root: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    note = fs_vault.create_note(P("important.md"), "original\n")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, failing, fail)
    with pytest.raises(OSError, match="simulated"):
        fs_vault.update_note(note, "new content\n")
    monkeypatch.undo()

    assert (vault_root / "important.md").read_text() == "original\n"
    assert leftover_temporaries(vault_root) == []
    assert fs_vault.update_note(note, "retry\n").content == "retry\n"


def test_failed_create_leaves_nothing_behind(
    fs_vault: FileSystemVault, vault_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="simulated"):
        fs_vault.create_note(P("new.md"), "content")
    monkeypatch.undo()

    assert not (vault_root / "new.md").exists()
    assert leftover_temporaries(vault_root) == []
    assert fs_vault.create_note(P("new.md"), "content").content == "content"


def test_failed_move_keeps_source_and_frees_destination(
    fs_vault: FileSystemVault, vault_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = fs_vault.create_note(P("a.md"), "a")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="simulated"):
        fs_vault.move_note(note, P("b.md"))
    monkeypatch.undo()

    assert (vault_root / "a.md").read_text() == "a"
    assert not (vault_root / "b.md").exists()
    assert fs_vault.move_note(note, P("b.md")).id == note.id


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_update_preserves_file_permissions(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("a.md"), "a")
    os.chmod(vault_root / "a.md", 0o640)

    fs_vault.update_note(note, "b")

    assert stat.S_IMODE(os.stat(vault_root / "a.md").st_mode) == 0o640


# --- External modifications -------------------------------------------------


def test_update_detects_external_edit(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("shared.md"), "v1\n")
    (vault_root / "shared.md").write_text("v1\nadded in another editor\n")

    with pytest.raises(NoteConflictError):
        fs_vault.update_note(note, "v1\nadded in Page\n")
    assert (vault_root / "shared.md").read_text() == "v1\nadded in another editor\n"


def test_update_after_rereading_succeeds(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("shared.md"), "v1\n")
    (vault_root / "shared.md").write_text("v2\n")

    fresh = fs_vault.read_note(P("shared.md"))

    assert fresh.id == note.id
    assert fs_vault.update_note(fresh, "v3\n").content == "v3\n"


def test_identical_rewrite_is_not_a_conflict(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("a.md"), "same")
    (vault_root / "a.md").write_text("same")

    assert fs_vault.update_note(note, "new").content == "new"


def test_delete_detects_external_edit(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("a.md"), "v1")
    (vault_root / "a.md").write_text("v2")

    with pytest.raises(NoteConflictError):
        fs_vault.delete_note(note)
    assert (vault_root / "a.md").read_text() == "v2"


def test_update_of_externally_deleted_note(fs_vault: FileSystemVault, vault_root: Path) -> None:
    note = fs_vault.create_note(P("a.md"), "v1")
    (vault_root / "a.md").unlink()

    with pytest.raises(NoteNotFoundError):
        fs_vault.update_note(note, "v2")
    assert not (vault_root / "a.md").exists()


def test_stale_snapshot_after_move_is_rejected(fs_vault: FileSystemVault) -> None:
    note = fs_vault.create_note(P("a.md"), "a")
    fs_vault.move_note(note, P("b.md"))

    with pytest.raises(NoteConflictError):
        fs_vault.update_note(note, "lost?")
    with pytest.raises(NoteConflictError):
        fs_vault.delete_note(note)


def test_note_from_another_vault_is_rejected(fs_vault: FileSystemVault, tmp_path: Path) -> None:
    other = FileSystemVault.create(tmp_path / "other", "Other", id_factory=lambda: UUID(int=500))
    foreign = other.create_note(P("a.md"), "a")
    fs_vault.create_note(P("a.md"), "a")

    with pytest.raises(VaultError):
        fs_vault.update_note(foreign, "b")


def test_unread_note_snapshot_is_rejected(fs_vault: FileSystemVault, vault_root: Path) -> None:
    (vault_root / "a.md").write_text("a")
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    made_up = Note(UUID(int=123), fs_vault.vault.id, P("a.md"), "a", moment, moment)

    with pytest.raises(NoteConflictError):
        fs_vault.delete_note(made_up)
    assert (vault_root / "a.md").exists()
