"""Stage 4 SQLite metadata persistence. No parsing, API, UI, or ML imports."""

from .persistent import MetadataSyncError, PersistentVault, ReconcileResult
from .repository import MetadataError, MetadataNotFoundError, MetadataRepository, NoteMetadata

__all__ = [
    "MetadataError", "MetadataNotFoundError", "MetadataRepository", "MetadataSyncError",
    "NoteMetadata", "PersistentVault", "ReconcileResult",
]
