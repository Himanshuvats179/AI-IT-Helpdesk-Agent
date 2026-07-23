"""Ticket + message persistence."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.core.constants import TicketStatus
from app.core.exceptions import NotFoundError
from app.core.ids import utcnow
from app.db.models import Message, Ticket
from app.repositories.base import BaseRepository


class TicketRepository(BaseRepository):
    async def create(self, ticket: Ticket) -> Ticket:
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def get(self, ticket_id: str) -> Ticket | None:
        return await self.session.get(Ticket, ticket_id)

    async def get_or_404(self, ticket_id: str) -> Ticket:
        ticket = await self.get(ticket_id)
        if ticket is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")
        return ticket

    async def list(
        self,
        *,
        requester_upn: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Ticket], int]:
        stmt = select(Ticket)
        count_stmt = select(func.count()).select_from(Ticket)
        if requester_upn:
            stmt = stmt.where(Ticket.requester_upn == requester_upn)
            count_stmt = count_stmt.where(Ticket.requester_upn == requester_upn)
        if status:
            stmt = stmt.where(Ticket.status == status)
            count_stmt = count_stmt.where(Ticket.status == status)
        stmt = stmt.order_by(Ticket.created_at.desc()).limit(limit).offset(offset)

        items = list((await self.session.scalars(stmt)).all())
        total = int((await self.session.scalar(count_stmt)) or 0)
        return items, total

    async def find_recent_duplicate(
        self, *, requester_upn: str, dedupe_key: str, window_minutes: int = 60
    ) -> Ticket | None:
        """Find a recent, still-open ticket from the same requester with the same key."""
        cutoff = utcnow() - timedelta(minutes=window_minutes)
        open_states = [
            TicketStatus.NEW.value,
            TicketStatus.TRIAGING.value,
            TicketStatus.IN_PROGRESS.value,
            TicketStatus.AWAITING_USER.value,
            TicketStatus.AWAITING_VERIFICATION.value,
            TicketStatus.AWAITING_APPROVAL.value,
            TicketStatus.ESCALATED.value,
            TicketStatus.HUMAN_HANDLING.value,
        ]
        stmt = (
            select(Ticket)
            .where(
                Ticket.requester_upn == requester_upn,
                Ticket.dedupe_key == dedupe_key,
                Ticket.status.in_(open_states),
                Ticket.created_at >= cutoff,
            )
            .order_by(Ticket.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    # ---- messages ----
    async def add_message(
        self, *, ticket_id: str, role: str, body: str, author: str | None = None, meta: dict | None = None
    ) -> Message:
        message = Message(ticket_id=ticket_id, role=role, body=body, author=author, meta=meta or {})
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_messages(self, ticket_id: str) -> list[Message]:
        stmt = select(Message).where(Message.ticket_id == ticket_id).order_by(Message.created_at)
        return list((await self.session.scalars(stmt)).all())
