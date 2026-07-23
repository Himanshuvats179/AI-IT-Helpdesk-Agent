"""Knowledge-base service: persistence + indexing + retrieval orchestration.

Owns the boundary between the durable KB (SQLite) and the search index
(retriever over ChromaDB). The retriever is a shared process singleton; this
service is constructed per-operation with a DB session.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import KBArticle
from app.repositories.kb_repository import KBRepository
from app.schemas.kb import KBArticleIn, RetrievalResult
from app.services.retrieval.retriever import HybridRetriever, IndexedArticle

logger = get_logger(__name__)


def build_content(article: KBArticleIn) -> str:
    """Derive the searchable text blob for an article (used for embed + BM25)."""
    if article.content:
        return article.content
    parts = [article.title]
    if article.symptoms:
        parts.append("Symptoms: " + "; ".join(article.symptoms))
    if article.applies_to:
        parts.append("Applies to: " + ", ".join(article.applies_to))
    if article.steps:
        parts.append("Steps: " + " ".join(s.text for s in article.steps))
    return "\n".join(parts)


class KBService:
    def __init__(self, session: AsyncSession, retriever: HybridRetriever) -> None:
        self.session = session
        self.repo = KBRepository(session)
        self.retriever = retriever

    async def seed(self, articles: list[KBArticleIn]) -> int:
        for article in articles:
            orm = KBArticle(
                id=article.id,
                title=article.title,
                category=article.category.value,
                symptoms=article.symptoms,
                applies_to=article.applies_to,
                steps=[s.model_dump() for s in article.steps],
                required_tools=article.required_tools,
                risk_level=article.risk_level.value,
                preconditions=article.preconditions,
                content=build_content(article),
            )
            await self.repo.upsert(orm)
        await self.session.flush()
        count = await self.reindex()
        return count

    async def reindex(self) -> int:
        articles = await self.repo.all()
        indexed = [
            IndexedArticle(
                id=a.id,
                title=a.title,
                category=a.category,
                risk_level=a.risk_level,
                content=a.content,
                steps=a.steps,
                required_tools=a.required_tools,
                applies_to=a.applies_to,
            )
            for a in articles
        ]
        # Embedding + BM25 build are CPU-bound; offload so we don't block the loop.
        await asyncio.to_thread(self.retriever.index, indexed)
        return len(indexed)

    async def search(self, query: str, category: str | None = None) -> RetrievalResult:
        # Dense embedding + BM25 scoring are blocking/CPU-bound — run off the loop.
        return await asyncio.to_thread(self.retriever.search, query, category)

    async def get_articles(self, ids: list[str]) -> list[KBArticle]:
        return await self.repo.get_many(ids)

    async def record_outcome(self, article_ids: list[str], success: bool) -> None:
        for article_id in article_ids:
            await self.repo.record_outcome(article_id, success)
