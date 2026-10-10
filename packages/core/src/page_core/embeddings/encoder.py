"""Text embedders.

Every embedder returns float32 vectors normalized to unit L2 length, so the
inner product of two vectors is their cosine similarity. Documents and queries
go through the same ``embed`` call and the same model.
"""

import threading
from collections.abc import Sequence
from typing import Protocol

import numpy as np

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingError(RuntimeError):
    """The embedding model could not be loaded or failed to embed text."""


class Embedder(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return an ``(len(texts), dimension)`` float32 array of unit vectors."""
        ...


def normalize_rows(vectors: object, dimension: int) -> np.ndarray:
    """Validate an embedding matrix and L2-normalize each row.

    Raises ``EmbeddingError`` for the wrong shape or non-finite values. A zero
    row stays zero and therefore scores 0 against everything.
    """
    matrix = np.array(vectors, dtype=np.float32, copy=True)
    if matrix.ndim != 2 or matrix.shape[1] != dimension:
        raise EmbeddingError(
            f"expected embeddings of shape (n, {dimension}), got {matrix.shape}"
        )
    if not np.all(np.isfinite(matrix)):
        raise EmbeddingError("embeddings contain NaN or infinite values")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.divide(matrix, norms, out=matrix, where=norms > 0)
    return np.ascontiguousarray(matrix)


class SentenceTransformerEmbedder:
    """Embeds text with a Sentence Transformers model, loaded once.

    Requires the ``embeddings`` extra (``pip install page-core[embeddings]``).
    The model is downloaded from Hugging Face on first use and cached locally.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "sentence-transformers is not installed; "
                "install page-core with the 'embeddings' extra"
            ) from exc
        try:
            self._model = SentenceTransformer(model_name, device=device)
        except Exception as exc:
            raise EmbeddingError(f"could not load embedding model {model_name!r}: {exc}") from exc
        # get_embedding_dimension replaced get_sentence_embedding_dimension in v6.
        get_dimension = getattr(self._model, "get_embedding_dimension", None) or (
            self._model.get_sentence_embedding_dimension
        )
        dimension = get_dimension()
        if not dimension:
            raise EmbeddingError(f"model {model_name!r} does not report a dimension")
        self._model_id = model_name
        self._dimension = int(dimension)
        self._batch_size = batch_size
        # Searches and indexing run on different threads; encode one batch at a time.
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        try:
            with self._lock:
                vectors = self._model.encode(
                    list(texts),
                    batch_size=self._batch_size,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
        except Exception as exc:
            raise EmbeddingError(f"embedding failed: {exc}") from exc
        return normalize_rows(vectors, self._dimension)
