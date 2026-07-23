"""Proactive 2-hour follow-up loop.

Scheduling uses the single durable ``scheduled_jobs`` mechanism (survives
restarts; exactly-once via idempotency key + lease). The follow-up asks one
closed question; the reply is classified to close / reopen / clarify. A
no-response auto-close is a DISTINCT terminal state (``closed_no_response``) so
silence is never mistaken for a confirmed success when calibrating the gate.
"""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.constants import AgentEventType, TicketStatus
from app.core.ids import new_event_id, utcnow
from app.core.logging import get_logger
from app.db.models import AgentEvent, Ticket
from app.repositories.agent_repository import AgentRepository
from app.repositories.scheduler_repository import SchedulerRepository
from app.repositories.ticket_repository import TicketRepository
from app.services.notification_service import EventBus, get_event_bus

logger = get_logger(__name__)

_POSITIVE = {
    "yes", "yep", "yeah", "works", "working", "fixed", "resolved", "solved",
    "great", "thanks", "thank", "ok", "okay", "good", "perfect", "sorted",
}
_NEGATIVE = {
    "no", "not", "still", "broken", "again", "nope", "worse", "fail",
    "failed", "failing", "doesn't", "won't", "isn't", "can't", "cannot", "negative",
}

FOLLOWUP_QUESTION = (
    "Quick follow-up on your earlier ticket: is everything working now? "
    "Please reply YES if it's resolved, or NO if you're still having trouble."
)


class FollowupService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.tickets = TicketRepository(session)
        self.agents = AgentRepository(session)
        self.scheduler = SchedulerRepository(session)
        self.bus = event_bus or get_event_bus()

    # ---- scheduling ----
    async def schedule(self, ticket_id: str, run_id: str | None) -> None:
        run_at = utcnow() + timedelta(seconds=self.settings.followup_delay_seconds)
        await self.scheduler.create_job(
            kind="followup",
            ticket_id=ticket_id,
            run_at=run_at,
            idempotency_key=f"followup:{ticket_id}:{run_id or 'na'}",
            payload={"run_id": run_id},
        )
        logger.info("followup_scheduled", ticket_id=ticket_id, run_at=run_at.isoformat())

    # ---- execution (called by the scheduler worker) ----
    async def run_followup_check(self, ticket_id: str) -> None:
        ticket = await self.tickets.get(ticket_id)
        if ticket is None or ticket.status not in (
            TicketStatus.RESOLVED.value,
            TicketStatus.FOLLOW_UP_PENDING.value,
        ):
            return  # ticket moved on (reopened/closed) — nothing to do
        ticket.status = TicketStatus.FOLLOW_UP_PENDING.value
        await self.tickets.add_message(
            ticket_id=ticket_id, role="agent", body=FOLLOWUP_QUESTION, author="agent"
        )
        await self._emit(ticket_id, AgentEventType.AWAITING, {"awaiting": "followup_reply"})

        # schedule the no-response timeout
        run_at = utcnow() + timedelta(seconds=self.settings.followup_no_response_timeout_seconds)
        await self.scheduler.create_job(
            kind="followup_timeout",
            ticket_id=ticket_id,
            run_at=run_at,
            idempotency_key=f"followup_timeout:{ticket_id}",
            payload={},
        )
        await self.session.flush()

    async def run_no_response_timeout(self, ticket_id: str) -> None:
        ticket = await self.tickets.get(ticket_id)
        if ticket is None or ticket.status != TicketStatus.FOLLOW_UP_PENDING.value:
            return
        ticket.status = TicketStatus.CLOSED_NO_RESPONSE.value
        ticket.closed_at = utcnow()
        await self._emit(ticket_id, AgentEventType.STATE_CHANGE, {"status": ticket.status})
        await self.session.flush()
        logger.info("followup_no_response_closed", ticket_id=ticket_id)

    # ---- reply handling ----
    @staticmethod
    def classify_reply(text: str) -> str:
        # Word-level matching (substring matching would catch "no" inside "now").
        tokens = set(re.findall(r"[a-z']+", (text or "").lower()))
        neg = bool(tokens & _NEGATIVE)
        pos = bool(tokens & _POSITIVE)
        if neg:
            return "negative"  # err on the side of not-resolved
        if pos:
            return "positive"
        return "unclear"

    async def apply_positive(self, ticket: Ticket) -> None:
        ticket.status = TicketStatus.CLOSED.value
        ticket.closed_at = utcnow()
        await self.scheduler.cancel_for_ticket(ticket.id, kind="followup_timeout")
        await self.tickets.add_message(
            ticket_id=ticket.id,
            role="agent",
            body="Glad it's working. I've closed this ticket — reach out anytime!",
            author="agent",
        )
        await self._emit(ticket.id, AgentEventType.STATE_CHANGE, {"status": ticket.status})
        await self.session.flush()

    async def apply_negative(self, ticket: Ticket) -> None:
        """Mark for reopen; the caller re-runs the agent."""
        ticket.status = TicketStatus.REOPENED.value
        ticket.attempt += 1
        await self.scheduler.cancel_for_ticket(ticket.id, kind="followup_timeout")
        await self._emit(ticket.id, AgentEventType.STATE_CHANGE, {"status": ticket.status})
        await self.session.flush()

    async def _emit(self, ticket_id: str, event_type: AgentEventType, data: dict) -> None:
        seq = await self.agents.next_seq(ticket_id)
        event = AgentEvent(
            id=new_event_id(), ticket_id=ticket_id, run_id=None, seq=seq,
            type=event_type.value, data=data,
        )
        await self.agents.add_event(event)
        await self.bus.publish(ticket_id, {"id": event.id, "seq": seq, "type": event_type.value, "data": data})
