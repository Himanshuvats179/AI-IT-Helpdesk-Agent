"""Control-flow tools: messaging, escalation, and the terminal finalize."""
from __future__ import annotations

from app.core.constants import AgentEventType, Outcome, ToolMode
from app.core.logging import get_logger
from app.schemas.agent import FinalizeResolution, ResolutionEvidence
from app.schemas.tool import ToolResult
from app.tools.base import Tool, ToolContext

logger = get_logger(__name__)


class SendUserMessageTool(Tool):
    name = "send_user_message"
    mode = ToolMode.AUTO_RATE_LIMITED
    description = "Send a message to the user (e.g. ask a clarifying question or share progress)."

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.repositories.ticket_repository import TicketRepository

        ctx.send_message_count += 1
        await TicketRepository(ctx.session).add_message(
            ticket_id=ctx.ticket.id, role="agent", body=args["message"], author="agent"
        )
        await ctx.emit(AgentEventType.THOUGHT, {"message": args["message"]})
        return ToolResult(content={"status": "sent"})


class UpdateTicketTool(Tool):
    name = "update_ticket"
    mode = ToolMode.AUTO
    description = "Record an internal working note on the ticket (not shown to the user)."

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.repositories.ticket_repository import TicketRepository

        await TicketRepository(ctx.session).add_message(
            ticket_id=ctx.ticket.id, role="system", body=args["note"], author="agent"
        )
        return ToolResult(content={"status": "noted"})


class EscalateToHumanTool(Tool):
    name = "escalate_to_human"
    mode = ToolMode.AUTO  # escalation is always permitted (fail-safe direction)
    description = (
        "Escalate to a human engineer with a reason and your current hypothesis + recommended "
        "next steps. After calling this, call finalize_resolution with outcome=cannot_resolve."
    )

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short reason code or phrase."},
                "hypothesis": {"type": ["string", "null"]},
                "recommended_steps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["reason"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        ctx.escalation_requested = args.get("reason") or "agent_requested"
        ctx.escalation_meta = {
            "hypothesis": args.get("hypothesis"),
            "recommended_steps": args.get("recommended_steps", []),
        }
        return ToolResult(
            content={
                "status": "escalation_recorded",
                "next": "Call finalize_resolution with outcome=cannot_resolve.",
            }
        )


class FinalizeResolutionTool(Tool):
    name = "finalize_resolution"
    mode = ToolMode.AUTO
    description = (
        "End the run. Provide an honest model_confidence (0..1), the cited_kb_ids you used, the "
        "applied_steps, structured evidence, and a clear user_facing_answer. Call this exactly once."
    )

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": [o.value for o in Outcome]},
                "model_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "cited_kb_ids": {"type": "array", "items": {"type": "string"}},
                "applied_steps": {"type": "array", "items": {"type": "string"}},
                "evidence": {
                    "type": "object",
                    "properties": {
                        "tools_succeeded": {"type": "array", "items": {"type": "string"}},
                        "tools_failed": {"type": "array", "items": {"type": "string"}},
                        "unmatched_symptoms": {"type": "boolean"},
                        "verification": {"type": ["string", "null"]},
                    },
                },
                "user_facing_answer": {"type": "string"},
                "handover_summary": {"type": ["string", "null"]},
            },
            "required": ["outcome", "model_confidence", "user_facing_answer"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        if ctx.finalize is not None:
            # Enforce the "call exactly once" contract: a second call would
            # silently overwrite the first finalization.
            return ToolResult(
                content={"error": "finalize_resolution was already called; ignoring."},
                is_error=True,
            )
        ctx.finalize = self._parse(args)
        return ToolResult(content={"status": "finalized"}, terminal=True)

    @staticmethod
    def _parse(args: dict) -> FinalizeResolution:
        try:
            return FinalizeResolution.model_validate(args)
        except Exception:  # noqa: BLE001 - be tolerant of imperfect model output
            evidence = args.get("evidence") or {}
            return FinalizeResolution(
                outcome=_safe_outcome(args.get("outcome")),
                model_confidence=float(args.get("model_confidence", 0.3) or 0.3),
                cited_kb_ids=list(args.get("cited_kb_ids", []) or []),
                applied_steps=list(args.get("applied_steps", []) or []),
                evidence=ResolutionEvidence(
                    tools_succeeded=list(evidence.get("tools_succeeded", []) or []),
                    tools_failed=list(evidence.get("tools_failed", []) or []),
                    unmatched_symptoms=bool(evidence.get("unmatched_symptoms", False)),
                ),
                user_facing_answer=str(args.get("user_facing_answer", ""))[:8000],
                handover_summary=(str(hs)[:8000] if (hs := args.get("handover_summary")) else None),
            )


def _safe_outcome(value) -> Outcome:
    try:
        return Outcome(value)
    except (ValueError, TypeError):
        return Outcome.CANNOT_RESOLVE
