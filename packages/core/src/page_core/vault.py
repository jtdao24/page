"""Filesystem-backed Markdown vault.

Markdown files on disk are the source of truth for note content. This module
reads and writes them safely; it does not parse Markdown, index notes, or
persist anything besides a small vault manifest. See docs/filesystem-vault.md
for the full contract and its limitations.
"""

import json
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from page_core.domain import Note, Vault, validate_note_path

METADATA_DIR = ".page"
MANIFEST_NAME = "vault.json"
_MANIFEST_FORMAT = 1

# Names and characters that are invalid or special on Windows. Rejecting them
# everywhere keeps vaults portable between macOS and Windows.
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
_NON_PORTABLE_CHARACTERS = frozenset('<>"|?*')

_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class VaultError(Exception):
    """Base class for filesystem vault errors."""


class VaultNotFoundError(VaultError):
    """No Page vault exists at the given location."""


class VaultExistsError(VaultError):
    """A Page vault already exists at the given location."""


class InvalidNotePathError(VaultError, ValueError):
    """A note path is valid in the domain but not managed by the vault."""


class NoteNotFoundError(VaultError):
    """The note file does not exist."""


class NoteExistsError(VaultError):
    """A file already exists at the destination path."""


class NoteConflictError(VaultError):
    """The note on disk no longer matches the caller's snapshot."""


class UnreadableNoteError(VaultError):
    """The note file is not valid UTF-8."""


