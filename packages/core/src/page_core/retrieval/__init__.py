"""Retrieval over the vault's semantic index."""

from page_core.retrieval.semantic import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_QUERY_CHARS,
    NoteMatch,
    NoteReader,
    QueryValidationError,
    SemanticSearchResult,
    SemanticSearchService,
    validate_query,
)

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_QUERY_CHARS",
    "NoteMatch",
    "NoteReader",
    "QueryValidationError",
    "SemanticSearchResult",
    "SemanticSearchService",
    "validate_query",
]
