"""Escalation persistence."""
from __future__ import annotations

from sqlalchemy import select

from app.core.ids import utcnow
from app.db.models import Escalation
from app.repositories.base import BaseRepository


class EscalationRepository(BaseRepository):
    async def create(self, escalation: Escalation) -> Escalation:
        self.session.add(escalation)
        await self.session.flush()
        return escalation

    async def get(self, escalation_id: str) -> Escalation | None:
        return await self.session.get(Escalation, escalation_id)

    async def get_open_for_ticket(self, ticket_id: str) -> Escalation | None:
        stmt = (
            select(Escalation)
            .where(Escalation.ticket_id == ticket_id, Escalation.status != "resolved")
            .order_by(Escalation.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def list(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Escalation]:
        stmt = select(Escalation)
        if status:
            stmt = stmt.where(Escalation.status == status)
        stmt = stmt.order_by(Escalation.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all())

    async def resolve(self, escalation: Escalation, assignee: str | None = None) -> None:
        escalation.status = "resolved"
        escalation.assignee = assignee or escalation.assignee
        escalation.resolved_at = utcnow()
        await self.session.flush()
