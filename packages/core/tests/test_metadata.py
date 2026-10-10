import hashlib
import os
import sqlite3
import stat
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import uuid4

import pytest

from page_core.metadata import (
    MetadataDecodeError, MetadataError, MetadataNotFoundError, MetadataRepository, NoteMetadata,
)
from page_core.metadata.repository import MIGRATIONS, SCHEMA_VERSION
from page_core.vault import InvalidNotePathError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="private metadata currently requires POSIX permissions")


@pytest.fixture
def repository(fs_vault):
    with MetadataRepository(fs_vault.vault) as result:
        yield result


@pytest.fixture
def record(fs_vault):
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    return NoteMetadata(uuid4(), fs_vault.vault.id, PurePosixPath("a.md"), moment, moment,
                        hashlib.sha256(b"original").hexdigest(), 1, 2, 8, 123456)


def test_standard_install_has_no_later_stage_dependencies():
    result = subprocess.run([sys.executable, "-c", "import sys,page_core.metadata; print(sorted(set(sys.modules) & {'faiss','numpy','torch','sentence_transformers','socket','http.server'}))"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


def test_crud_reopen_and_metadata_only(repository, record, fs_vault):
    source = fs_vault.vault.root_path / "a.md"
    source.write_bytes(b"original\r\n")
    before = source.stat()
    repository.insert(record)
    assert repository.get(record.id) == record
    assert repository.get_by_path(record.relative_path) == record
    assert repository.list_notes() == [record]
    changed = replace(record, relative_path=PurePosixPath("b.md"), updated_at=record.updated_at + timedelta(days=1))
    repository.update(changed)
    with MetadataRepository(fs_vault.vault) as other:
        assert other.get(record.id) == changed
        assert other.get_by_path(record.relative_path) is None
    columns = [row[1] for row in repository._db.execute("PRAGMA table_info(notes)")]
    assert "content" not in columns and "text" not in columns
    assert source.read_bytes() == b"original\r\n"
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    repository.delete(record.id)
    assert repository.get(record.id) is None
    assert source.exists()


def test_active_path_uniqueness_and_tombstones(repository, record):
    repository.insert(record)
    with pytest.raises(sqlite3.IntegrityError):
        repository.insert(replace(record, id=uuid4()))
    missing = replace(record, missing_since=datetime.now(UTC))
    repository.update(missing)
    replacement = replace(record, id=uuid4())
    repository.insert(replacement)
    assert repository.get_by_path(record.relative_path) == replacement
    assert repository.list_notes() == [replacement]
    assert len(repository.list_notes(include_missing=True)) == 2


def test_transaction_and_nested_savepoint_rollback(repository, record):
    with pytest.raises(RuntimeError):
        with repository.transaction():
            repository.insert(record)
            raise RuntimeError("abort")
    assert repository.list_notes() == []
    with repository.transaction():
        repository.insert(record)
        with pytest.raises(sqlite3.IntegrityError):
            repository.insert(replace(record, id=uuid4()))
        repository.update(replace(record, relative_path=PurePosixPath("renamed.md")))
    assert repository.get(record.id).relative_path == PurePosixPath("renamed.md")
    with pytest.raises(ValueError, match="immutable"):
        repository.update(replace(record, created_at=record.created_at - timedelta(days=1)))


def test_write_lock_and_uncommitted_data_are_preserved_across_security_checks(repository, record):
    script = """import sqlite3,sys
db=sqlite3.connect(sys.argv[1],timeout=0.05)
print(db.execute('SELECT COUNT(*) FROM notes').fetchone()[0])
try:
    db.execute('BEGIN IMMEDIATE')
except sqlite3.OperationalError:
    print('locked')
else:
    print('unexpected write access')
"""
    with repository.transaction():
        repository.insert(record)
        result = subprocess.run([sys.executable, "-c", script, str(repository.database)], capture_output=True, text=True, check=True)
        assert result.stdout.splitlines() == ["0", "locked"]
    assert repository.get(record.id) == record


def test_opening_another_repository_preserves_existing_write_lock(repository, record, monkeypatch):
    connect = sqlite3.connect
    def short_timeout(*args, **kwargs):
        kwargs["timeout"] = 0.05
        return connect(*args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", short_timeout)
    with repository.transaction():
        repository.insert(record)
        repository.database.chmod(0o644)
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            MetadataRepository(repository.vault)
    assert repository.get(record.id) == record


def test_foreign_vault_and_unknown_ids(repository, record):
    with pytest.raises(ValueError, match="another vault"):
        repository.insert(replace(record, vault_id=uuid4()))
    with pytest.raises(MetadataNotFoundError):
        repository.update(record)
    with pytest.raises(MetadataNotFoundError):
        repository.delete(record.id)
    with pytest.raises(TypeError):
        repository.get(str(record.id))


@pytest.mark.parametrize("changes", [
    {"digest": "invalid"}, {"size_bytes": -1}, {"device": True},
    {"mtime_ns": 1.5}, {"updated_at": datetime(2025, 1, 1, tzinfo=UTC)},
    {"created_at": datetime(2026, 1, 1)}, {"missing_since": datetime(2026, 1, 1)},
    {"relative_path": PurePosixPath("../outside.md")},
    {"relative_path": PurePosixPath(".hidden/a.md")},
])
def test_record_validation(record, changes):
    with pytest.raises((TypeError, ValueError)):
        replace(record, **changes)


@pytest.mark.parametrize("field,value", [("id", None), ("missing_since", "invalid"), ("size_bytes", -1), ("digest", "z" * 64),
    ("relative_path", "../outside.md"), ("relative_path", "/absolute.md"),
    ("relative_path", "hidden/.secret.md"), ("relative_path", "x.txt"),
    ("updated_at", "2025-01-01T00:00:00.000000+00:00"), ("vault_id", str(uuid4()))])
def test_database_constraints(repository, record, field, value):
    repository.insert(record)
    with pytest.raises(sqlite3.IntegrityError):
        with repository.transaction():
            repository._db.execute(f"UPDATE notes SET {field}=? WHERE id=?", (value, str(record.id)))
    assert repository.get(record.id) == record


@pytest.mark.parametrize("field,value", [("id", "x" * 36), ("relative_path", "CON.md"),
                                         ("relative_path", "dir./a.md")])
def test_corrupt_stored_values_raise_a_typed_decode_error(repository, record, field, value):
    repository.insert(record)
    with repository.transaction():
        repository._db.execute(f"UPDATE notes SET {field}=? WHERE id=?", (value, str(record.id)))
    with pytest.raises(MetadataDecodeError) as error:
        repository.list_notes()
    assert isinstance(error.value, ValueError) and isinstance(error.value, MetadataError)


def test_fresh_schema_and_migration_history(repository):
    assert repository._db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert [row[0] for row in repository._db.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
    indexes = {row[1] for row in repository._db.execute("PRAGMA index_list(notes)")}
    assert {"notes_active_path", "notes_digest", "notes_file_identity", "notes_updated"} <= indexes


def test_upgrade_version_one_preserves_metadata(fs_vault, record):
    with MetadataRepository(fs_vault.vault) as repository:
        database = repository.database
    with sqlite3.connect(database) as db:
        for index in ("notes_active_path", "notes_digest", "notes_file_identity", "notes_updated"):
            db.execute(f"DROP INDEX {index}")
        db.execute("DELETE FROM schema_migrations WHERE version=2")
        db.execute("PRAGMA user_version=1")
        db.execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)", MetadataRepository._values(record))
    with MetadataRepository(fs_vault.vault) as migrated:
        assert migrated.get(record.id) == record
        assert migrated._db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_migration_failure_is_atomic(fs_vault, monkeypatch):
    from page_core.metadata import repository as module
    monkeypatch.setattr(module, "MIGRATIONS", (MIGRATIONS[0], ("CREATE TABLE temporary_migration (id INTEGER)", "INVALID SQL")))
    with pytest.raises(sqlite3.OperationalError):
        MetadataRepository(fs_vault.vault)
    database = fs_vault.vault.root_path / ".page/metadata/notes.sqlite3"
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


@pytest.mark.parametrize("damage", ["future", "history", "vault", "unversioned"])
def test_incompatible_database_rejected_without_overwrite(fs_vault, record, damage):
    with MetadataRepository(fs_vault.vault) as repository:
        repository.insert(record)
        database = repository.database
    with sqlite3.connect(database) as db:
        if damage == "future":
            db.execute("PRAGMA user_version=100")
        elif damage == "history":
            db.execute("DELETE FROM schema_migrations WHERE version=1")
        elif damage == "vault":
            db.execute("UPDATE vaults SET id=?", (str(uuid4()),))
        else:
            db.execute("PRAGMA user_version=0")
    before = database.read_bytes()
    with pytest.raises(MetadataError):
        MetadataRepository(fs_vault.vault)
    assert database.read_bytes() == before


def test_private_storage_under_permissive_umask_and_reopening(repository, record, fs_vault):
    repository.close()
    directory = repository.directory
    database = repository.database
    directory.chmod(0o755)
    database.chmod(0o644)
    previous = os.umask(0)
    try:
        with MetadataRepository(fs_vault.vault) as secured:
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(directory.parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(database.stat().st_mode) == 0o600
            with secured.transaction():
                secured.insert(record)
                journal = database.with_name(database.name + "-journal")
                assert stat.S_IMODE(journal.stat().st_mode) == 0o600
            secured._db.execute("PRAGMA journal_mode=WAL")
            secured.update(replace(record, relative_path=PurePosixPath("b.md")))
            for suffix in ("-wal", "-shm"):
                assert stat.S_IMODE(database.with_name(database.name + suffix).stat().st_mode) == 0o600
    finally:
        os.umask(previous)


@pytest.mark.parametrize("entry", ["directory", "database", "journal", "wal", "shm"])
def test_symlink_cache_entries_rejected(fs_vault, tmp_path, symlinks, entry):
    with MetadataRepository(fs_vault.vault) as repository:
        directory, database = repository.directory, repository.database
    outside = tmp_path / "outside"
    if entry == "directory":
        outside.mkdir()
        directory.rename(directory.with_name("saved"))
        directory.symlink_to(outside, target_is_directory=True)
    else:
        outside.write_bytes(b"private outside data")
        target = database if entry == "database" else database.with_name(database.name + {"journal": "-journal", "wal": "-wal", "shm": "-shm"}[entry])
        target.unlink(missing_ok=True)
        target.symlink_to(outside)
    before = stat.S_IMODE(outside.stat().st_mode)
    with pytest.raises((OSError, MetadataError, InvalidNotePathError)):
        MetadataRepository(fs_vault.vault)
    assert stat.S_IMODE(outside.stat().st_mode) == before


def test_hardlinked_database_rejected_without_chmod(fs_vault, tmp_path, hardlinks):
    with MetadataRepository(fs_vault.vault) as repository:
        database = repository.database
    linked = tmp_path / "linked.sqlite3"
    os.link(database, linked)
    linked.chmod(0o644)
    with pytest.raises(MetadataError, match="unsafe"):
        MetadataRepository(fs_vault.vault)
    assert stat.S_IMODE(linked.stat().st_mode) == 0o644


def test_database_replacement_rejected(repository):
    repository.database.rename(repository.database.with_name("saved.sqlite3"))
    repository.database.touch(mode=0o600)
    with pytest.raises(MetadataError, match="replaced"):
        with repository.transaction():
            pass


def test_other_user_writable_vault_rejected(fs_vault):
    fs_vault.vault.root_path.chmod(0o777)
    with pytest.raises(MetadataError, match="not writable by others"):
        MetadataRepository(fs_vault.vault)


def test_private_permissions_without_nofollow_chmod_support(fs_vault, monkeypatch):
    with MetadataRepository(fs_vault.vault) as repository:
        database = repository.database
    database.chmod(0o644)
    monkeypatch.setattr(os, "supports_follow_symlinks", os.supports_follow_symlinks - {os.chmod})
    with MetadataRepository(fs_vault.vault):
        assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_private_acl_support_fails_closed(fs_vault, monkeypatch):
    from page_core.metadata import repository as module
    monkeypatch.setattr(module.os, "name", "nt")
    with pytest.raises(MetadataError, match="POSIX"):
        MetadataRepository(fs_vault.vault)
