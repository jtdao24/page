"""Chunking, embedding and the persistent vector index (requires numpy and faiss)."""

from page_core.embeddings.chunking import (
    DEFAULT_MAX_CHARS,
    TextChunk,
    chunk_markdown,
    heading_text,
)
from page_core.embeddings.encoder import (
    DEFAULT_MODEL,
    Embedder,
    EmbeddingError,
    SentenceTransformerEmbedder,
    normalize_rows,
)
from page_core.embeddings.index import (
    METRIC,
    ChunkHit,
    IndexIncompatibleError,
    IndexStats,
    IndexStorageError,
    SemanticIndex,
    SemanticIndexError,
    SyncReport,
)

__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MODEL",
    "METRIC",
    "ChunkHit",
    "Embedder",
    "EmbeddingError",
    "IndexIncompatibleError",
    "IndexStats",
    "IndexStorageError",
    "SemanticIndex",
    "SemanticIndexError",
    "SentenceTransformerEmbedder",
    "SyncReport",
    "TextChunk",
    "chunk_markdown",
    "heading_text",
    "normalize_rows",
]
