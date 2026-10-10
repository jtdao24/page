"""Stage 4 SQLite metadata persistence. No parsing, API, UI, or ML imports."""

from .persistent import InvalidRenameError, MetadataSyncError, PersistentVault, ReconcileResult
from .repository import (
    MetadataDecodeError, MetadataError, MetadataNotFoundError, MetadataRepository, NoteMetadata,
)

__all__ = [
    "InvalidRenameError", "MetadataDecodeError", "MetadataError", "MetadataNotFoundError",
    "MetadataRepository", "MetadataSyncError",
    "NoteMetadata", "PersistentVault", "ReconcileResult",
]
