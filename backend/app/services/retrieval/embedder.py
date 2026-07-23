"""Embedding abstraction + sentence-transformers implementation.

The :class:`Embedder` Protocol lets the retriever stay decoupled from any
specific model. Production uses a local sentence-transformers model (offline
after a one-time download); tests inject a deterministic fake.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class Embedder(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Local semantic embeddings via sentence-transformers (cosine-normalized)."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None  # lazy: avoid the heavy import/download until first use
        self._dim: int | None = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("loading_embedding_model", model=self.model_name)
            self._model = SentenceTransformer(self.model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())
        return self._model

    @property
    def dimension(self) -> int:
        if self._dim is None:
            self._ensure_model()
        return int(self._dim or 384)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        model = self._ensure_model()
        vector = model.encode([text], normalize_embeddings=True, convert_to_numpy=True)[0]
        return vector.tolist()


class DeterministicHashEmbedder:
    """Dependency-free bag-of-words hashing embedder (cosine-normalized).

    Used as a fallback when sentence-transformers isn't installed, and by tests
    (fast, offline, deterministic). Overlapping vocabulary -> higher similarity,
    which is enough to exercise the hybrid retriever's behaviour.
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def _embed(self, text: str) -> list[float]:
        import math
        import re

        vec = [0.0] * self._dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            vec[hash(token) % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
