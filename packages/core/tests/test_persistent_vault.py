import os
import sqlite3
from dataclasses import replace
from pathlib import PurePosixPath
from uuid import uuid4

import pytest

from page_core.metadata import InvalidRenameError, MetadataRepository, MetadataSyncError, PersistentVault
from page_core.vault import FileSystemVault, NoteConflictError, NoteExistsError, UnreadableNoteError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="private metadata currently requires POSIX permissions")


@pytest.fixture
def persistent(fs_vault):
    metadata = MetadataRepository(fs_vault.vault)
    with PersistentVault(fs_vault, metadata) as result:
        result.reconcile()
        yield result


def test_existing_notes_adopted_without_changing_bytes(fs_vault):
    root = fs_vault.vault.root_path
    (root / "existing.md").write_bytes(b"\xef\xbb\xbf# Title\r\nbody without final newline")
    before = (root / "existing.md").read_bytes()
    with PersistentVault.open(root) as vault:
        first = vault.read_note(PurePosixPath("existing.md"))
    with PersistentVault.open(root) as reopened:
        second = reopened.read_note(PurePosixPath("existing.md"))
        assert second.id == first.id
        assert second.created_at == first.created_at
        assert second.content.encode("utf8") == before
    assert (root / "existing.md").read_bytes() == before


def test_attaching_metadata_preserves_an_already_issued_stage_three_id(fs_vault):
    original = fs_vault.create_note(PurePosixPath("a.md"), "already read")
    with MetadataRepository(fs_vault.vault) as metadata:
        with PersistentVault(fs_vault, metadata) as vault:
            vault.reconcile()
            assert vault.read_note(original.relative_path).id == original.id
            assert vault.update_note(original, "updated").id == original.id


def test_reading_one_note_keeps_other_already_issued_ids(fs_vault):
    first = fs_vault.create_note(PurePosixPath("a.md"), "first")
    second = fs_vault.create_note(PurePosixPath("b.md"), "second")
    with MetadataRepository(fs_vault.vault) as metadata:
        with PersistentVault(fs_vault, metadata) as vault:
            assert vault.read_note(first.relative_path).id == first.id
            assert vault.read_note(second.relative_path).id == second.id
            assert vault.update_note(second, "updated").id == second.id


def test_create_update_move_delete_and_reopen(persistent):
    root = persistent.vault.root_path
    first = persistent.create_note(PurePosixPath("folder/a.md"), "original\r\n")
    updated = persistent.update_note(first, "changed\r\n")
    moved = persistent.move_note(updated, PurePosixPath("other/b.md"))
    renamed = persistent.rename_note(moved, "c.md")
    assert renamed.id == updated.id == first.id
    assert renamed.created_at == first.created_at
    with PersistentVault.open(root) as reopened:
        read = reopened.read_note(renamed.relative_path)
        assert read.id == first.id
        assert read.created_at == first.created_at
        assert read.content == "changed\r\n"
    persistent.delete_note(renamed)
    assert persistent.list_note_paths() == []
    assert persistent.metadata.list_notes() == []
    assert persistent.metadata.get(first.id).missing_since is not None
    fresh = persistent.create_note(first.relative_path, "new")
    assert fresh.id != first.id


def test_vault_folder_move_preserves_ids_and_creation(persistent, tmp_path):
    first = persistent.create_note(PurePosixPath("a.md"), "hello")
    root = persistent.vault.root_path
    persistent.close()
    moved_root = tmp_path / "moved-vault"
    root.rename(moved_root)
    with PersistentVault.open(moved_root) as reopened:
        note = reopened.read_note(first.relative_path)
        assert note.id == first.id and note.created_at == first.created_at
        assert note.vault_id == first.vault_id


def test_external_atomic_edit_preserves_creation_and_identity(persistent):
    first = persistent.create_note(PurePosixPath("a.md"), "first")
    root = persistent.vault.root_path
    temporary = root / "replacement"
    temporary.write_text("edited outside Page")
    os.replace(temporary, root / "a.md")
    result = persistent.reconcile()
    assert result.modified == 1
    second = persistent.read_note(first.relative_path)
    assert second.id == first.id and second.created_at == first.created_at
    assert second.content == "edited outside Page"
    with pytest.raises(NoteConflictError):
        persistent.update_note(first, "stale overwrite")


def test_changed_bytes_with_same_size_and_mtime_reconciled(persistent):
    note = persistent.create_note(PurePosixPath("a.md"), "before")
    path = persistent.vault.root_path / "a.md"
    info = path.stat()
    path.write_bytes(b"after!")
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    before = persistent.metadata.get(note.id)
    assert persistent.reconcile().modified == 1
    after = persistent.metadata.get(note.id)
    assert before.digest != after.digest
    assert before.mtime_ns == after.mtime_ns
    assert before.id == after.id and before.created_at == after.created_at


