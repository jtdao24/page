"""API errors and safe HTTP error translation.

Every error response uses one envelope with a stable code and a fixed message.
Exception text, input values, request bodies and credentials are never echoed:
storage messages can contain paths, and validation context can contain input.
"""

import logging
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from starlette.responses import JSONResponse

from page_core.llm import (
    LLMAuthError, LLMBlockedError, LLMNotConfiguredError, LLMRateLimitError, LLMResponseError,
    LLMUnavailableError,
)
from page_core.semantic import ModelUnavailableError, IndexCorruptError, EmbeddingError
from page_core.metadata import MetadataDecodeError, MetadataError, MetadataNotFoundError, MetadataSyncError
from page_core.vault import (
    InvalidNotePathError, NoteConflictError, NoteExistsError, NoteNotFoundError,
    UnreadableNoteError, VaultExistsError, VaultNotFoundError,
)

from .service import (
    InvalidReconciliationError, InvalidVaultError, InvalidSearchError,
    NoteNotFoundInVaultError, ReconciliationRequiredError, RevisionConflictError,
    StorageUnavailableError, VaultAlreadyOpenError, VaultIdentityConflictError,
    VaultSessionNotFoundError,
)

logger = logging.getLogger("page_core.api")

_SQLITE_BUSY_CODES = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})


