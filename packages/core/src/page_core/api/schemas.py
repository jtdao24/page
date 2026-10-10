"""Strict request and response models for the local API.

Request strings are checked here and converted explicitly to ``UUID``,
``Path`` and ``PurePosixPath`` values at the API boundary. Nothing is coerced:
unknown fields, nulls and wrong JSON types are rejected.
"""

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, NonNegativeInt
from pydantic_core import PydanticCustomError

from page_core.vault import _require_managed_path

_CANONICAL_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _encodable(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def parse_uuid(value: str) -> UUID:
    """Accept only the canonical lowercase hyphenated spelling."""
    if not isinstance(value, str):
        raise TypeError(f"identifier must be str, got {type(value).__name__}")
    if not _CANONICAL_UUID.fullmatch(value):
        raise ValueError("identifier must be a canonical lowercase UUID")
    return UUID(value)


def parse_note_path(value: str) -> PurePosixPath:
    """Convert a canonical relative POSIX string to a managed note path.

    Spellings that ``PurePosixPath`` would silently normalize are rejected
    first; the vault's managed-path rules then apply unchanged.
    """
    if not isinstance(value, str):
        raise TypeError(f"note path must be str, got {type(value).__name__}")
    parts = value.split("/")
    if not _encodable(value) or value.startswith("/") or any(part in {"", "."} for part in parts):
        raise ValueError("note path must be a canonical relative POSIX path")
    path = _require_managed_path(PurePosixPath(value))
    if str(path) != value:
        raise ValueError("note path must be a canonical relative POSIX path")
    return path


def parse_root(value: str) -> Path:
    """Convert an absolute native root without expanding ``~`` or variables."""
    if not isinstance(value, str):
        raise TypeError(f"root path must be str, got {type(value).__name__}")
    if not value or "\x00" in value or not _encodable(value):
        raise ValueError("root path must be a nonempty native path")
    root = Path(value)
    if not root.is_absolute():
        raise ValueError("root path must be absolute")
    return root


def _check(parser: Any, code: str, message: str) -> Any:
    def validate(value: Any) -> Any:
        try:
            parser(value)
        except (TypeError, ValueError):
            raise PydanticCustomError(code, message) from None
        return value
    return validate


def _check_name(value: str) -> str:
    if not value.strip() or not _encodable(value):
        raise ValueError("name must be nonblank text")
    return value


def _check_text(value: str) -> str:
    if not _encodable(value):
        raise ValueError("text must be encodable as UTF-8")
    return value


def _check_renames(value: dict[str, str]) -> dict[str, str]:
    for identifier, path in value.items():
        parse_uuid(identifier)
        parse_note_path(path)
    return value


RootPath = Annotated[str, AfterValidator(_check(parse_root, "invalid_root_path", "Expected a nonempty absolute path"))]
VaultName = Annotated[str, AfterValidator(_check(_check_name, "invalid_name", "Expected nonblank text"))]
NotePath = Annotated[str, AfterValidator(_check(parse_note_path, "invalid_note_path", "Expected a managed relative note path"))]
Content = Annotated[str, AfterValidator(_check(_check_text, "unencodable_text", "Text must be encodable as UTF-8"))]
KnownRenames = Annotated[
    dict[str, str],
    AfterValidator(_check(_check_renames, "invalid_known_renames",
                          "Expected canonical note UUIDs mapped to managed relative note paths")),
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CreateVaultRequest(_Request):
    root_path: RootPath
    name: VaultName


class OpenVaultRequest(_Request):
    root_path: RootPath


class CreateNoteRequest(_Request):
    relative_path: NotePath
    content: Content = ""


class UpdateNoteRequest(_Request):
    content: Content


class MoveNoteRequest(_Request):
    relative_path: NotePath


class ReconcileRequest(_Request):
    known_renames: KnownRenames = Field(default_factory=dict)


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class HealthResponse(_Response):
    status: Literal["ok"]
    version: str


class VaultResponse(_Response):
    id: str
    name: str
    root_path: str
    needs_reconciliation: bool


class NoteSummaryResponse(_Response):
    id: str
    vault_id: str
    relative_path: str
    created_at: str
    updated_at: str
    revision: str


class NoteResponse(NoteSummaryResponse):
    content: str


class ReconcileResponse(_Response):
    added: NonNegativeInt
    modified: NonNegativeInt
    renamed: NonNegativeInt
    missing: NonNegativeInt
    unchanged: NonNegativeInt


class ErrorBody(_Response):
    code: str
    message: str
    details: dict[str, Any] | None


class ErrorResponse(_Response):
    error: ErrorBody


REQUEST_MODELS: tuple[type[BaseModel], ...] = (
    CreateVaultRequest, OpenVaultRequest, CreateNoteRequest,
    UpdateNoteRequest, MoveNoteRequest, ReconcileRequest,
)


class GraphNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    relative_path: str


class GraphLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_note_id: str
    target_reference: str
    target_note_id: str | None
    alias: str | None
    line: int
    unresolved_reason: Literal["missing", "ambiguous", "invalid"] | None


class GraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    vault_id: str
    nodes: list[GraphNodeResponse]
    links: list[GraphLinkResponse]
