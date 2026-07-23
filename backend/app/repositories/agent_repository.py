"""Agent run, tool-call and event persistence (the audit trail)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.ids import utcnow
from app.db.models import AgentEvent, AgentRun, ToolCall
from app.repositories.base import BaseRepository


class AgentRepository(BaseRepository):
    # ---- runs ----
    async def create_run(self, run: AgentRun) -> AgentRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_run(self, run_id: str) -> AgentRun | None:
        return await self.session.get(AgentRun, run_id)

    async def list_runs(self, ticket_id: str) -> list[AgentRun]:
        # Eager-load tool_calls to avoid an N+1 when rendering run history.
        stmt = (
            select(AgentRun)
            .where(AgentRun.ticket_id == ticket_id)
            .order_by(AgentRun.created_at)
            .options(selectinload(AgentRun.tool_calls))
        )
        return list((await self.session.scalars(stmt)).all())

    async def finish_run(
        self,
        run: AgentRun,
        *,
        status: str,
        outcome: str | None = None,
        final_confidence: float | None = None,
        error: str | None = None,
    ) -> None:
        run.status = status
        run.outcome = outcome
        run.final_confidence = final_confidence
        run.error = error
        run.finished_at = utcnow()
        await self.session.flush()

    # ---- tool calls ----
    async def add_tool_call(self, tool_call: ToolCall) -> ToolCall:
        self.session.add(tool_call)
        await self.session.flush()
        return tool_call

    async def get_tool_call_by_idempotency_key(self, key: str) -> ToolCall | None:
        stmt = select(ToolCall).where(ToolCall.idempotency_key == key).limit(1)
        return await self.session.scalar(stmt)

    async def list_tool_calls(self, run_id: str) -> list[ToolCall]:
        stmt = select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.created_at)
        return list((await self.session.scalars(stmt)).all())

    async def list_tool_calls_for_ticket(self, ticket_id: str) -> list[ToolCall]:
        stmt = (
            select(ToolCall)
            .where(ToolCall.ticket_id == ticket_id)
            .order_by(ToolCall.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    # ---- events ----
    async def next_seq(self, ticket_id: str) -> int:
        stmt = select(func.max(AgentEvent.seq)).where(AgentEvent.ticket_id == ticket_id)
        current = await self.session.scalar(stmt)
        return int(current or 0) + 1

    async def add_event(self, event: AgentEvent) -> AgentEvent:
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_events(self, ticket_id: str, after_seq: int = 0) -> list[AgentEvent]:
        stmt = (
            select(AgentEvent)
            .where(AgentEvent.ticket_id == ticket_id, AgentEvent.seq > after_seq)
            .order_by(AgentEvent.seq)
        )
        return list((await self.session.scalars(stmt)).all())