def test_backdated_file_mtime_keeps_domain_timestamps_valid(persistent):
    first = persistent.create_note(PurePosixPath("a.md"), "hello")
    path = persistent.vault.root_path / "a.md"
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    note = persistent.read_note(first.relative_path)
    assert note.id == first.id and note.created_at == first.created_at
    assert note.updated_at >= note.created_at
    assert persistent.metadata.get(note.id).mtime_ns == 1_000_000_000


def test_unchanged_reconciliation_does_not_write_metadata(persistent):
    persistent.create_note(PurePosixPath("a.md"), "same")
    changes = persistent.metadata._db.total_changes
    assert persistent.reconcile().unchanged == 1
    assert persistent.metadata._db.total_changes == changes


def test_external_unique_rename_and_original_path_recreation(persistent):
    original = persistent.create_note(PurePosixPath("a.md"), "original")
    root = persistent.vault.root_path
    (root / "a.md").rename(root / "b.md")
    assert persistent.reconcile().renamed == 1
    moved = persistent.read_note(PurePosixPath("b.md"))
    assert moved.id == original.id and moved.created_at == original.created_at
    (root / "a.md").write_text("a new note")
    assert persistent.reconcile().added == 1
    assert persistent.read_note(PurePosixPath("a.md")).id != original.id


def test_missing_note_tombstone_is_not_implicitly_resurrected(persistent):
    original = persistent.create_note(PurePosixPath("a.md"), "same")
    path = persistent.vault.root_path / "a.md"
    path.unlink()
    assert persistent.reconcile().missing == 1
    missing_since = persistent.metadata.get(original.id).missing_since
    assert persistent.reconcile().missing == 0
    assert persistent.metadata.get(original.id).missing_since == missing_since
    path.write_text("same")
    assert persistent.reconcile().added == 1
    assert persistent.read_note(original.relative_path).id != original.id


def test_ambiguous_external_moves_get_new_independent_ids(persistent):
    first = persistent.create_note(PurePosixPath("a.md"), "same")
    second = persistent.create_note(PurePosixPath("b.md"), "same")
    root = persistent.vault.root_path
    (root / "a.md").rename(root / "x.md")
    (root / "b.md").rename(root / "y.md")
    result = persistent.reconcile()
    assert result.added == result.missing == 2 and result.renamed == 0
    ids = {record.id for record in persistent.metadata.list_notes()}
    assert len(ids) == 2 and ids.isdisjoint({first.id, second.id})


def test_edited_external_move_can_be_explicitly_confirmed(persistent):
    first = persistent.create_note(PurePosixPath("a.md"), "original")
    root = persistent.vault.root_path
    (root / "a.md").rename(root / "b.md")
    (root / "b.md").write_text("edited during move")
    result = persistent.reconcile(known_renames={first.id: PurePosixPath("b.md")})
    assert result.renamed == 1 and result.modified == 1
    moved = persistent.read_note(PurePosixPath("b.md"))
    assert moved.id == first.id and moved.created_at == first.created_at


def test_confirmed_move_can_restore_a_previously_missing_identity(persistent):
    original = persistent.create_note(PurePosixPath("a.md"), "original")
    root = persistent.vault.root_path
    (root / "a.md").unlink()
    persistent.reconcile()
    (root / "b.md").write_text("edited and restored")
    persistent.reconcile(known_renames={original.id: PurePosixPath("b.md")})
    assert persistent.read_note(PurePosixPath("b.md")).id == original.id


@pytest.mark.parametrize("bad_mapping", ["unknown", "existing-source", "missing-target", "unsafe-target"])
def test_invalid_rename_confirmations_roll_back(persistent, bad_mapping):
    first = persistent.create_note(PurePosixPath("a.md"), "a")
    second = persistent.create_note(PurePosixPath("b.md"), "b")
    mappings = {"unknown": {uuid4(): second.relative_path}, "existing-source": {first.id: second.relative_path},
                "missing-target": {first.id: PurePosixPath("missing.md")}, "unsafe-target": {first.id: PurePosixPath("../outside.md")}}
    before = persistent.metadata.list_notes(include_missing=True)
    with pytest.raises(ValueError):
        persistent.reconcile(known_renames=mappings[bad_mapping])
    assert persistent.metadata.list_notes(include_missing=True) == before


@pytest.mark.parametrize("bad_mapping", ["unknown", "existing-source", "missing-target"])
def test_rejected_confirmations_raise_a_typed_value_error(persistent, bad_mapping):
    first = persistent.create_note(PurePosixPath("a.md"), "a")
    second = persistent.create_note(PurePosixPath("b.md"), "b")
    mappings = {"unknown": {uuid4(): second.relative_path}, "existing-source": {first.id: second.relative_path},
                "missing-target": {first.id: PurePosixPath("missing.md")}}
    with pytest.raises(InvalidRenameError) as error:
        persistent.reconcile(known_renames=mappings[bad_mapping])
    assert isinstance(error.value, ValueError)


