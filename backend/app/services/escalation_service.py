"""Escalation service: build the pre-filled human handover and route it.

The handover is structured and immutable. The tool-call trace is taken from our
own audit log (never re-summarized by the model), and both the model's raw
self-confidence and the calibrated confidence are recorded so a human can see
exactly where the agent was over/under-confident.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state_machine import can_transition
from app.core.constants import Category, Priority, TicketStatus
from app.core.ids import utcnow
from app.core.logging import get_logger
from app.db.models import Escalation, Ticket
from app.repositories.agent_repository import AgentRepository
from app.repositories.escalation_repository import EscalationRepository
from app.repositories.ticket_repository import TicketRepository
from app.schemas.agent import ConfidenceDecision
from app.schemas.escalation import HandoverPackage
from app.schemas.kb import RetrievalResult

logger = get_logger(__name__)

_REASON_TEXT = {
    "low_confidence": "Calibrated confidence fell below the auto-resolution threshold.",
    "no_good_kb_match": "No knowledge-base article matched the issue; refused to improvise a fix.",
    "privileged_action_unverified": "A privileged action was required but identity was not verified.",
    "injection_flag": "Prompt-injection was detected in the request.",
    "security_label": "Request touches privileged/security-sensitive scope.",
    "repeated_tool_failure": "A required tool failed repeatedly.",
    "oscillation_detected": "The agent oscillated without making progress.",
    "budget_exhausted": "The agent exhausted its step/cost budget.",
    "pause_spin": "The agent stalled on repeated pause-turns without making progress.",
    "needs_approval": "An action requires explicit human approval.",
    "protocol_violation": "The agent ended without a valid finalize_resolution.",
    "agent_error": "An internal error occurred while resolving the ticket.",
    "user_requested": "The user explicitly asked for a human.",
}

_QUEUE_BY_CATEGORY = {
    Category.ACCESS_REQUEST: "identity-access",
    Category.PASSWORD_RESET: "identity-access",
    Category.ACCOUNT_LOCKOUT: "identity-access",
    Category.MFA: "identity-access",
    Category.VPN: "network-ops",
    Category.NETWORK: "network-ops",
    Category.EMAIL: "messaging",
    Category.HARDWARE_DIAG: "deskside",
    Category.PRINTER: "deskside",
    Category.SOFTWARE_INSTALL: "endpoint",
    Category.PERFORMANCE: "endpoint",
}


def route_queue(category: str | None, security_label: bool, priority: str | None) -> str:
    if security_label:
        return "security"
    if priority == Priority.P1.value:
        return "major-incident"
    try:
        return _QUEUE_BY_CATEGORY.get(Category(category), "tier2-triage")
    except (ValueError, TypeError):
        return "tier2-triage"


class EscalationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tickets = TicketRepository(session)
        self.agents = AgentRepository(session)
        self.repo = EscalationRepository(session)

    async def escalate(
        self,
        ticket: Ticket,
        *,
        run_id: str | None,
        reason_code: str,
        decision: ConfidenceDecision | None = None,
        retrieval: RetrievalResult | None = None,
        hypothesis: str | None = None,
        recommended_steps: list[str] | None = None,
    ) -> Escalation:
        existing = await self.repo.get_open_for_ticket(ticket.id)
        if existing is not None:
            return existing  # idempotent: never double-escalate

        messages = await self.tickets.list_messages(ticket.id)
        conversation = [
            {
                "role": m.role,
                "author": m.author,
                "body": m.body,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]

        tool_calls = await self.agents.list_tool_calls_for_ticket(ticket.id)
        tool_trace = [
            {
                "tool": tc.tool_name,
                "arguments": tc.arguments,
                "is_error": tc.is_error,
                "policy": tc.policy_decision,
                "output": tc.output,
            }
            for tc in tool_calls
        ]

        considered = list(retrieval.cited_ids()) if retrieval else []
        rec_steps = list(recommended_steps or [])
        if retrieval and not rec_steps:
            for hit in retrieval.hits[:1]:
                rec_steps.extend(
                    s.get("text", "") if isinstance(s, dict) else str(s) for s in hit.steps
                )

        package = HandoverPackage(
            ticket_id=ticket.id,
            why_escalated=_REASON_TEXT.get(reason_code, reason_code),
            reason_code=reason_code,
            category=ticket.category,
            priority=ticket.priority,
            model_self_confidence=decision.model_confidence if decision else ticket.model_confidence,
            calibrated_confidence=decision.calibrated_confidence if decision else ticket.confidence,
            structured_summary=ticket.subject,
            current_hypothesis=hypothesis,
            recommended_next_steps=[s for s in rec_steps if s],
            kb_articles_considered=considered,
            tool_call_trace=tool_trace,
            entities=ticket.entities or {},
            conversation=conversation,
        )

        queue = route_queue(ticket.category, ticket.security_label, ticket.priority)
        escalation = Escalation(
            ticket_id=ticket.id,
            run_id=run_id,
            reason=reason_code,
            queue=queue,
            model_self_confidence=package.model_self_confidence,
            calibrated_confidence=package.calibrated_confidence,
            payload=package.model_dump(),
            status="open",
        )
        await self.repo.create(escalation)

        # Honor the state machine: never resurrect a closed ticket into ESCALATED.
        # The escalation record is still kept for audit even if status is unchanged.
        current = TicketStatus(ticket.status)
        if can_transition(current, TicketStatus.ESCALATED):
            ticket.status = TicketStatus.ESCALATED.value
            ticket.updated_at = utcnow()
        else:
            logger.warning(
                "escalation_status_unchanged",
                ticket_id=ticket.id, current=current.value, reason=reason_code,
            )
        await self.session.flush()

        logger.info(
            "ticket_escalated",
            ticket_id=ticket.id,
            queue=queue,
            reason=reason_code,
            calibrated=package.calibrated_confidence,
        )
        return escalation
