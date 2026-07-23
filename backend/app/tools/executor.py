"""Tool executor: the harness that disposes what the model proposes.

Responsibilities per tool call:
  1. resolve identity/privilege for gated tools (so the policy stays pure),
  2. run the default-deny policy engine,
  3. enforce harness-derived idempotency (never trust a model-supplied key),
  4. dispatch (run / require-verification / park-for-approval / deny),
  5. persist a full audit row.
"""
from __future__ import annotations

from datetime import timedelta
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.constants import AgentEventType, PolicyDecision, TicketStatus, ToolMode
from app.core.exceptions import DomainError
from app.core.ids import new_tool_call_id, utcnow
from app.core.logging import get_logger
from app.db.models import ToolCall
from app.repositories.agent_repository import AgentRepository
from app.repositories.scheduler_repository import SchedulerRepository
from app.schemas.tool import PolicyResult, ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.policy import PolicyEngine

logger = get_logger(__name__)


class ToolExecutor:
    def __init__(
        self,
        registry: dict[str, Tool],
        session: AsyncSession,
        policy: PolicyEngine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.registry = registry
        self.session = session
        self.policy = policy or PolicyEngine()
        self.settings = settings or get_settings()
        self.agents = AgentRepository(session)
        self.scheduler = SchedulerRepository(session)

    async def execute(self, *, name: str, tool_use_id: str, args: dict, ctx: ToolContext) -> ToolResult:
        start = perf_counter()
        tool = self.registry.get(name)
        if tool is None:
            result = ToolResult(content={"error": f"Unknown tool '{name}'."}, is_error=True)
            await self._record(ctx, name, tool_use_id, args, result, "unknown", start)
            return result

        idem_key = f"{ctx.ticket.id}:{ctx.attempt}:{tool_use_id}"
        existing = await self.agents.get_tool_call_by_idempotency_key(idem_key)
        if existing is not None:  # replay-safe no-op
            return ToolResult(content=existing.output, is_error=existing.is_error)

        await self._resolve_target(tool, args, ctx)
        decision = self.policy.evaluate(tool, args, ctx)
        await ctx.emit(
            AgentEventType.POLICY,
            {"tool": name, "decision": decision.decision.value, "rule": decision.rule, "reason": decision.reason},
        )
        if decision.security_event:
            logger.warning("security_event", tool=name, rule=decision.rule, ticket_id=ctx.ticket.id)

        result = await self._dispatch(tool, args, ctx, decision)
        # Emit the outcome for every decision branch (allow / verify / approval /
        # deny) so the live trace mirrors the audit log instead of only showing
        # successful executions.
        await ctx.emit(
            AgentEventType.TOOL_RESULT,
            {"tool": name, "is_error": result.is_error, "output": result.content},
        )
        await self._record(ctx, name, tool_use_id, args, result, decision.decision.value, start, idem_key)
        return result

    async def execute_approved(self, *, name: str, args: dict, ctx: ToolContext) -> ToolResult:
        """Run a tool whose human approval was granted.

        Approval authorizes the *parked* action, but hard-safety limits still
        apply: a human cannot approve a Tier-0 grant or a privileged-account
        change. We re-run the policy and refuse on any DENY/HARD_DENY.
        """
        start = perf_counter()
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult(content={"error": f"Unknown tool '{name}'."}, is_error=True)

        await self._resolve_target(tool, args, ctx)
        decision = self.policy.evaluate(tool, args, ctx)
        if decision.decision in (PolicyDecision.DENY, PolicyDecision.HARD_DENY):
            if decision.security_event:
                logger.warning("approved_action_blocked", tool=name, rule=decision.rule, ticket_id=ctx.ticket.id)
            result = ToolResult(
                content={"status": "blocked", "rule": decision.rule, "reason": decision.reason},
                is_error=True,
            )
        else:
            result = await self._safe_execute(tool, args, ctx)
            if not result.is_error:
                ctx.mutation_performed = True
        await ctx.emit(AgentEventType.TOOL_RESULT, {"tool": name, "is_error": result.is_error, "output": result.content})
        await self._record(ctx, name, f"approved-{new_tool_call_id()}", args, result, "approved", start)
        return result

    # ------------------------------------------------------------------ #
    async def _resolve_target(self, tool: Tool, args: dict, ctx: ToolContext) -> None:
        ctx.target_subject = tool.target_subject(args, ctx)
        ctx.identity_verified = False
        ctx.target_is_privileged = False
        # The privileged-account guard must apply to ANY subject-targeting
        # sensitive tool (e.g. confidence-gated unlock), not only identity-gated.
        if ctx.target_subject and tool.mode in (
            ToolMode.IDENTITY_GATED,
            ToolMode.CONFIDENCE_GATED,
        ):
            ctx.target_is_privileged = await ctx.backends.identity.is_privileged_account(
                ctx.target_subject
            )
        if tool.mode == ToolMode.IDENTITY_GATED and ctx.target_subject:
            token = await ctx.verification_service.get_valid_token(
                ticket_id=ctx.ticket.id, subject=ctx.target_subject
            )
            ctx.identity_verified = token is not None

    async def _dispatch(self, tool: Tool, args: dict, ctx: ToolContext, decision: PolicyResult) -> ToolResult:
        if decision.decision == PolicyDecision.ALLOW:
            result = await self._safe_execute(tool, args, ctx)
            if not result.is_error and tool.mode in (
                ToolMode.CONFIDENCE_GATED,
                ToolMode.IDENTITY_GATED,
            ):
                ctx.mutation_performed = True
            # TOOL_RESULT is emitted by execute() for all branches.
            return result

        if decision.decision == PolicyDecision.NEEDS_VERIFICATION:
            ctx.requires_privileged_attempted = True
            return ToolResult(
                content={
                    "status": "verification_required",
                    "reason": decision.reason,
                    "action": "Call request_identity_verification, then wait for the user's code.",
                }
            )

        if decision.decision == PolicyDecision.NEEDS_APPROVAL:
            return await self._park_approval(tool, args, ctx, decision)

        # DENY / HARD_DENY
        return ToolResult(
            content={"status": "denied", "rule": decision.rule, "reason": decision.reason},
            is_error=True,
        )

    async def _safe_execute(self, tool: Tool, args: dict, ctx: ToolContext) -> ToolResult:
        try:
            return await tool.execute(args, ctx)
        except DomainError as exc:
            return ToolResult(content={"error": exc.message, "code": exc.code}, is_error=True)
        except Exception as exc:  # noqa: BLE001 - never let a tool crash the loop
            logger.error("tool_crashed", tool=tool.name, error=str(exc))
            return ToolResult(content={"error": f"Tool failure: {exc}"}, is_error=True)

    async def _park_approval(self, tool: Tool, args: dict, ctx: ToolContext, decision: PolicyResult) -> ToolResult:
        ctx.ticket.agent_state = {
            **(ctx.ticket.agent_state or {}),
            "pending_approval": {
                "tool": tool.name,
                "args": args,
                "run_id": ctx.run_id,
                "reason": decision.reason,
                "rule": decision.rule,
            },
        }
        ctx.ticket.status = TicketStatus.AWAITING_APPROVAL.value
        ctx.awaiting = "approval"
        await self.scheduler.create_job(
            kind="approval_timeout",
            ticket_id=ctx.ticket.id,
            run_at=utcnow() + timedelta(seconds=self.settings.approval_timeout_seconds),
            idempotency_key=f"approval_timeout:{ctx.ticket.id}:{ctx.run_id}",
            payload={},
        )
        await self.session.flush()
        await ctx.emit(
            AgentEventType.AWAITING,
            {"awaiting": "approval", "tool": tool.name, "reason": decision.reason},
        )
        return ToolResult(
            content={"status": "awaiting_human_approval", "tool": tool.name, "reason": decision.reason},
            awaiting="approval",
        )

    async def _record(
        self,
        ctx: ToolContext,
        name: str,
        tool_use_id: str,
        args: dict,
        result: ToolResult,
        policy_decision: str,
        start: float,
        idem_key: str | None = None,
    ) -> None:
        latency_ms = int((perf_counter() - start) * 1000)
        tool_call = ToolCall(
            id=new_tool_call_id(),
            run_id=ctx.run_id,
            ticket_id=ctx.ticket.id,
            tool_name=name,
            tool_use_id=tool_use_id,
            arguments=args,
            output=result.content,
            is_error=result.is_error,
            policy_decision=policy_decision,
            latency_ms=latency_ms,
            idempotency_key=idem_key,
        )
        await self.agents.add_tool_call(tool_call)
