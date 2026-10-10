"""Deterministic embedders for tests: no model download, no network."""

import re
import threading
from collections.abc import Sequence

import numpy as np

# Words for the same topic share an axis, so a query can match a note that uses
# different words, the way a real embedding model matches paraphrases.
TOPICS = {
    0: "logic boolean circuit circuits gate gates karnaugh simplify minimize digital",
    1: "bread flour yeast dough knead bake baking sourdough",
    2: "planet planets orbit orbits star stars telescope astronomy",
    3: "garden soil compost seeds plant plants watering",
    4: "python function functions class classes code programming",
}
VOCABULARY = {word: axis for axis, words in TOPICS.items() for word in words.split()}
BIAS_AXIS = 7


class KeywordEmbedder:
    """Maps each text to topic counts plus a small constant bias, L2-normalized."""

    def __init__(self, model_id: str = "test/keywords", dimension: int = 8) -> None:
        self._model_id = model_id
        self._dimension = dimension
        self.calls: list[list[str]] = []
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        with self._lock:
            self.calls.append(list(texts))
        matrix = np.zeros((len(texts), self._dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"[a-z]+", text.lower()):
                axis = VOCABULARY.get(word)
                if axis is not None and axis < self._dimension:
                    matrix[row, axis] += 1.0
            matrix[row, min(BIAS_AXIS, self._dimension - 1)] += 0.1
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix

    def embedded_texts(self) -> list[str]:
        return [text for call in self.calls for text in call]


class FailingEmbedder(KeywordEmbedder):
    """Embeds documents normally but fails once ``fail`` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.fail = False

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if self.fail:
            from page_core.embeddings import EmbeddingError

            raise EmbeddingError("model crashed")
        return super().embed(texts)
