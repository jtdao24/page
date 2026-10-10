# Stage 4: SQLite metadata persistence

`page_core.metadata` builds on the Stage 2 domain models and Stage 3 filesystem
vault. Markdown files remain the sole source of note content. This stage adds
no Markdown parsing, link extraction, chunking, embeddings, vector indexing,
API, or desktop integration.

## Storage and installation

```
<vault>/
  .page/vault.json                  existing Stage 3 manifest
  .page/metadata/notes.sqlite3      generated Stage 4 metadata
  **/*.md                          user-owned source files
```

SQLite is part of Python's standard library. The existing Python 3.12 setup and
unchanged pinned development requirements are sufficient:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r packages/core/requirements-dev.txt -e packages/core
python -m pytest packages/core
```

All persistence tests are collected by the normal pytest command; no optional
packages or model downloads are required.

## Repository

`MetadataRepository(vault)` opens or creates the database for that manifest UUID.
Use it as a context manager or call `close()`.

`NoteMetadata` stores an independent UUID, vault UUID, managed relative path,
timezone-aware creation/update timestamps, SHA-256 digest of raw file bytes,
device/inode, byte size, exact modification time in nanoseconds, and an optional
`missing_since` timestamp. It stores no note content. Values validate against
the existing domain and managed-path rules before SQL writes.

| Method | Behavior |
| --- | --- |
| `insert(record)` | Inserts metadata; rejects duplicate IDs or active paths. |
| `get(note_id)` | Returns a record or `None`, including tombstones. |
| `get_by_path(path)` | Returns the active record at a managed path or `None`. |
| `list_notes(include_missing=False)` | Sorted active metadata, optionally with tombstones. |
| `update(record)` | Updates an existing record; creation time is immutable. |
| `delete(note_id)` | Removes metadata only; never deletes Markdown. Raises for unknown IDs. |
| `transaction()` | Commits a batch atomically; errors roll back. Nested scopes use savepoints. |

Individual writes also use transactions. Failed inner writes can be caught without
losing a surrounding transaction. Independent instances serialize writes through
SQLite with a five-second busy timeout. Instances are not thread-safe. Direct
repository CRUD does not synchronize a live filesystem adapter; use the adapter
for file operations or explicitly reconcile afterward.

## Migrations and integrity

`PRAGMA user_version` and `schema_migrations` record numbered schema versions.
Version 1 creates vault/note tables and migration history. Version 2 adds unique
active-path and digest, file-identity, and modification-time indexes. All upgrade
statements and version/history updates run in one transaction, without
`executescript`'s implicit commit. A migration failure rolls the whole upgrade
back. Future versions, inconsistent histories, unversioned nonempty databases,
and a database belonging to another vault are rejected without overwriting data.

Foreign keys, nonnegative file counts, path/digest formats, canonical UTC
timestamps, and creation/update chronology have SQL constraints. Public writes
also use domain validation. SQLite uses full synchronization. Corrupt metadata
is surfaced as an error, never silently discarded or treated as an empty vault.
Source files remain untouched. Regenerating metadata can recover current file
facts, but historical UUIDs and creation times are not encoded in Markdown.

## Persistent filesystem adapter

```python
from pathlib import Path, PurePosixPath
from page_core.metadata import PersistentVault

with PersistentVault.open(Path("/absolute/path/to/vault")) as vault:
    note = vault.read_note(PurePosixPath("ideas.md"))
    updated = vault.update_note(note, note.content + "\nAnother thought.\n")
    renamed = vault.rename_note(updated, "collected-ideas.md")
    assert renamed.id == note.id
    assert renamed.created_at == note.created_at
