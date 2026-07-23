"""The Act loop: Claude tool-use cycle with full stop_reason handling.

The model must terminate by calling ``finalize_resolution`` (parsed into a
structured object). An ``end_turn`` without it is a protocol violation: one
nudge, then a forced low-confidence escalation by the runner. Safety bounds:
max steps, per-ticket cost ceiling, and checkpoint-before-side-effect (each turn
is committed so a crash resumes cleanly and idempotency keys make tool replay a
no-op).
"""
from __future__ import annotations

from app.config import Settings, get_settings
from app.core.constants import AgentEventType, RunPhase
from app.core.logging import get_logger
from app.db.models import AgentRun
from app.llm.prompts import AGENT_SYSTEM
from app.llm.provider import LLMProvider, TextBlock
from app.repositories.agent_repository import AgentRepository
from app.schemas.agent import RunResult
from app.tools.base import ToolContext
from app.tools.executor import ToolExecutor

logger = get_logger(__name__)


class AgentLoop:
    def __init__(
        self,
        provider: LLMProvider,
        executor: ToolExecutor,
        settings: Settings | None = None,
    ) -> None:
        self.provider = provider
        self.executor = executor
        self.settings = settings or get_settings()

    async def run(
        self,
        *,
        ctx: ToolContext,
        run: AgentRun,
        agents: AgentRepository,
        tools_defs: list[dict],
        context_block: list[dict],
    ) -> RunResult:
        messages: list[dict] = [{"role": "user", "content": context_block}]
        nudged = False
        pause_count = 0
        await ctx.emit(AgentEventType.PHASE, {"phase": RunPhase.ACT.value})

        for step in range(self.settings.agent_max_steps):
            response = await self.provider.create_message(
                system=AGENT_SYSTEM,
                messages=messages,
                tools=tools_defs,
                tool_choice={"type": "auto"},
                model=self.settings.llm_model,
                max_tokens=self.settings.llm_max_tokens,
                temperature=0.0,
            )

            messages.append({"role": "assistant", "content": response.raw_assistant_content})
            run.steps += 1
            run.model = response.model or self.settings.llm_model
            run.input_tokens += response.usage.input_tokens
            run.output_tokens += response.usage.output_tokens
            run.cache_read_tokens += response.usage.cache_read_input_tokens
            run.cost_cents += response.usage.cost_cents(run.model)
            run.transcript = messages
            await agents.session.flush()
            await agents.session.commit()  # checkpoint BEFORE any side effects of next turn

            # surface the model's reasoning text
            for block in response.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    await ctx.emit(AgentEventType.THOUGHT, {"text": block.text.strip()[:1000]})

            # cost ceiling
            if run.cost_cents > self.settings.agent_cost_ceiling_cents:
                logger.warning("cost_ceiling_hit", ticket_id=ctx.ticket.id, cost=run.cost_cents)
                return RunResult(outcome=_cannot(), escalated=True, escalation_reason="budget_exhausted", steps=run.steps)

            stop = response.stop_reason

            if stop == "tool_use":
                tool_results = []
                for tool_use in response.tool_uses():
                    await ctx.emit(
                        AgentEventType.TOOL_CALL,
                        {"tool": tool_use.name, "args": tool_use.input},
                    )
                    result = await self.executor.execute(
                        name=tool_use.name, tool_use_id=tool_use.id, args=tool_use.input, ctx=ctx
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result.as_tool_content(),
                            "is_error": result.is_error,
                        }
                    )

                if ctx.finalize is not None:
                    return RunResult(
                        outcome=ctx.finalize.outcome,
                        finalize=ctx.finalize,
                        escalated=ctx.escalation_requested is not None,
                        escalation_reason=ctx.escalation_requested,
                        steps=run.steps,
                    )
                if ctx.awaiting is not None:
                    return RunResult(outcome=_needs_user(), awaiting=ctx.awaiting, steps=run.steps)

                messages.append({"role": "user", "content": tool_results})
                continue

            if stop == "pause_turn":
                # The model yielded mid-turn (e.g. server-side tool); resume with
                # the same history. Guard against an infinite no-progress spin.
                pause_count += 1
                if pause_count > 3:
                    # A no-progress pause spin, not a cost/step budget overrun —
                    # using a distinct reason keeps the confidence calibration and
                    # the operator-facing handover accurate.
                    return RunResult(
                        outcome=_cannot(), escalated=True,
                        escalation_reason="pause_spin", steps=run.steps,
                    )
                continue

            if stop == "max_tokens":
                messages.append(
                    {"role": "user", "content": "Continue. Emit finalize_resolution when done."}
                )
                continue

            if stop in ("end_turn", "refusal", "stop_sequence"):
                if ctx.finalize is not None:
                    return RunResult(outcome=ctx.finalize.outcome, finalize=ctx.finalize, steps=run.steps)
                if not nudged:
                    nudged = True
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "You ended without finishing. You MUST call finalize_resolution "
                                "exactly once (or escalate_to_human then finalize_resolution)."
                            ),
                        }
                    )
                    continue
                return RunResult(outcome=_cannot(), protocol_violation=True, steps=run.steps)

            # unknown stop reason — be safe
            return RunResult(outcome=_cannot(), protocol_violation=True, steps=run.steps)

        # step budget exhausted
        return RunResult(outcome=_cannot(), escalated=True, escalation_reason="budget_exhausted", steps=run.steps)


# small helpers to avoid importing Outcome everywhere
def _cannot():
    from app.core.constants import Outcome

    return Outcome.CANNOT_RESOLVE


def _needs_user():
    from app.core.constants import Outcome

    return Outcome.NEEDS_USER
