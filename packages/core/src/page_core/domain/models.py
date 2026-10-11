"""Core domain models for Page.

The models are immutable value objects. They validate their own invariants on
construction and never touch the filesystem, a database, or the network.
Invalid types raise ``TypeError``; well-typed but invalid values raise
``ValueError``. Inputs are never coerced.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

_NOTE_SUFFIX = ".md"

# Read-only knowledge sources Page can index besides notes, by kind.
SOURCE_KINDS: dict[str, str] = {
    ".pdf": "pdf",
    ".txt": "text",
    **{suffix: "code" for suffix in (
        ".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".kt", ".swift", ".c", ".h",
        ".cpp", ".hpp", ".cs", ".rb", ".php", ".sh", ".sql", ".html", ".css", ".json", ".yaml",
        ".yml", ".toml",
    )},
}

# Characters that change a path's meaning on some supported platform:
# "\\" is a Windows separator, ":" introduces Windows drives and streams,
# and NUL terminates paths at the OS boundary.
_UNSAFE_PATH_CHARACTERS = frozenset("\\:\x00")


def _require_type[T](field: str, value: object, expected: type[T]) -> T:
    if not isinstance(value, expected):
        raise TypeError(
            f"{field} must be {expected.__name__}, got {type(value).__name__}"
        )
    return value


def _require_int(field: str, value: object) -> int:
    # bool is a subclass of int but is never a meaningful count or offset.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    return value


def _require_non_negative_int(field: str, value: object) -> int:
    number = _require_int(field, value)
    if number < 0:
        raise ValueError(f"{field} must be non-negative, got {number}")
    return number


def _require_non_blank_str(field: str, value: object) -> str:
    text = _require_type(field, value, str)
    if not text.strip():
        raise ValueError(f"{field} must not be empty or whitespace")
    return text


def _require_aware_datetime(field: str, value: object) -> datetime:
    moment = _require_type(field, value, datetime)
    if moment.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return moment


def _require_relative_path(field: str, value: object) -> PurePosixPath:
    # Only the pure POSIX flavour is accepted so the domain never holds a
    # platform-specific, filesystem-capable path object.
    if type(value) is not PurePosixPath:
        raise TypeError(f"{field} must be PurePosixPath, got {type(value).__name__}")
    if value.is_absolute():
        raise ValueError(f"{field} must be relative, got {str(value)!r}")
    if not value.parts:
        raise ValueError(f"{field} must not be empty")
    if ".." in value.parts:
        raise ValueError(f"{field} must not contain '..', got {str(value)!r}")
    if _UNSAFE_PATH_CHARACTERS.intersection(str(value)):
        raise ValueError(
            f"{field} must not contain '\\', ':' or NUL, got {str(value)!r}"
        )
    return value


def _require_note_path(field: str, value: object) -> PurePosixPath:
    path = _require_relative_path(field, value)
    if path.suffix != _NOTE_SUFFIX:
        raise ValueError(f"{field} must end in {_NOTE_SUFFIX!r}, got {str(path)!r}")
    return path


def source_kind(path: PurePosixPath) -> str | None:
    """The source kind for a path's extension (any case), or None if unsupported."""
    return SOURCE_KINDS.get(path.suffix.lower())


def _require_source_path(field: str, value: object) -> PurePosixPath:
    path = _require_relative_path(field, value)
    if source_kind(path) is None:
        raise ValueError(f"{field} must have a supported source suffix, got {str(path)!r}")
    return path


def validate_note_path(path: object) -> PurePosixPath:
    """Return ``path`` if it is a valid ``Note.relative_path``, else raise."""
    return _require_note_path("note path", path)


def validate_source_path(path: object) -> PurePosixPath:
    """Return ``path`` if it is a valid ``SourceDocument.relative_path``, else raise."""
    return _require_source_path("source path", path)


def validate_document_path(path: object) -> PurePosixPath:
    """Return ``path`` if it is a valid note or source path, else raise."""
    _require_relative_path("document path", path)
    if isinstance(path, PurePosixPath) and path.suffix == _NOTE_SUFFIX:
        return path
    return _require_source_path("document path", path)


@dataclass(frozen=True, slots=True)
class Vault:
    """A local knowledge vault. Identity is ``id``, not ``root_path``."""

    id: UUID
    name: str
    root_path: Path

    def __post_init__(self) -> None:
        _require_type("Vault.id", self.id, UUID)
        _require_non_blank_str("Vault.name", self.name)
        root_path = _require_type("Vault.root_path", self.root_path, Path)
        if not root_path.is_absolute():
            raise ValueError(
                f"Vault.root_path must be absolute, got {str(self.root_path)!r}"
            )