```

`PersistentVault.create(root, name)` uses Stage 3 manifest/adoption rules.
Create/open automatically reconcile existing files. The adapter exposes the
existing read/create/update/move/rename/delete method shapes and delegates file
mutations to `FileSystemVault`. Raw UTF-8, line endings, atomic saves, occupied-name
checks, and content conflict checks retain Stage 3 behavior. Attaching persistence
to an existing filesystem instance preserves already-issued UUIDs for unregistered
notes. Explicit creation always receives a new UUID, including at a retired path.

`FileSystemVault` remains in-memory by default. Its identity allocation/restore
hooks perform no I/O and validate mappings before replacing state. The optional
listing error callback lets Stage 4 reject incomplete traversal; default Stage 3
listing behavior is unchanged. Persistent adapter snapshots are checked by their
registered vault/UUID/path and source content; a persistent UUID never bypasses
the existing content conflict checks.

First registration uses filesystem birth time where available, otherwise file
mtime. That creation time survives atomic saves and restarts. Update time follows
mtime, clamped to creation time if an external tool backdates the file. Exact
source mtime is still recorded separately in `mtime_ns`. Moving the entire vault
preserves IDs because records use manifest UUIDs and relative paths, not root paths.

## External changes and recovery

Call `vault.reconcile()` after changes outside Page. It hashes raw bytes without
parsing Markdown, then publishes a complete metadata snapshot transactionally.
Traversal/read errors or detectable concurrent file changes abort reconciliation;
previous notes are not silently marked missing after a failed scan. Invalid UTF-8
files can have metadata, but reading them still raises Stage 3's unreadable-note
error. `ReconcileResult` reports added, modified, renamed, missing, and unchanged
counts. Unchanged records are not rewritten.

- Existing paths retain IDs and creation times after edits, including atomic
  editor replacements. Hashes detect edits even if size/mtime are unchanged.
- A unique unmatched, byte-identical file can be inferred as a rename of one
  newly missing note. Duplicate candidates are not guessed.
- Edited external moves and ambiguous copies receive new IDs by default. Confirm
  a known move with `reconcile(known_renames={note_id: new_relative_path})`. This
  requires a missing source ID and a unique existing destination, and can restore
  a previously recorded tombstone.
- Missing files become tombstones; repeated scans keep the first missing time.
  A file recreated after its predecessor was marked missing gets a new ID.
- Delete/recreate and path swaps entirely between scans can be indistinguishable
  from edits. Existing paths are authoritative; Stage 4 does not guess from inode
  reuse or implement filesystem watching.

Pure metadata deletion leaves source files alone; later reconciliation registers
them again. A UUID can survive if it is still known in memory; after a restart,
deleted identity cannot be reconstructed from the file. Direct CRUD should not run concurrently with an adapter without
reconciling its registry afterward.

Filesystem writes and SQLite commits are not one atomic transaction. If metadata
fails after a successful file mutation, `MetadataSyncError` reports the operation,
note, and current path. Page keeps the successful source write and rolls metadata
back; it never restores an old file over an external edit. Reconcile before
continuing. Explicitly confirm ambiguous failed moves by persisted source UUID
and destination. A failed create has no committed new UUID; reconciliation
registers the file. Take a backup before manually repairing/removing corrupt
metadata; source Markdown cannot reconstruct historical identity.

## Privacy and platform limits

Stage 4 restricts `.page` and its metadata directory to `0700`, and the database
and any existing SQLite journal/WAL/shared-memory files to `0600`. New SQLite
auxiliaries inherit the private database mode. Ownership, regular file type,
and permissions are checked; symlinks and hard-linked cache files are rejected
before chmod. Pre-existing permissive caches are tightened, and cache/database
replacement during transactions is rejected. Note permissions are unchanged.
File checks during active connections use stat only, preserving SQLite's POSIX
locks; permission changes require closing/reopening to tighten them safely.
The vault root must be owned by this user and not writable by others. Path checks
retain Stage 3's assumption that no hostile process with the same user's authority
is swapping directories.

Owner-only enforcement currently supports POSIX and is validated on macOS.
Windows `chmod` does not enforce owner-only ACLs, so this adapter fails closed
there pending implemented and tested Windows ACL support. Existing Stage 2/3
behavior is unchanged; no Windows metadata behavior is claimed as verified.
