"""Stage 4 ingestion. Transformer model loading/download is on demand."""

__all__ = ["IngestionIndex"]


def __getattr__(name):
    # Keep the model worker free of FAISS when running as a package module.
    if name == "IngestionIndex":
        from .index import IngestionIndex

        return IngestionIndex
    raise AttributeError(name)
