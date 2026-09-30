from __future__ import annotations

import hashlib
import re
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


class LightweightEmbeddingBackend(EmbeddingBackend):
    """Deterministic, dependency-light text embeddings for serverless runtime.

    Uses hashed unigrams/bigrams rather than a model-backed embedding package.
    This keeps the Vercel function bundle small while preserving deterministic
    vector geometry for HDBSCAN. Use SentenceTransformerBackend off-platform
    when model-backed semantic embeddings are desired.
    """

    def __init__(self, dimensions: int = 256):
        self.dimensions = max(32, int(dimensions))

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
            features = tokens + [f"{a}::{b}" for a, b in zip(tokens, tokens[1:])]
            for feature in features:
                digest = hashlib.sha256(feature.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                sign = 1.0 if digest[4] & 1 else -1.0
                vectors[row, index] += sign

        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        np.divide(vectors, np.maximum(norms, 1e-12), out=vectors)
        return vectors


class SentenceTransformerBackend(EmbeddingBackend):
    """Optional local semantic embeddings. Loaded only when explicitly selected."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "SentenceTransformer backend is optional; "
                "install requirements-clustering.txt"
            ) from exc
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


def build_embedding_backend(config=None) -> EmbeddingBackend:
    backend_name = getattr(config, "embedding_backend", "lightweight")
    if backend_name == "sentence_transformer":
        return SentenceTransformerBackend(
            getattr(config, "embedding_model", "all-MiniLM-L6-v2")
        )
    return LightweightEmbeddingBackend(
        getattr(config, "embedding_dimensions", 256)
    )