def test_failed_scan_never_marks_unread_files_missing(persistent, monkeypatch):
    first = persistent.create_note(PurePosixPath("a.md"), "hello")
    def unreadable(*args, **kwargs):
        kwargs["onerror"](PermissionError("cannot enumerate folder"))
        return iter(())
    monkeypatch.setattr(os, "walk", unreadable)
    with pytest.raises(PermissionError):
        persistent.reconcile()
    assert persistent.metadata.get(first.id).missing_since is None


def test_metadata_can_reconcile_invalid_utf8_without_parsing_it(persistent):
    path = persistent.vault.root_path / "invalid.md"
    path.write_bytes(b"\xff")
    assert persistent.reconcile().added == 1
    with pytest.raises(UnreadableNoteError):
        persistent.read_note(PurePosixPath("invalid.md"))
    assert path.read_bytes() == b"\xff"


def test_reconciliation_failure_rolls_back_all_metadata(persistent, monkeypatch):
    first = persistent.create_note(PurePosixPath("a.md"), "first")
    root = persistent.vault.root_path
    (root / "a.md").unlink()
    (root / "b.md").write_text("new")
    def fail(record):
        raise sqlite3.OperationalError("database write failed")
    monkeypatch.setattr(persistent.metadata, "insert", fail)
    with pytest.raises(sqlite3.OperationalError):
        persistent.reconcile()
    assert persistent.metadata.get(first.id).missing_since is None
    assert persistent.metadata.get_by_path(PurePosixPath("b.md")) is None
    assert (root / "b.md").read_text() == "new"


def test_file_save_survives_metadata_failure_and_reconciliation_repairs_it(persistent, monkeypatch):
    first = persistent.create_note(PurePosixPath("a.md"), "before")
    original_update = persistent.metadata.update
    def fail(record):
        raise sqlite3.OperationalError("database write failed")
    monkeypatch.setattr(persistent.metadata, "update", fail)
    with pytest.raises(MetadataSyncError) as error:
        persistent.update_note(first, "after")
    assert error.value.operation == "update" and error.value.note_id == first.id
    assert (persistent.vault.root_path / "a.md").read_text() == "after"
    monkeypatch.setattr(persistent.metadata, "update", original_update)
    assert persistent.reconcile().modified == 1
    read = persistent.read_note(first.relative_path)
    assert read.content == "after" and read.id == first.id


def test_filesystem_failure_does_not_modify_metadata(persistent):
    first = persistent.create_note(PurePosixPath("a.md"), "a")
    second = persistent.create_note(PurePosixPath("b.md"), "b")
    before = persistent.metadata.list_notes(include_missing=True)
    with pytest.raises(NoteExistsError):
        persistent.move_note(first, second.relative_path)
    assert persistent.metadata.list_notes(include_missing=True) == before


def test_hardlinked_notes_have_separate_ids(persistent, hardlinks):
    first = persistent.create_note(PurePosixPath("a.md"), "same")
    root = persistent.vault.root_path
    os.link(root / "a.md", root / "b.md")
    persistent.reconcile()
    assert persistent.read_note(PurePosixPath("b.md")).id != first.id


def test_unmanaged_symlinks_are_not_adopted(persistent, tmp_path, symlinks):
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    (persistent.vault.root_path / "linked.md").symlink_to(outside)
    persistent.reconcile()
    assert persistent.metadata.list_notes() == []
    assert outside.read_text() == "outside"


def test_restore_registry_validates_before_replacing_state(fs_vault):
    first = fs_vault.create_note(PurePosixPath("a.md"), "a")
    with pytest.raises(ValueError):
        fs_vault.restore_note_identities({first.relative_path: first.id, PurePosixPath("b.md"): first.id})
    assert fs_vault.read_note(first.relative_path).id == first.id
    with pytest.raises(TypeError):
        fs_vault.restore_note_identities({first.relative_path: str(first.id)})
    assert fs_vault.read_note(first.relative_path).id == first.id


def test_duplicate_allocated_ids_abort_without_losing_notes(persistent, monkeypatch):
    root = persistent.vault.root_path
    (root / "a.md").write_text("a")
    (root / "b.md").write_text("b")
    identifier = uuid4()
    monkeypatch.setattr(persistent.files, "_new_id", lambda: identifier)
    from page_core.metadata import MetadataError
    with pytest.raises(MetadataError, match="duplicate"):
        persistent.reconcile()
    assert persistent.metadata.list_notes(include_missing=True) == []
    assert (root / "a.md").read_text() == "a"
    assert (root / "b.md").read_text() == "b"
