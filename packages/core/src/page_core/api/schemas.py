"""Request and response bodies for the Page Core HTTP API.

apps/desktop/src/api/types.ts mirrors these models; keep the two in step.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from page_core.retrieval import DEFAULT_LIMIT, MAX_LIMIT, MAX_QUERY_CHARS


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


class SemanticSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(max_length=MAX_QUERY_CHARS)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("query must not be blank")
        return text


class ChunkLocation(BaseModel):
    id: str
    """Stable UUID of the chunk; kept across edits to other parts of the note."""
    ordinal: int
    """Position of the chunk within the note, from 0."""
    start_byte: int
    end_byte: int
    """The chunk is the note's UTF-8 bytes [start_byte, end_byte)."""
    heading: str | None


class SemanticSearchHit(BaseModel):
    note_id: str
    path: str
    title: str
    score: float
    """Cosine similarity of the query and the best-matching chunk, in [-1, 1]."""
    excerpt: str
    chunk: ChunkLocation
    matched_chunks: int


class SemanticSearchResponse(BaseModel):
    query: str
    limit: int
    metric: Literal["cosine"]
    model: str
    results: list[SemanticSearchHit]
    """Ranked by descending score, then by path; one entry per note."""


class NoteResponse(BaseModel):
    id: str
    path: str
    title: str
    content: str
    updated_at: datetime


class SyncReportBody(BaseModel):
    added: int
    updated: int
    removed: int
    unchanged: int
    failed: list[str]


class IndexStatusResponse(BaseModel):
    state: Literal["loading", "indexing", "ready", "error"]
    searchable: bool
    detail: str | None
    vault_name: str
    model: str | None
    dimension: int | None
    metric: Literal["cosine"]
    notes: int
    chunks: int
    last_sync_at: datetime | None
    last_sync: SyncReportBody | None