class FileSystemVault:
    """A vault rooted at a local directory.

    Use ``create`` or ``open``. Note IDs are assigned when a note is first
    read through this instance and are kept only in memory: they survive
    renames and moves made through this instance, but not a restart.
    Instances are not thread-safe.
    """

    def __init__(
        self, vault: Vault, *, id_factory: Callable[[], UUID] = uuid4
    ) -> None:
        if not isinstance(vault, Vault):
            raise TypeError(f"vault must be Vault, got {type(vault).__name__}")
        self._vault = vault
        self._root = vault.root_path
        self._new_id = id_factory
        self._ids: dict[PurePosixPath, UUID] = {}

    @classmethod
    def create(
        cls, root: Path, name: str, *, id_factory: Callable[[], UUID] = uuid4
    ) -> "FileSystemVault":
        """Create a vault at ``root``, which may be an existing folder of notes."""
        root = _resolve_root(root, strict=False)
        vault = Vault(id_factory(), name, root)
        root.mkdir(parents=True, exist_ok=True)
        metadata = root / METADATA_DIR
        try:
            os.mkdir(metadata)
        except FileExistsError:
            pass
        _require_real_directory(metadata)
        manifest = {"format": _MANIFEST_FORMAT, "id": str(vault.id), "name": vault.name}
        data = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        try:
            _create_exclusive(metadata / MANIFEST_NAME, data)
        except FileExistsError as exc:
            raise VaultExistsError(f"a Page vault already exists at {root}") from exc
        return cls(vault, id_factory=id_factory)

    @classmethod
    def open(
        cls, root: Path, *, id_factory: Callable[[], UUID] = uuid4
    ) -> "FileSystemVault":
        """Open an existing vault. Never creates or modifies anything."""
        try:
            root = _resolve_root(root, strict=True)
        except FileNotFoundError as exc:
            raise VaultNotFoundError(f"no directory at {root}") from exc
        metadata = root / METADATA_DIR
        manifest_path = metadata / MANIFEST_NAME
        try:
            _require_real_directory(metadata)
            raw, _ = _read_regular_file(manifest_path)
        except FileNotFoundError as exc:
            raise VaultNotFoundError(f"no Page vault at {root}") from exc
        try:
            manifest = json.loads(raw.decode("utf-8"))
            version = manifest["format"]
            vault_id = UUID(manifest["id"])
            name = manifest["name"]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise VaultError(f"invalid vault manifest at {manifest_path}") from exc
        if version != _MANIFEST_FORMAT:
            raise VaultError(f"unsupported vault manifest format {version!r}")
        try:
            vault = Vault(vault_id, name, root)
        except (TypeError, ValueError) as exc:
            raise VaultError(f"invalid vault manifest at {manifest_path}") from exc
        return cls(vault, id_factory=id_factory)

    @property
    def vault(self) -> Vault:
        return self._vault

    def list_note_paths(self) -> list[PurePosixPath]:
        """Return every managed note path, sorted. Does not read note contents.

        Hidden entries, symlinks, and files whose names break the note path
        rules are skipped.
        """
        paths: list[PurePosixPath] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            directory = Path(dirpath)
            dirnames[:] = [
                name
                for name in dirnames
                if not name.startswith(".") and not (directory / name).is_symlink()
            ]
            for filename in filenames:
                full = directory / filename
                relative = PurePosixPath(*full.relative_to(self._root).parts)
                if not _is_managed_path(relative):
                    continue
                try:
                    mode = os.lstat(full).st_mode
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(mode):
                    paths.append(relative)
        return sorted(paths, key=str)

    def read_note(self, path: PurePosixPath) -> Note:
        relative = _require_managed_path(path)
        target = self._existing_file(relative)
        data, info = _read_regular_file(target)
        return self._to_note(relative, _decode(data, relative), info)

    def create_note(self, path: PurePosixPath, content: str = "") -> Note:
        """Create a note. Never overwrites an existing file."""
        relative = _require_managed_path(path)
        data = _encode(content)
        target, _ = self._locate(relative)
        self._make_parent_directories(relative)
        try:
            _create_exclusive(target, data)
        except FileExistsError as exc:
            raise NoteExistsError(f"{relative} already exists") from exc
        return self.read_note(relative)

    def update_note(self, note: Note, content: str) -> Note:
        """Replace a note's content atomically.

        Raises ``NoteConflictError`` if the file no longer contains exactly
        ``note.content``, for example after an edit in another application.
        """
        relative = self._snapshot_path(note)
        data = _encode(content)
        target = self._existing_file(relative)
        current, info = _read_regular_file(target)
        if current != _encode(note.content):
            raise NoteConflictError(f"{relative} changed on disk since it was read")
        _atomic_replace(target, data, mode=stat.S_IMODE(info.st_mode))
        return self.read_note(relative)

    def move_note(self, note: Note, new_path: PurePosixPath) -> Note:
        """Move or rename a note, keeping its ID. Never overwrites a file."""
        source = self._snapshot_path(note)
        destination = _require_managed_path(new_path)
        if destination == source:
            return self.read_note(source)
        source_file = self._existing_file(source)
        destination_file, _ = self._locate(destination)
        self._make_parent_directories(destination)
        try:
            _create_exclusive(destination_file, None)
        except FileExistsError as exc:
            if not _same_file(source_file, destination_file):
                raise NoteExistsError(f"{destination} already exists") from exc
            # Case-only rename on a case-insensitive filesystem.
            os.rename(source_file, destination_file)
        else:
            try:
                os.replace(source_file, destination_file)
            except BaseException:
                _unlink_quietly(destination_file)
                raise
        self._ids[destination] = self._ids.pop(source)
        return self.read_note(destination)

    def rename_note(self, note: Note, new_name: str) -> Note:
        """Rename a note within its current directory."""
        if not isinstance(new_name, str):
            raise TypeError(f"new_name must be str, got {type(new_name).__name__}")
        if "/" in new_name or new_name in {"", ".", ".."}:
            raise ValueError(f"new_name must be a single file name, got {new_name!r}")
        return self.move_note(note, note.relative_path.with_name(new_name))

    def delete_note(self, note: Note) -> None:
        """Permanently delete a note file. There is no trash or undo.

        Raises ``NoteConflictError`` if the file changed since it was read.
        """
        relative = self._snapshot_path(note)
        target = self._existing_file(relative)
        current, _ = _read_regular_file(target)
        if current != _encode(note.content):
            raise NoteConflictError(f"{relative} changed on disk since it was read")
        os.unlink(target)
        del self._ids[relative]

    def _to_note(self, relative: PurePosixPath, content: str, info: os.stat_result) -> Note:
        note_id = self._ids.get(relative)
        if note_id is None:
            note_id = self._new_id()
            self._ids[relative] = note_id
        created_at, updated_at = _timestamps(info)
        return Note(note_id, self._vault.id, relative, content, created_at, updated_at)

    def _snapshot_path(self, note: Note) -> PurePosixPath:
        if not isinstance(note, Note):
            raise TypeError(f"note must be Note, got {type(note).__name__}")
        if note.vault_id != self._vault.id:
            raise VaultError(f"note {note.id} belongs to another vault")
        if self._ids.get(note.relative_path) != note.id:
            raise NoteConflictError(
                f"note {note.id} is not at {note.relative_path} in this vault; "
                "read it again"
            )
        return note.relative_path

    def _locate(self, relative: PurePosixPath) -> tuple[Path, os.stat_result | None]:
        """Map a note path to the filesystem without following symlinks.

        Returns the target and its status if a file with exactly that name
        exists. Rejects symlinks, non-directory parents, and directories
        whose existing name differs only in case.
        """
        current = self._root
        last = len(relative.parts) - 1
        for index, part in enumerate(relative.parts):
            current = current / part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                return self._root.joinpath(*relative.parts), None
            if stat.S_ISLNK(info.st_mode):
                raise InvalidNotePathError(f"{relative}: symlinks are not followed")
            exact = part in os.listdir(current.parent)
            if index == last:
                return current, info if exact else None
            if not exact:
                raise InvalidNotePathError(
                    f"{relative}: {part!r} differs in case from an existing directory"
                )
            if not stat.S_ISDIR(info.st_mode):
                raise InvalidNotePathError(f"{relative}: {part!r} is not a directory")
        raise AssertionError("unreachable: note paths are never empty")

    def _existing_file(self, relative: PurePosixPath) -> Path:
        target, info = self._locate(relative)
        if info is None:
            raise NoteNotFoundError(f"{relative} does not exist")
        if not stat.S_ISREG(info.st_mode):
            raise InvalidNotePathError(f"{relative} is not a regular file")
        return target

    def _make_parent_directories(self, relative: PurePosixPath) -> None:
        current = self._root
        for part in relative.parts[:-1]:
            current = current / part
            try:
                os.mkdir(current)
            except FileExistsError:
                pass
            _require_real_directory(current)


