"""Tool execution + executor (policy, idempotency, denials) against a real DB."""
from __future__ import annotations

from app.config import get_settings
from app.db.models import AgentRun
from app.db.session import session_scope
from app.repositories.agent_repository import AgentRepository
from app.services.kb_service import KBService
from app.services.ticket_service import TicketService
from app.services.verification_service import VerificationService
from app.tools.account_tools import ResetPasswordTool
from app.tools.backends import default_backends
from app.tools.base import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.readonly_tools import CheckAccountStatusTool, SearchKBTool
from app.tools.registry import build_default_registry


async def _noop_emit(*_args, **_kwargs):
    return None


async def _make_ticket(session, body="My VPN won't connect.", requester="demo.user@corp.com"):
    ticket, _ = await TicketService(session).create_ticket(body=body, requester_upn=requester)
    await session.flush()
    return ticket


def _ctx(session, retriever, ticket, run_id="run_test"):
    return ToolContext(
        session=session,
        ticket=ticket,
        run_id=run_id,
        attempt=1,
        settings=get_settings(),
        kb_service=KBService(session, retriever),
        verification_service=VerificationService(session),
        backends=default_backends(),
        emit=_noop_emit,
    )


async def test_search_kb_tool_updates_grounding(seeded):
    async with session_scope() as session:
        ticket = await _make_ticket(session)
        ctx = _ctx(session, seeded, ticket)
        result = await SearchKBTool().execute({"query": "vpn won't connect", "category": "vpn"}, ctx)
        assert result.content["hits"]
        assert "KB-0003" in ctx.retrieved_ids


async def test_check_account_status_defaults_to_requester(seeded):
    async with session_scope() as session:
        ticket = await _make_ticket(session)
        ctx = _ctx(session, seeded, ticket)
        result = await CheckAccountStatusTool().execute({}, ctx)
        assert result.content["subject"] == "demo.user@corp.com"
        assert "locked" in result.content


async def test_reset_password_consumes_verification_token(seeded):
    async with session_scope() as session:
        ticket = await _make_ticket(session, body="forgot my password")
        vs = VerificationService(session)
        await vs.create_challenge(ticket_id=ticket.id, subject="demo.user@corp.com")
        await vs.verify(ticket_id=ticket.id, code="123456")
        ctx = _ctx(session, seeded, ticket)
        ctx.target_subject = "demo.user@corp.com"
        result = await ResetPasswordTool().execute({}, ctx)
        assert result.content["status"] == "reset"
        # token is single-use: now consumed
        assert await vs.get_valid_token(ticket_id=ticket.id, subject="demo.user@corp.com") is None


async def test_executor_idempotency(seeded):
    async with session_scope() as session:
        ticket = await _make_ticket(session)
        run = AgentRun(ticket_id=ticket.id, attempt=1, trigger="intake", status="running")
        await AgentRepository(session).create_run(run)
        await session.flush()
        ctx = _ctx(session, seeded, ticket, run_id=run.id)
        executor = ToolExecutor(build_default_registry(), session)

        r1 = await executor.execute(name="check_account_status", tool_use_id="dup", args={}, ctx=ctx)
        r2 = await executor.execute(name="check_account_status", tool_use_id="dup", args={}, ctx=ctx)
        assert r1.content == r2.content
        calls = await AgentRepository(session).list_tool_calls(run.id)
        assert len(calls) == 1  # replayed, not re-recorded


async def test_executor_blocks_privileged_reset(seeded):
    async with session_scope() as session:
        ticket = await _make_ticket(session)
        run = AgentRun(ticket_id=ticket.id, attempt=1, trigger="intake", status="running")
        await AgentRepository(session).create_run(run)
        await session.flush()
        ctx = _ctx(session, seeded, ticket, run_id=run.id)
        executor = ToolExecutor(build_default_registry(), session)
        result = await executor.execute(
            name="reset_ad_password", tool_use_id="t1", args={"username": "admin@corp.com"}, ctx=ctx
        )
        assert result.is_error
        assert result.content.get("status") == "denied"


async def test_executor_requires_verification_for_self_reset(seeded):
    async with session_scope() as session:
        ticket = await _make_ticket(session)
        run = AgentRun(ticket_id=ticket.id, attempt=1, trigger="intake", status="running")
        await AgentRepository(session).create_run(run)
        await session.flush()
        ctx = _ctx(session, seeded, ticket, run_id=run.id)
        executor = ToolExecutor(build_default_registry(), session)
        result = await executor.execute(name="reset_ad_password", tool_use_id="t2", args={}, ctx=ctx)
        assert result.content.get("status") == "verification_required"


async def test_executor_blocks_privileged_unlock(seeded):
    # unlock_account is CONFIDENCE_GATED, but the privileged-account guard still applies.
    async with session_scope() as session:
        ticket = await _make_ticket(session)
        run = AgentRun(ticket_id=ticket.id, attempt=1, trigger="intake", status="running")
        await AgentRepository(session).create_run(run)
        await session.flush()
        ctx = _ctx(session, seeded, ticket, run_id=run.id)
        executor = ToolExecutor(build_default_registry(), session)
        result = await executor.execute(
            name="unlock_account", tool_use_id="t3", args={"username": "admin@corp.com"}, ctx=ctx
        )
        assert result.is_error
        assert result.content.get("status") == "denied"


async def test_grant_access_ignores_attacker_subject(seeded):
    from app.tools.account_tools import GrantAccessTool

    async with session_scope() as session:
        ticket = await _make_ticket(session, requester="demo.user@corp.com")
        ctx = _ctx(session, seeded, ticket)
        result = await GrantAccessTool().execute(
            {"resource_id": "team-share", "subject": "ceo@corp.com"}, ctx
        )
        # subject is forced to the requester, never the attacker-supplied value
        assert result.content["subject"] == "demo.user@corp.com"
