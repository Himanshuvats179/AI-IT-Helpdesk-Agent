"""Ticket intake, listing, detail, and run history."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import AgentRunner
from app.api.deps import get_runner, get_session
from app.repositories.agent_repository import AgentRepository
from app.repositories.ticket_repository import TicketRepository
from app.schemas.agent import AgentRunRead, ToolCallRead
from app.schemas.common import Page
from app.schemas.ticket import IntakeResponse, TicketCreate, TicketDetail, TicketRead, MessageRead
from app.services.ticket_service import TicketService

router = APIRouter(prefix="/v1/tickets", tags=["tickets"])


@router.post("", response_model=IntakeResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_ticket(
    payload: TicketCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
    runner: AgentRunner = Depends(get_runner),
) -> IntakeResponse:
    service = TicketService(session)
    ticket, duplicate_of = await service.create_ticket(
        body=payload.body,
        subject=payload.subject,
        requester_upn=payload.requester_upn,
        channel=payload.channel,
    )
    # Commit before scheduling the background run so the worker session sees it.
    await session.commit()

    if duplicate_of is None:
        runner.schedule(ticket.id, "intake")
        return IntakeResponse(ticket_id=ticket.id, run_id=None, status="processing")

    response.status_code = status.HTTP_200_OK
    return IntakeResponse(
        ticket_id=ticket.id, run_id=None, status="duplicate", duplicate_of=duplicate_of
    )


@router.get("", response_model=Page[TicketRead])
async def list_tickets(
    requester: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Page[TicketRead]:
    repo = TicketRepository(session)
    items, total = await repo.list(
        requester_upn=requester, status=status_filter, limit=limit, offset=offset
    )
    return Page[TicketRead](
        items=[TicketRead.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(
    ticket_id: str, session: AsyncSession = Depends(get_session)
) -> TicketDetail:
    repo = TicketRepository(session)
    ticket = await repo.get_or_404(ticket_id)
    messages = await repo.list_messages(ticket_id)
    base = TicketRead.model_validate(ticket).model_dump()
    return TicketDetail(**base, messages=[MessageRead.model_validate(m) for m in messages])


@router.get("/{ticket_id}/runs", response_model=list[AgentRunRead])
async def get_runs(
    ticket_id: str, session: AsyncSession = Depends(get_session)
) -> list[AgentRunRead]:
    repo = TicketRepository(session)
    await repo.get_or_404(ticket_id)
    agents = AgentRepository(session)
    runs = await agents.list_runs(ticket_id)
    out: list[AgentRunRead] = []
    for run in runs:
        tool_calls = run.tool_calls  # eager-loaded (selectinload) — no extra query
        out.append(
            AgentRunRead(
                id=run.id,
                ticket_id=run.ticket_id,
                attempt=run.attempt,
                trigger=run.trigger,
                status=run.status,
                model=run.model,
                steps=run.steps,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                cost_cents=run.cost_cents,
                outcome=run.outcome,
                final_confidence=run.final_confidence,
                error=run.error,
                created_at=run.created_at,
                finished_at=run.finished_at,
                tool_calls=[ToolCallRead.model_validate(tc) for tc in tool_calls],
            )
        )
    return out