def _resolve_root(root: object, *, strict: bool) -> Path:
    if not isinstance(root, Path):
        raise TypeError(f"root must be Path, got {type(root).__name__}")
    return root.resolve(strict=strict)


def _require_managed_path(path: object) -> PurePosixPath:
    relative = validate_note_path(path)
    for part in relative.parts:
        if part.startswith("."):
            raise InvalidNotePathError(f"{relative}: hidden entries are not managed")
        if part != part.rstrip(" ."):
            raise InvalidNotePathError(f"{relative}: names must not end in a space or dot")
        if any(ch in _NON_PORTABLE_CHARACTERS or ord(ch) < 32 for ch in part):
            raise InvalidNotePathError(f"{relative}: {part!r} contains a non-portable character")
        if part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
            raise InvalidNotePathError(f"{relative}: {part!r} is a reserved name on Windows")
    return relative


def _is_managed_path(path: PurePosixPath) -> bool:
    try:
        _require_managed_path(path)
    except (TypeError, ValueError):
        return False
    return True


def _require_real_directory(path: Path) -> None:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise InvalidNotePathError(f"{path} is not a directory")


def _encode(content: object) -> bytes:
    if not isinstance(content, str):
        raise TypeError(f"content must be str, got {type(content).__name__}")
    # Encoding before touching the disk means invalid text cannot damage a file.
    return content.encode("utf-8")


def _decode(data: bytes, relative: PurePosixPath) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnreadableNoteError(f"{relative} is not valid UTF-8") from exc


def _timestamps(info: os.stat_result) -> tuple[datetime, datetime]:
    updated_at = datetime.fromtimestamp(info.st_mtime, tz=UTC)
    birth = getattr(info, "st_birthtime", None)
    if birth is None:
        return updated_at, updated_at
    return min(datetime.fromtimestamp(birth, tz=UTC), updated_at), updated_at


def _read_regular_file(path: Path) -> tuple[bytes, os.stat_result]:
    fd = os.open(path, os.O_RDONLY | _O_BINARY | _O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise InvalidNotePathError(f"{path} is not a regular file")
        return stream.read(), info


def _create_exclusive(path: Path, data: bytes | None) -> None:
    """Create ``path``, failing if anything exists there, then fill it atomically.

    With ``data=None`` the empty file is left as a reservation for the caller.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW, 0o666)
    os.close(fd)
    if data is None:
        return
    try:
        _atomic_replace(path, data, mode=None)
    except BaseException:
        _unlink_quietly(path)
        raise


def _atomic_replace(target: Path, data: bytes, *, mode: int | None) -> None:
    """Write ``data`` to a temporary file beside ``target``, then swap it in.

    On failure the original file is untouched and the temporary file is removed.
    """
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW, 0o666
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        _unlink_quietly(temporary)
        raise
    _fsync_directory(target.parent)


def _fsync_directory(path: Path) -> None:
    # Persists the rename on POSIX. Windows cannot open directories this way.
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _unlink_quietly(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False
