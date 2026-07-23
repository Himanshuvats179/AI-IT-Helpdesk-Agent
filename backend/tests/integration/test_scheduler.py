"""Scheduler worker: due jobs are claimed, dispatched, and marked done.

Regression guard: the dispatch must re-load the job in its own session, else the
detached job stays 'running', its lease expires, and the follow-up re-fires.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.models import ScheduledJob
from app.db.session import session_scope
from app.workers.scheduler import SchedulerWorker
from tests.conftest import create_ticket, get_ticket
from tests.fakes.fake_llm import FakeLLM, finalize_call


async def _resolve_ticket(make_runner):
    ticket_id = await create_ticket("My VPN won't connect.")
    fake = FakeLLM(
        perception={"primary_category": "vpn", "urgency": "medium", "impact": "individual",
                    "summary": "vpn", "confidence": 0.92},
        script=[[("search_kb", {"query": "vpn"})], [finalize_call(cited=["KB-0003"], answer="fix")]],
    )
    runner = make_runner(fake)
    await runner.run(ticket_id, "intake")
    return ticket_id, runner


async def test_scheduler_dispatches_followup_and_marks_done(make_runner):
    ticket_id, runner = await _resolve_ticket(make_runner)
    assert (await get_ticket(ticket_id)).status == "resolved"

    worker = SchedulerWorker(runner)
    await asyncio.sleep(1.1)  # FOLLOWUP_DELAY_SECONDS=1 in tests
    await worker._tick()

    async with session_scope() as session:
        jobs = (
            await session.scalars(
                select(ScheduledJob).where(
                    ScheduledJob.ticket_id == ticket_id, ScheduledJob.kind == "followup"
                )
            )
        ).all()
    assert jobs, "a follow-up job should have been scheduled"
    assert all(j.status == "done" for j in jobs), "job must be completed, not left running"
    assert (await get_ticket(ticket_id)).status == "follow_up_pending"
