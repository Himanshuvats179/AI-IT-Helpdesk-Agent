"""Knowledge base article persistence."""
from __future__ import annotations

from sqlalchemy import select

from app.core.ids import utcnow
from app.db.models import KBArticle
from app.repositories.base import BaseRepository


class KBRepository(BaseRepository):
    async def upsert(self, article: KBArticle) -> KBArticle:
        existing = await self.session.get(KBArticle, article.id)
        if existing is None:
            self.session.add(article)
            await self.session.flush()
            return article
        # update fields in place
        for field in (
            "title", "category", "symptoms", "applies_to", "steps",
            "required_tools", "risk_level", "preconditions", "content",
        ):
            setattr(existing, field, getattr(article, field))
        existing.version += 1
        existing.last_verified = utcnow()
        await self.session.flush()
        return existing

    async def get(self, article_id: str) -> KBArticle | None:
        return await self.session.get(KBArticle, article_id)

    async def get_many(self, ids: list[str]) -> list[KBArticle]:
        if not ids:
            return []
        stmt = select(KBArticle).where(KBArticle.id.in_(ids))
        return list((await self.session.scalars(stmt)).all())

    async def all(self, category: str | None = None) -> list[KBArticle]:
        stmt = select(KBArticle)
        if category:
            stmt = stmt.where(KBArticle.category == category)
        stmt = stmt.order_by(KBArticle.id)
        return list((await self.session.scalars(stmt)).all())

    async def delete(self, article_id: str) -> bool:
        article = await self.get(article_id)
        if article is None:
            return False
        await self.session.delete(article)
        await self.session.flush()
        return True

    async def record_outcome(self, article_id: str, success: bool, alpha: float = 0.2) -> None:
        """EWMA update of an article's success_rate from a follow-up outcome."""
        article = await self.get(article_id)
        if article is None:
            return
        prior = article.success_rate if article.resolution_count > 0 else (1.0 if success else 0.0)
        article.success_rate = round((1 - alpha) * prior + alpha * (1.0 if success else 0.0), 4)
        article.resolution_count += 1
        await self.session.flush()
