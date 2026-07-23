"""Durable scheduler worker.

Polls ``scheduled_jobs`` for due timers (follow-ups, approval timeouts), claims
them exactly-once via the repository's conditional-update lease, and dispatches
them. Runs as an asyncio task inside the app process (single mechanism; would be
a separate process backed by the same table in production).
"""
from __future__ import annotations

import asyncio

from app.config import Settings, get_settings
from app.core.constants import TicketStatus
from app.core.ids import new_run_id
from app.core.logging import get_logger
from app.db.models import ScheduledJob
from app.db.session import session_scope
from app.repositories.scheduler_repository import SchedulerRepository
from app.repositories.ticket_repository import TicketRepository
from app.services.followup_service import FollowupService

logger = get_logger(__name__)


class SchedulerWorker:
    def __init__(self, runner, settings: Settings | None = None) -> None:
        self.runner = runner
        self.settings = settings or get_settings()
        self.owner = new_run_id()  # unique lease owner id for this worker
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("scheduler_started", owner=self.owner, poll=self.settings.scheduler_poll_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 - never let the poller die
                logger.exception("scheduler_tick_error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.scheduler_poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        # Independent transactions: a claim failure must not undo lease reclaim.
        async with session_scope() as session:
            await SchedulerRepository(session).reclaim_expired_leases()
        async with session_scope() as session:
            jobs = await SchedulerRepository(session).claim_due(owner=self.owner, limit=10)

        for job in jobs:
            await self._dispatch(job)

    async def _dispatch(self, job: ScheduledJob) -> None:
        kind, ticket_id, job_id = job.kind, job.ticket_id, job.id
        try:
            async with session_scope() as session:
                # Re-fetch the job in THIS session — the claimed object is detached,
                # so mutating it here would not persist (job would expire + re-run).
                fresh = await session.get(ScheduledJob, job_id)
                if fresh is None or fresh.status != "running":
                    return
                followups = FollowupService(session, self.settings, self.runner.bus)
                if kind == "followup":
                    await followups.run_followup_check(ticket_id)
                elif kind == "followup_timeout":
                    await followups.run_no_response_timeout(ticket_id)
                elif kind == "approval_timeout":
                    await self._approval_timeout(session, ticket_id)
                await SchedulerRepository(session).complete(fresh, status="done")
                await session.commit()
            logger.info("job_done", kind=kind, ticket_id=ticket_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_failed", kind=job.kind, ticket_id=job.ticket_id)
            async with session_scope() as session:
                fresh = await session.get(ScheduledJob, job.id)
                if fresh is not None:
                    await SchedulerRepository(session).complete(fresh, status="failed", error=str(exc))
                    await session.commit()

    async def _approval_timeout(self, session, ticket_id: str) -> None:
        """Fail-closed: an unanswered approval escalates; it never auto-executes."""
        tickets = TicketRepository(session)
        ticket = await tickets.get(ticket_id)
        if ticket is None or ticket.status != TicketStatus.AWAITING_APPROVAL.value:
            return
        from app.services.escalation_service import EscalationService

        state = dict(ticket.agent_state or {})
        state.pop("pending_approval", None)
        ticket.agent_state = state
        await EscalationService(session).escalate(
            ticket, run_id=None, reason_code="needs_approval",
            hypothesis="Approval request timed out without a human decision (fail-closed).",
        )
        await tickets.add_message(
            ticket_id=ticket_id, role="agent",
            body="The approval request timed out, so I've routed this to a specialist queue.",
            author="agent",
        )
