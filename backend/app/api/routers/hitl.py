"""Human-in-the-loop: escalations, approvals, and operator overrides."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import AgentRunner
from app.api.deps import get_runner, get_session
from app.core.constants import TicketStatus
from app.core.ids import utcnow
from app.repositories.escalation_repository import EscalationRepository
from app.repositories.ticket_repository import TicketRepository
from app.schemas.escalation import ApprovalDecision, EscalationRead, HitlAction
from app.services.escalation_service import EscalationService

router = APIRouter(prefix="/v1", tags=["hitl"])


@router.get("/escalations", response_model=list[EscalationRead])
async def list_escalations(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[EscalationRead]:
    repo = EscalationRepository(session)
    escalations = await repo.list(status=status_filter, limit=limit, offset=offset)
    return [EscalationRead.model_validate(e) for e in escalations]


@router.get("/tickets/{ticket_id}/escalation", response_model=EscalationRead | None)
async def get_ticket_escalation(
    ticket_id: str, session: AsyncSession = Depends(get_session)
) -> EscalationRead | None:
    repo = EscalationRepository(session)
    escalation = await repo.get_open_for_ticket(ticket_id)
    return EscalationRead.model_validate(escalation) if escalation else None


@router.post("/tickets/{ticket_id}/approve")
async def approve(
    ticket_id: str,
    payload: ApprovalDecision,
    runner: AgentRunner = Depends(get_runner),
) -> dict:
    return await runner.approve(
        ticket_id, approve=payload.approve, operator_id=payload.operator_id, note=payload.note
    )


@router.post("/tickets/{ticket_id}/hitl")
async def operator_override(
    ticket_id: str,
    payload: HitlAction,
    session: AsyncSession = Depends(get_session),
    runner: AgentRunner = Depends(get_runner),
) -> dict:
    action = payload.action.lower()

    # Approvals reuse the runner's authorized-execution path.
    if action in ("approve", "deny"):
        return await runner.approve(
            ticket_id, approve=(action == "approve"), operator_id=payload.operator_id, note=payload.note
        )

    tickets = TicketRepository(session)
    ticket = await tickets.get_or_404(ticket_id)

    if action == "force_escalate":
        await EscalationService(session).escalate(
            ticket, run_id=None, reason_code="user_requested",
            hypothesis=payload.note or "Operator forced escalation.",
        )
        await session.commit()
        return {"status": "escalated", "ticket_status": ticket.status}

    if action == "force_resolve":
        ticket.status = TicketStatus.RESOLVED.value
        ticket.resolved_at = utcnow()
        ticket.resolution = {"answer": payload.message or "Resolved by operator.", "by": payload.operator_id}
        await tickets.add_message(
            ticket_id=ticket_id, role="human",
            body=payload.message or "Resolved by a specialist.", author=payload.operator_id,
        )
        # close out any open escalation
        esc = await EscalationRepository(session).get_open_for_ticket(ticket_id)
        if esc:
            await EscalationRepository(session).resolve(esc, assignee=payload.operator_id)
        await session.commit()
        return {"status": "resolved"}

    if action == "take_over":
        ticket.status = TicketStatus.HUMAN_HANDLING.value
        esc = await EscalationRepository(session).get_open_for_ticket(ticket_id)
        if esc:
            esc.status = "assigned"
            esc.assignee = payload.operator_id
        await tickets.add_message(
            ticket_id=ticket_id, role="human",
            body=payload.note or f"{payload.operator_id} is now handling this ticket.",
            author=payload.operator_id,
        )
        await session.commit()
        return {"status": "human_handling"}

    if action == "reply":
        await tickets.add_message(
            ticket_id=ticket_id, role="human", body=payload.message or "", author=payload.operator_id
        )
        await session.commit()
        return {"status": "replied"}

    return {"status": "unknown_action", "action": action}