@dataclass(frozen=True, slots=True)
class Note:
    """A Markdown document in a vault. Identity is ``id``, not the path."""

    id: UUID
    vault_id: UUID
    relative_path: PurePosixPath
    content: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_type("Note.id", self.id, UUID)
        _require_type("Note.vault_id", self.vault_id, UUID)
        _require_note_path("Note.relative_path", self.relative_path)
        _require_type("Note.content", self.content, str)
        _require_aware_datetime("Note.created_at", self.created_at)
        _require_aware_datetime("Note.updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("Note.updated_at must not be earlier than created_at")


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A read-only file in a vault (PDF, code or text) and the text extracted from it.

    Identity follows the path: ``id`` is derived from the vault and path, so a
    moved source is a new document. ``revision`` is the SHA-256 of the file bytes.
    Chunk byte offsets refer to ``content``, the extracted text.
    """

    id: UUID
    vault_id: UUID
    relative_path: PurePosixPath
    content: str
    revision: str

    def __post_init__(self) -> None:
        _require_type("SourceDocument.id", self.id, UUID)
        _require_type("SourceDocument.vault_id", self.vault_id, UUID)
        _require_source_path("SourceDocument.relative_path", self.relative_path)
        _require_type("SourceDocument.content", self.content, str)
        revision = _require_type("SourceDocument.revision", self.revision, str)
        if len(revision) != 64 or any(ch not in "0123456789abcdef" for ch in revision):
            raise ValueError("SourceDocument.revision must be a lowercase SHA-256 hex digest")

    @property
    def kind(self) -> str:
        return SOURCE_KINDS[self.relative_path.suffix.lower()]


@dataclass(frozen=True, slots=True)
class Link:
    """A directed reference from a note to a possibly unresolved target."""

    source_note_id: UUID
    target_reference: str
    target_note_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_type("Link.source_note_id", self.source_note_id, UUID)
        _require_non_blank_str("Link.target_reference", self.target_reference)
        if self.target_note_id is not None:
            _require_type("Link.target_note_id", self.target_note_id, UUID)


@dataclass(frozen=True, slots=True)
class Chunk:
    """A span of a note, located by the UTF-8 byte interval [start_byte, end_byte)."""

    id: UUID
    note_id: UUID
    ordinal: int
    text: str
    start_byte: int
    end_byte: int
    token_count: int | None = None

    def __post_init__(self) -> None:
        _require_type("Chunk.id", self.id, UUID)
        _require_type("Chunk.note_id", self.note_id, UUID)
        _require_non_negative_int("Chunk.ordinal", self.ordinal)
        _require_type("Chunk.text", self.text, str)
        if not self.text:
            raise ValueError("Chunk.text must not be empty")
        _require_non_negative_int("Chunk.start_byte", self.start_byte)
        _require_non_negative_int("Chunk.end_byte", self.end_byte)
        if self.end_byte <= self.start_byte:
            raise ValueError(
                "Chunk.end_byte must be greater than start_byte, "
                f"got [{self.start_byte}, {self.end_byte})"
            )
        if self.token_count is not None:
            _require_non_negative_int("Chunk.token_count", self.token_count)


@dataclass(frozen=True, slots=True)
class ContextResult:
    """An assembled LLM context package and the chunks it was built from."""

    context_text: str
    selected_chunks: tuple[Chunk, ...]
    token_count: int
    token_budget: int

    def __post_init__(self) -> None:
        _require_type("ContextResult.context_text", self.context_text, str)
        _require_type("ContextResult.selected_chunks", self.selected_chunks, tuple)
        for index, chunk in enumerate(self.selected_chunks):
            _require_type(f"ContextResult.selected_chunks[{index}]", chunk, Chunk)
        _require_non_negative_int("ContextResult.token_count", self.token_count)
        _require_int("ContextResult.token_budget", self.token_budget)
        if self.token_budget <= 0:
            raise ValueError(
                f"ContextResult.token_budget must be positive, got {self.token_budget}"
            )
        if self.token_count > self.token_budget:
            raise ValueError(
                f"ContextResult.token_count ({self.token_count}) exceeds "
                f"token_budget ({self.token_budget})"
            )
