from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List
import numpy as np


class EmbeddingBackend(ABC):
    @abstractmethod
    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Return L2-normalized float32 vectors shaped (n, dim)."""

    def embed_texts_safe(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        return self.embed_texts(texts)


class SentenceTransformerBackend(EmbeddingBackend):
    """Local semantic embeddings. Model is loaded lazily by the clustering stage."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError("pip install sentence-transformers") from exc
        self._model = SentenceTransformer(model_name)
        self.model_name = model_name

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)
