# Filesystem Vault

Specification for `page_core.vault` (Stage 3). The source of truth is
`packages/core/src/page_core/vault.py`. It builds on the domain models in
[domain-models.md](domain-models.md) and uses only the Python standard library.

## Layout

```
<vault root>/
├── .page/
│   └── vault.json      {"format": 1, "id": "<uuid>", "name": "<name>"}
└── **/*.md             notes, owned by the user
```

The manifest is the only file Page writes besides notes. It gives the vault a UUID
that does not depend on the folder's location, so moving or renaming the folder keeps
its identity.

## Operations

| Method | Behavior |
|---|---|
| `FileSystemVault.create(root, name)` | Creates `root` if needed and writes the manifest. Existing notes in `root` are adopted untouched. Raises `VaultExistsError` if a manifest exists. |
| `FileSystemVault.open(root)` | Reads the manifest. Never creates or modifies anything. Raises `VaultNotFoundError` for a missing folder or manifest, and `VaultError` for an invalid manifest. |
| `list_note_paths()` | Sorted paths of all managed notes. Does not read contents. |
| `read_note(path)` | Returns a domain `Note`. |
| `create_note(path, content="")` | Creates the note and any missing parent folders. Never overwrites: `NoteExistsError`. |
| `update_note(note, content)` | Atomically replaces the content (see below). |
| `move_note(note, new_path)` | Moves or renames the file, keeping the note's ID. Never overwrites: `NoteExistsError`. |
| `rename_note(note, new_name)` | `move_note` within the same folder. |
| `delete_note(note)` | Deletes the file. |

`update_note`, `move_note`, `rename_note` and `delete_note` take the `Note` the caller
last read, not a path.

## Paths

Note paths follow the domain rules (`PurePosixPath`, relative, lowercase `.md`, no
`..`, `\`, `:` or NUL). The vault additionally refuses, with `InvalidNotePathError`:

- **Hidden entries:** any component starting with `.`. This keeps `.page`, `.git`,
  `.obsidian` and temporary files out of reach.
- **Names that break on Windows:** components ending in a space or dot; components
  containing `< > " | ? *` or control characters; reserved names such as `CON`, `NUL`,
  `COM1` or `LPT1`, with or without an extension.
- **Symlinks:** any symlinked component is refused, whether it points inside or outside
  the vault. Only the vault root itself may be a symlink; it is resolved when the vault
  is created or opened.
- **Case mismatches:** a directory component whose existing name differs only in case.
  Paths must match the on-disk name exactly, so behavior is the same on case-sensitive
  and case-insensitive filesystems. On a case-insensitive filesystem a case variant of
  an existing note cannot be created, and a case-only rename is supported.

`list_note_paths` skips anything these rules refuse, and the vault never modifies such
files.

## Note identity

- Note IDs are random UUIDs, never derived from paths.
- IDs live **only in memory**, in the `FileSystemVault` instance. A note keeps its ID
  for the life of the instance, including across `move_note` and `rename_note`.
- Reopening the vault assigns new IDs. Changes made outside Page (renames or moves) also
  produce new IDs. Persisting note identity is deferred to Stage 4.
- A `Note` snapshot is accepted only by the instance that produced it and only while it
  is still at its recorded path. Otherwise `NoteConflictError` is raised.

## Content and timestamps

- Files are read and written as raw bytes and decoded or encoded as strict UTF-8.
  Line endings, byte order marks and a missing final newline are preserved exactly, so
  the domain's UTF-8 byte offsets match the file.
- A file that is not valid UTF-8 raises `UnreadableNoteError` when read. It is still
  listed and does not affect other notes.
- New content is encoded before any file is opened, so text that cannot be encoded
  (such as a lone surrogate) raises an error without touching the disk.
- `updated_at` is the file's modification time in UTC. `created_at` is the file's birth
  time where the platform reports one (macOS, Windows), and otherwise equals
  `updated_at`. Because each save replaces the file, birth time resets on every update;
  creation times that survive edits are deferred to Stage 4.

## Atomic writes

Every content write:

1. Creates a hidden temporary file in the same directory, exclusively.
2. Writes the bytes, flushes and calls `fsync`.
3. Copies the original file's permission bits when updating.
4. Swaps the temporary file into place with `os.replace`.
5. Calls `fsync` on the directory, on POSIX only.

If any step before the swap fails, the original file is untouched and the temporary
file is removed. Creating a note first reserves the name with an exclusive create. A
failed create removes the reservation; a crash between the reservation and the swap can
leave an empty note.

**Durability limits:**
- On macOS, `fsync` does not force the drive's write cache to disk, so a power loss can
  still lose the most recent save.
- Windows does not support directory `fsync`, so the rename itself may not be durable.
- On Windows, `os.replace` fails if another program holds the note open without
  sharing. The error is raised and the original file is kept.

## External modifications

`update_note` and `delete_note` re-read the file and compare its bytes with the
snapshot's `content`. If they differ, for example after an edit in another application,
`NoteConflictError` is raised and nothing is written. Rewriting a file with identical
bytes is not a conflict. To continue, read the note again and reapply the change.

The comparison and the write are separate steps, so an edit landing in between can
still be overwritten. The window is short but not zero.

## Rename and move

- The destination name is reserved with an exclusive create before the file is moved
  over the reservation. An existing file is never replaced, even if it appears after the
  check.
- On failure the source is kept and the reservation removed.
- Missing destination folders are created. Emptied source folders are left in place.
- Content and modification time are preserved.

## Deletion

Deletion is permanent: there is no trash or undo, and recovery depends on the user's
own backups or operating system tools. Deletion applies only to the snapshot's file,
only if its content is unchanged, and never removes folders.

## Concurrency and limits

- Paths are checked component by component immediately before each operation, without
  following symlinks, and reads and new files are opened with `O_NOFOLLOW` where the
  platform supports it. This does **not** protect against another process swapping a
  checked directory for a symlink between the check and the operation. The vault
  assumes that no hostile process is modifying the vault folder at the same time.
- `FileSystemVault` is not thread-safe.
- Only macOS has been tested. Windows behavior described here follows the platform
  documentation but has not been verified.

## Deferred

| Concern | Stage |
|---|---|
| Persistent note IDs and creation times; metadata index | 4 |
| Exposing the vault through an API | 5 |
| Desktop integration | 6 |
| Markdown parsing, links, backlinks, graph | 7 |
| File watching | Not yet scheduled |
