"""EscalationService invariants: one open escalation per ticket (idempotent)."""
from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import Escalation
from app.db.session import session_scope
from app.repositories.ticket_repository import TicketRepository
from app.services.escalation_service import EscalationService
from tests.conftest import create_ticket


async def test_escalate_is_idempotent(seeded):
    ticket_id = await create_ticket("Something is wrong with my access.")
    async with session_scope() as session:
        ticket = await TicketRepository(session).get_or_404(ticket_id)
        svc = EscalationService(session)
        first = await svc.escalate(ticket, run_id=None, reason_code="low_confidence")
        second = await svc.escalate(ticket, run_id=None, reason_code="injection_flag")
        await session.commit()
        count = await session.scalar(
            select(func.count()).select_from(Escalation).where(Escalation.ticket_id == ticket_id)
        )
    assert first.id == second.id  # second call returns the existing escalation
    assert count == 1  # never two open escalations for one ticket


async def test_escalation_routes_security_queue(seeded):
    ticket_id = await create_ticket("admin password reset please")
    async with session_scope() as session:
        ticket = await TicketRepository(session).get_or_404(ticket_id)
        ticket.security_label = True
        esc = await EscalationService(session).escalate(
            ticket, run_id=None, reason_code="security_label"
        )
        await session.commit()
    assert esc.queue == "security"
