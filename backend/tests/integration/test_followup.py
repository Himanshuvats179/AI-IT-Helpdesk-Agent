"""The proactive follow-up loop: positive/negative/no-response paths."""
from __future__ import annotations

import asyncio

from app.db.session import session_scope
from app.services.followup_service import FollowupService
from tests.conftest import create_ticket, get_ticket
from tests.fakes.fake_llm import FakeLLM, finalize_call


async def _resolve_vpn_ticket(make_runner) -> str:
    ticket_id = await create_ticket("My VPN won't connect.")
    fake = FakeLLM(
        perception={"primary_category": "vpn", "urgency": "medium", "impact": "individual",
                    "summary": "vpn issue", "confidence": 0.92},
        script=[
            [("search_kb", {"query": "vpn"})],
            [finalize_call(cited=["KB-0003"], answer="Re-import the VPN profile.")],
        ],
    )
    runner = make_runner(fake)
    await runner.run(ticket_id, "intake")
    assert (await get_ticket(ticket_id)).status == "resolved"
    return ticket_id


async def _trigger_followup(ticket_id: str):
    async with session_scope() as session:
        await FollowupService(session).run_followup_check(ticket_id)
        await session.commit()


async def test_followup_positive_closes(make_runner):
    ticket_id = await _resolve_vpn_ticket(make_runner)
    await _trigger_followup(ticket_id)
    assert (await get_ticket(ticket_id)).status == "follow_up_pending"

    runner = make_runner(FakeLLM())
    result = await runner.handle_user_message(ticket_id, "Yes, it's working now, thanks!")
    assert result["status"] == "closed"
    assert (await get_ticket(ticket_id)).status == "closed"


async def test_followup_negative_reopens(make_runner):
    ticket_id = await _resolve_vpn_ticket(make_runner)
    await _trigger_followup(ticket_id)

    runner = make_runner(FakeLLM())
    result = await runner.handle_user_message(ticket_id, "No, it's still broken.")
    assert result["status"] == "reopened"
    # the reopen run leaves follow_up_pending (it re-enters the agent)
    assert (await get_ticket(ticket_id)).status != "follow_up_pending"
    # drain the background reopen run
    pending = [t for t in list(runner._tasks) if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def test_followup_no_response_closes_distinctly(make_runner):
    ticket_id = await _resolve_vpn_ticket(make_runner)
    await _trigger_followup(ticket_id)
    async with session_scope() as session:
        await FollowupService(session).run_no_response_timeout(ticket_id)
        await session.commit()
    assert (await get_ticket(ticket_id)).status == "closed_no_response"
