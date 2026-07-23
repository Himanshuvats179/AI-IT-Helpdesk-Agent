"""Verification-token persistence (identity step-up)."""
from __future__ import annotations

from sqlalchemy import select

from app.core.ids import utcnow
from app.db.models import VerificationToken
from app.repositories.base import BaseRepository


class VerificationRepository(BaseRepository):
    async def create(self, token: VerificationToken) -> VerificationToken:
        self.session.add(token)
        await self.session.flush()
        return token

    async def get(self, token_id: str) -> VerificationToken | None:
        return await self.session.get(VerificationToken, token_id)

    async def get_active_for_ticket(self, ticket_id: str) -> VerificationToken | None:
        """Most recent pending, non-expired token for a ticket."""
        now = utcnow()
        stmt = (
            select(VerificationToken)
            .where(
                VerificationToken.ticket_id == ticket_id,
                VerificationToken.status == "pending",
                VerificationToken.expires_at > now,
            )
            .order_by(VerificationToken.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def get_verified_unconsumed(self, ticket_id: str, subject: str) -> VerificationToken | None:
        """A subject-bound, verified-but-unconsumed token (the precondition gate)."""
        now = utcnow()
        stmt = (
            select(VerificationToken)
            .where(
                VerificationToken.ticket_id == ticket_id,
                VerificationToken.subject == subject,
                VerificationToken.status == "verified",
                VerificationToken.expires_at > now,
            )
            .order_by(VerificationToken.verified_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)
