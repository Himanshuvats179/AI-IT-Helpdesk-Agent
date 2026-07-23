"""Build the shared retriever from settings, with a graceful offline fallback.

Primary (per the chosen design): ChromaDB + sentence-transformers. If those
heavy deps aren't importable, fall back to an in-memory store + hashing embedder
so the service still runs — behind the identical HybridRetriever interface.
"""
from __future__ import annotations

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.retrieval.embedder import (
    DeterministicHashEmbedder,
    SentenceTransformerEmbedder,
)
from app.services.retrieval.retriever import HybridRetriever
from app.services.retrieval.vector_store import ChromaVectorStore, InMemoryVectorStore

logger = get_logger(__name__)


def build_retriever(settings: Settings | None = None) -> HybridRetriever:
    settings = settings or get_settings()
    try:
        embedder = SentenceTransformerEmbedder(settings.embedding_model)
        embedder.dimension  # force model load now so failures surface here
        vector_store = ChromaVectorStore(settings.chroma_path, settings.chroma_collection)
        logger.info("retriever_backend", backend="chroma+sentence-transformers")
    except Exception as exc:  # noqa: BLE001
        logger.warning("retriever_fallback", reason=str(exc), backend="inmemory+hash")
        embedder = DeterministicHashEmbedder()
        vector_store = InMemoryVectorStore()

    return HybridRetriever(
        embedder,
        vector_store,
        top_k=settings.rag_top_k,
        dense_k=settings.rag_dense_k,
        keyword_k=settings.rag_keyword_k,
        score_floor=settings.rag_score_floor,
    )