class ApiError(Exception):
    """An HTTP error with a stable machine code and a safe message."""

    def __init__(self, status: int, code: str, message: str, *,
                 details: Mapping[str, Any] | None = None,
                 headers: Mapping[str, str] | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.details = None if details is None else dict(details)
        self.headers = dict(headers or {})


def error_response(error: ApiError) -> JSONResponse:
    body = {"error": {"code": error.code, "message": error.message, "details": error.details}}
    return JSONResponse(body, status_code=error.status, headers=error.headers)


_VALIDATION_MESSAGES = {
    "missing": "Field required",
    "extra_forbidden": "Unknown field",
    "string_type": "Expected a string",
    "dict_type": "Expected an object",
    "model_type": "Expected a JSON object",
    "model_attributes_type": "Expected a JSON object",
    "json_invalid": "Malformed JSON",
    "json_type": "Expected JSON",
    "invalid_root_path": "Expected a nonempty absolute path",
    "invalid_name": "Expected nonblank text",
    "invalid_note_path": "Expected a managed relative note path",
    "unencodable_text": "Text must be encodable as UTF-8",
    "invalid_known_renames": "Expected canonical note UUIDs mapped to managed relative note paths",
    "invalid_uuid": "Expected a canonical lowercase UUID",
    "invalid_if_match": "Expected exactly one strong quoted revision",
}


def validation_error(errors: Iterable[Mapping[str, Any]], *, prefix: tuple[str, ...] = (),
                     known_fields: frozenset[str] = frozenset()) -> ApiError:
    """Build a 422 from validation errors, keeping only safe parts.

    Locations keep known field names and list indexes; other location parts,
    such as user-supplied mapping keys, are replaced with ``"*"``.
    """
    items = []
    for error in errors:
        code = str(error.get("type", "invalid"))
        location = list(prefix)
        for part in error.get("loc", ()):
            if isinstance(part, int) and not isinstance(part, bool):
                location.append(part)
            elif part in known_fields or part == "[key]":
                location.append(part)
            else:
                location.append("*")
        items.append({"location": location, "code": code,
                      "message": _VALIDATION_MESSAGES.get(code, "Invalid value")})
    return ApiError(422, "validation_error", "The request is invalid.", details={"errors": items})


def field_error(location: list[str], code: str) -> ApiError:
    return validation_error([{"type": code, "loc": tuple(location)}], known_fields=frozenset(location))


def _is_busy(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF in _SQLITE_BUSY_CODES
    return isinstance(error, sqlite3.OperationalError) and any(
        word in str(error).lower() for word in ("locked", "busy"))


def translate(error: BaseException) -> ApiError:
    """Map a storage or session exception to an ``ApiError``.

    Specific classes are checked before their bases. Unrecognized exceptions,
    including ordinary ``TypeError``/``ValueError``/``OSError`` not listed
    here, are server errors, never client errors.
    """
    if isinstance(error, ApiError):
        return error
    if isinstance(error, MetadataSyncError):
        return ApiError(503, "metadata_sync_failed",
                        "The filesystem changed but metadata could not be saved; reconcile the vault.",
                        details={
                            "filesystem_changed": True,
                            "operation": error.operation,
                            "relative_path": str(error.path),
                            # A failed create has no committed persistent identity.
                            "note_id": None if error.operation == "create" else str(error.note_id),
                            "reconciliation_required": True,
                        })
    simple: list[tuple[type[BaseException], int, str, str]] = [
        (LLMNotConfiguredError, 503, "llm_not_configured",
         "Add a Gemini API key in Page, or set GEMINI_API_KEY before starting Page Core."),
        (LLMAuthError, 502, "llm_auth_failed", "Gemini rejected the API key; check the key saved in Page or GEMINI_API_KEY."),
        (LLMRateLimitError, 429, "llm_rate_limited", "Gemini's rate limit or quota was reached; try again later."),
        (LLMBlockedError, 422, "llm_blocked", "Gemini declined to answer this request."),
        (LLMUnavailableError, 503, "llm_unavailable", "Gemini could not be reached; try again."),
        (LLMResponseError, 502, "llm_failed",
         "Gemini rejected the request or gave no usable answer; check GEMINI_API_KEY and PAGE_GEMINI_MODEL."),
        (ModelUnavailableError, 503, "model_unavailable", "Prepare the local embedding model before searching."),
        (IndexCorruptError, 503, "index_corrupt", "The semantic index is corrupt; rebuild it."),
        (EmbeddingError, 503, "embedding_failed", "Local embedding inference failed; try again."),
        (InvalidSearchError, 422, "invalid_search", "The query exceeds the embedding model input limit."),
        (VaultSessionNotFoundError, 404, "vault_not_found", "No open vault has this ID."),
        (VaultAlreadyOpenError, 409, "vault_exists", "A Page vault already exists at this root."),
        (VaultIdentityConflictError, 409, "vault_identity_conflict",
         "Another open vault already has this vault's ID."),
        (InvalidVaultError, 422, "invalid_vault", "The vault manifest or structure is invalid or unsupported."),
        (NoteNotFoundInVaultError, 404, "note_not_found", "No active note has this ID in this vault."),
        (RevisionConflictError, 412, "revision_conflict",
         "The note changed since this revision was read; read it again."),
        (ReconciliationRequiredError, 409, "reconciliation_required",
         "Reconcile this vault before using its notes."),
        (InvalidReconciliationError, 422, "invalid_reconciliation",
         "Known renames require a missing source ID and a unique existing destination."),
        (StorageUnavailableError, 503, "storage_unavailable", "Private metadata storage is unavailable."),
        (MetadataDecodeError, 500, "storage_error", "Stored metadata could not be read."),
        (MetadataNotFoundError, 404, "note_not_found", "No active note has this ID in this vault."),
        (MetadataError, 503, "storage_unavailable", "Metadata storage refused or could not perform the operation."),
        (VaultExistsError, 409, "vault_exists", "A Page vault already exists at this root."),
        (VaultNotFoundError, 404, "vault_not_found", "No Page vault exists at this root."),
        (NoteNotFoundError, 404, "note_not_found", "The note file does not exist."),
        (NoteExistsError, 409, "note_exists", "A file already exists at the destination path."),
        (NoteConflictError, 409, "note_conflict", "The note changed on disk; read it again."),
        (UnreadableNoteError, 422, "unreadable_note", "The note file is not valid UTF-8."),
        (InvalidNotePathError, 422, "validation_error", "The note path is not managed by the vault."),
        (PermissionError, 403, "filesystem_forbidden", "The filesystem denied access."),
    ]
    for kind, status, code, message in simple:
        if isinstance(error, kind):
            return ApiError(status, code, message)
    if isinstance(error, sqlite3.Error):
        if _is_busy(error):
            return ApiError(503, "storage_busy", "Metadata storage is busy; try again.")
        if isinstance(error, sqlite3.DatabaseError):
            _log_unexpected("storage_error", error)
            return ApiError(500, "storage_error", "Metadata storage failed.")
    elif isinstance(error, OSError):
        _log_unexpected("filesystem_error", error)
        return ApiError(500, "filesystem_error", "A filesystem operation failed.")
    _log_unexpected("internal_error", error)
    return ApiError(500, "internal_error", "An unexpected error occurred.")


def internal_error() -> ApiError:
    return ApiError(500, "internal_error", "An unexpected error occurred.")


def _log_unexpected(code: str, error: BaseException) -> None:
    # Only the exception type: messages may contain paths or other user data.
    logger.error("%s: %s", code, type(error).__name__)
