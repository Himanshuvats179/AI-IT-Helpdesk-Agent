"""AgentRunner: orchestrates a full Perceive -> Plan -> Act -> Reflect run.

One in-flight run per ticket (in-process lock). Each run owns its own DB session
(worker-style), never the request's. Disposition after the loop is decided by the
single confidence gate + grounding validation here, not by the model.
"""
from __future__ import annotations

import asyncio
import json
import weakref
from datetime import timedelta

from app.config import Settings, get_settings
from app.core.constants import (
    SLA_MINUTES,
    AgentEventType,
    ConfidenceZone,
    Outcome,
    Priority,
    TicketStatus,
    VerificationStatus,
    compute_priority,
)
from app.core.ids import utcnow
from app.core.logging import bind_trace, clear_trace, get_logger
from app.db.models import AgentRun, Ticket, ToolCall
from app.llm.prompts import build_agent_context_block
from app.llm.provider import LLMProvider
from app.repositories.agent_repository import AgentRepository
from app.repositories.ticket_repository import TicketRepository
from app.schemas.agent import RunResult
from app.schemas.perception import PerceptionResult
from app.services.confidence_service import ConfidenceContext, ConfidenceService
from app.services.escalation_service import EscalationService
from app.services.followup_service import FollowupService
from app.services.kb_service import KBService
from app.services.notification_service import EventBus, get_event_bus
from app.services.perception_service import PerceptionService
from app.services.redaction_service import RedactionService
from app.services.retrieval.retriever import HybridRetriever
from app.services.verification_service import VerificationService
from app.agent.events import EventEmitter
from app.agent.loop import AgentLoop
from app.db.session import session_scope
from app.tools.backends import Backends, default_backends
from app.tools.base import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.registry import build_default_registry, tool_definitions

logger = get_logger(__name__)


class AgentRunner:
    def __init__(
        self,
        provider: LLMProvider,
        retriever: HybridRetriever,
        *,
        event_bus: EventBus | None = None,
        backends: Backends | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.provider = provider
        self.retriever = retriever
        self.bus = event_bus or get_event_bus()
        self.backends = backends or default_backends()
        self.settings = settings or get_settings()
        self.registry = build_default_registry()
        self._tool_defs = tool_definitions(self.registry)
        self._tasks: set[asyncio.Task] = set()
        # Weak values: a per-ticket lock lives only while a run holds a strong
        # reference to it, so the map self-prunes instead of growing unbounded.
        self._locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = (
            weakref.WeakValueDictionary()
        )

    # ------------------------------------------------------------------ #
    # Public entry points
    # ------------------------------------------------------------------ #
    def schedule(self, ticket_id: str, trigger: str = "intake") -> asyncio.Task:
        """Fire-and-forget a run as a background task (keeps a strong reference)."""
        task = asyncio.create_task(self.run(ticket_id, trigger))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def run(self, ticket_id: str, trigger: str = "intake") -> str | None:
        lock = self._locks.setdefault(ticket_id, asyncio.Lock())
        async with lock:
            run_id: str | None = None
            try:
                async with session_scope() as session:
                    run_id = await self._execute(session, ticket_id, trigger)
                return run_id
            except Exception as exc:  # noqa: BLE001
                logger.exception("agent_run_failed", ticket_id=ticket_id, error=str(exc))
                await self._fail(ticket_id, run_id, str(exc))
                return run_id
            finally:
                clear_trace()

    # ------------------------------------------------------------------ #
    async def _execute(self, session, ticket_id: str, trigger: str) -> str:
        tickets = TicketRepository(session)
        agents = AgentRepository(session)
        ticket = await tickets.get_or_404(ticket_id)

        ticket.attempt = (ticket.attempt or 0) + 1
        run = AgentRun(
            ticket_id=ticket_id,
            attempt=ticket.attempt,
            trigger=trigger,
            status="running",
            model=self.settings.llm_model,
        )
        await agents.create_run(run)
        run.trace_id = run.id
        await session.commit()
        bind_trace(run.id, ticket_id=ticket_id)

        emitter = EventEmitter(session, ticket_id, run.id, self.bus)
        await emitter.emit(AgentEventType.RUN_STARTED, {"trigger": trigger, "attempt": ticket.attempt})

        # ---- PERCEIVE ----
        await emitter.emit(AgentEventType.PHASE, {"phase": "perceive"})
        user_text = await self._latest_user_text(tickets, ticket_id)
        perception_service = PerceptionService(self.provider, self.settings)
        perception = await perception_service.classify(
            user_text, heuristic_injection=ticket.injection_flag
        )
        self._apply_perception(ticket, perception)
        ticket.status = TicketStatus.IN_PROGRESS.value
        await session.commit()
        await emitter.emit(
            AgentEventType.STATE_CHANGE,
            {"status": ticket.status, "category": ticket.category, "priority": ticket.priority},
        )

        # ---- PLAN (retrieve) ----
        kb = KBService(session, self.retriever)
        query = f"{ticket.subject}\n{user_text}\n{perception.summary}"
        retrieval = await kb.search(query, category=ticket.category)
        await emitter.emit(
            AgentEventType.PHASE,
            {
                "phase": "plan",
                "retrieval": {
                    "confidence": retrieval.confidence,
                    "no_good_match": retrieval.no_good_match,
                    "kb_ids": list(retrieval.cited_ids()),
                },
            },
        )

        # ---- ACT (loop) ----
        verification = VerificationService(session, self.settings)
        identity_verified = (
            await verification.get_valid_token(ticket_id=ticket_id, subject=ticket.requester_upn)
        ) is not None
        messages = await tickets.list_messages(ticket_id)
        conversation = [
            {"role": m.role, "body": m.body} for m in messages if m.role in ("user", "agent")
        ]
        context_block = build_agent_context_block(
            ticket_id=ticket_id,
            requester_upn=ticket.requester_upn,
            category=ticket.category,
            priority=ticket.priority,
            summary=perception.summary,
            entities=ticket.entities or {},
            identity_verified=identity_verified,
            conversation=conversation,
            retrieval=retrieval,
        )

        executor = ToolExecutor(self.registry, session, settings=self.settings)
        ctx = ToolContext(
            session=session,
            ticket=ticket,
            run_id=run.id,
            attempt=ticket.attempt,
            settings=self.settings,
            kb_service=kb,
            verification_service=verification,
            backends=self.backends,
            emit=emitter.emit,
            retrieved_ids=set(retrieval.cited_ids()),
            retrieval=retrieval,
        )
        loop = AgentLoop(self.provider, executor, self.settings)
        result = await loop.run(
            ctx=ctx, run=run, agents=agents, tools_defs=self._tool_defs, context_block=context_block
        )

        # ---- REFLECT / disposition ----
        await emitter.emit(AgentEventType.PHASE, {"phase": "reflect"})
        await self._finalize_run(session, ticket, run, ctx, result, retrieval, emitter)
        return run.id

    # ------------------------------------------------------------------ #
    def _apply_perception(self, ticket: Ticket, perception: PerceptionResult) -> None:
        priority = compute_priority(perception.urgency, perception.impact)
        ticket.category = perception.primary_category.value
        ticket.urgency = perception.urgency.value
        ticket.impact = perception.impact.value
        ticket.priority = priority.value
        ticket.sentiment = perception.sentiment.value
        ticket.language = perception.language or "en"
        ticket.model_confidence = perception.confidence
        ticket.security_label = ticket.security_label or perception.security_label
        ticket.injection_flag = ticket.injection_flag or perception.injection_flag
        entities = perception.entities.model_dump(exclude_none=True)
        merged = {**(ticket.entities or {}), **{k: v for k, v in entities.items() if v}}
        ticket.entities = merged
        ticket.sla_due_at = utcnow() + timedelta(minutes=SLA_MINUTES.get(priority, 240))

    async def _finalize_run(
        self, session, ticket: Ticket, run: AgentRun, ctx: ToolContext, result: RunResult, retrieval, emitter: EventEmitter
    ) -> None:
        agents = AgentRepository(session)
        tickets = TicketRepository(session)
        escalation_service = EscalationService(session)
        confidence = ConfidenceService(self.settings)
        followups = FollowupService(session, self.settings, self.bus)

        # 1) Loop paused awaiting a human/user input — ticket status already set.
        if result.awaiting:
            await agents.finish_run(run, status="finished", outcome="needs_user")
            await emitter.emit(AgentEventType.RUN_FINISHED, {"outcome": "awaiting", "awaiting": result.awaiting})
            await session.commit()
            return

        tool_calls = await agents.list_tool_calls(run.id)
        repeated_failure = self._has_repeated_failure(tool_calls)
        oscillation = self._has_oscillation(tool_calls)
        finalize = result.finalize

        # 2) No valid finalize -> escalate (protocol violation / budget / error).
        if finalize is None:
            reason = result.escalation_reason or (
                "protocol_violation" if result.protocol_violation else "agent_error"
            )
            await self._do_escalate(
                ticket, run, escalation_service, emitter,
                reason_code=reason, retrieval=retrieval, decision=None,
                hypothesis=None, recommended=ctx.escalation_meta.get("recommended_steps"),
            )
            await agents.finish_run(run, status="finished", outcome="cannot_resolve")
            await session.commit()
            return

        # Redact model-generated text before it is persisted and (later) re-fed
        # into the agent context — it must be treated as untrusted just like user
        # input, so it can't smuggle secrets/PII back into the transcript.
        safe_answer = RedactionService().redact(finalize.user_facing_answer)

        # 3) Grounding validation (anti-hallucination).
        hallucinated = bool(set(finalize.cited_kb_ids) - ctx.retrieved_ids)
        extra_reasons = ["hallucinated_citation"] if hallucinated else []
        # If the agent grounded its answer in an actually-retrieved article, trust
        # that grounding over the coarse score gate (whose job is to catch the
        # "answered with NO article at all" case).
        grounded_citation = bool(finalize.cited_kb_ids) and not hallucinated
        effective_no_good_match = retrieval.no_good_match and not grounded_citation

        cctx = ConfidenceContext(
            priority=Priority(ticket.priority) if ticket.priority else None,
            no_good_match=effective_no_good_match,
            injection_flag=ticket.injection_flag,
            security_label=ticket.security_label,
            requires_privileged=ctx.requires_privileged_attempted,
            identity_verified=ctx.identity_verified,
            repeated_failure=repeated_failure,
            oscillation=oscillation,
            budget_exhausted=result.escalation_reason == "budget_exhausted",
            extra_reasons=extra_reasons,
        )
        decision = confidence.calibrate(finalize, cctx)
        ticket.model_confidence = decision.model_confidence
        ticket.confidence = decision.calibrated_confidence
        ticket.confidence_zone = decision.zone.value
        await emitter.emit(
            AgentEventType.CONFIDENCE,
            {
                "model": decision.model_confidence,
                "calibrated": decision.calibrated_confidence,
                "zone": decision.zone.value,
                "reasons": decision.reasons,
            },
        )

        explicit_escalation = ctx.escalation_requested is not None or result.escalated

        # 4) Needs-user clarification (only if not otherwise escalating).
        if (
            finalize.outcome == Outcome.NEEDS_USER
            and not explicit_escalation
            and decision.zone != ConfidenceZone.ESCALATE
        ):
            await tickets.add_message(
                ticket_id=ticket.id, role="agent", body=safe_answer, author="agent"
            )
            ticket.status = TicketStatus.AWAITING_USER.value
            await agents.finish_run(
                run, status="finished", outcome="needs_user", final_confidence=decision.calibrated_confidence
            )
            await emitter.emit(AgentEventType.STATE_CHANGE, {"status": ticket.status})
            await emitter.emit(AgentEventType.RUN_FINISHED, {"outcome": "needs_user"})
            await session.commit()
            return

        # In the verify band, require a passing verification ONLY when the agent
        # actually performed a mutation (a pure informational answer has nothing
        # to re-check, so it shouldn't be escalated for a missing verification).
        verification_ok = finalize.evidence.verification == VerificationStatus.VERIFIED
        needs_verification = (
            decision.zone == ConfidenceZone.ACT_WITH_VERIFICATION
            and ctx.mutation_performed
            and not verification_ok
        )
        must_escalate = (
            explicit_escalation
            or finalize.outcome == Outcome.CANNOT_RESOLVE
            or decision.zone == ConfidenceZone.ESCALATE
            or hallucinated
            or needs_verification
        )

        # 5) Escalate.
        if must_escalate:
            reason_code = self._reason_code(ctx, decision, hallucinated, finalize.outcome)
            hypothesis = (
                ctx.escalation_meta.get("hypothesis")
                or finalize.handover_summary
                or safe_answer
            )
            await self._do_escalate(
                ticket, run, escalation_service, emitter,
                reason_code=reason_code, retrieval=retrieval, decision=decision,
                hypothesis=hypothesis, recommended=ctx.escalation_meta.get("recommended_steps"),
            )
            await tickets.add_message(
                ticket_id=ticket.id,
                role="agent",
                body=(
                    "I couldn't safely resolve this on my own, so I've routed it to a specialist "
                    "who will follow up shortly. Summary of what I found: " + safe_answer
                ),
                author="agent",
            )
            await agents.finish_run(
                run, status="finished", outcome="cannot_resolve", final_confidence=decision.calibrated_confidence
            )
            await session.commit()
            return

        # 6) Resolve.
        await tickets.add_message(
            ticket_id=ticket.id, role="agent", body=safe_answer, author="agent"
        )
        ticket.status = TicketStatus.RESOLVED.value
        ticket.resolved_at = utcnow()
        ticket.resolution = {
            "cited_kb_ids": finalize.cited_kb_ids,
            "applied_steps": finalize.applied_steps,
            "answer": safe_answer,
            "confidence": decision.calibrated_confidence,
        }
        await agents.finish_run(
            run, status="finished", outcome="resolved", final_confidence=decision.calibrated_confidence
        )
        await emitter.emit(AgentEventType.STATE_CHANGE, {"status": "resolved"})
        await emitter.emit(
            AgentEventType.RESOLVED,
            {"confidence": decision.calibrated_confidence, "cited_kb_ids": finalize.cited_kb_ids},
        )
        await followups.schedule(ticket.id, run.id)
        await emitter.emit(AgentEventType.RUN_FINISHED, {"outcome": "resolved"})
        await session.commit()

    async def _do_escalate(
        self, ticket, run, escalation_service, emitter, *, reason_code, retrieval, decision, hypothesis, recommended
    ) -> None:
        escalation = await escalation_service.escalate(
            ticket,
            run_id=run.id,
            reason_code=reason_code,
            decision=decision,
            retrieval=retrieval,
            hypothesis=hypothesis,
            recommended_steps=recommended,
        )
        await emitter.emit(AgentEventType.STATE_CHANGE, {"status": ticket.status})
        await emitter.emit(
            AgentEventType.ESCALATED,
            {"reason": reason_code, "queue": escalation.queue, "escalation_id": escalation.id},
        )
        await emitter.emit(AgentEventType.RUN_FINISHED, {"outcome": "escalated", "reason": reason_code})

    # ------------------------------------------------------------------ #
    # Human-in-the-loop + reply handling
    # ------------------------------------------------------------------ #
    async def approve(self, ticket_id: str, *, approve: bool, operator_id: str, note: str | None = None) -> dict:
        async with session_scope() as session:
            tickets = TicketRepository(session)
            agents = AgentRepository(session)
            ticket = await tickets.get_or_404(ticket_id)
            pending = (ticket.agent_state or {}).get("pending_approval")
            if ticket.status != TicketStatus.AWAITING_APPROVAL.value or not pending:
                return {"status": "no_pending_approval", "ticket_status": ticket.status}

            # New attempt → fresh idempotency-key namespace, so the approved tool
            # actually executes instead of replaying a cached pre-approval result.
            ticket.attempt = (ticket.attempt or 0) + 1
            run = AgentRun(
                ticket_id=ticket_id, attempt=ticket.attempt, trigger="approval",
                status="running", model=self.settings.llm_model,
            )
            await agents.create_run(run)
            await session.commit()
            emitter = EventEmitter(session, ticket_id, run.id, self.bus)

            # clear the pending marker either way
            state = dict(ticket.agent_state or {})
            state.pop("pending_approval", None)
            ticket.agent_state = state

            if not approve:
                await tickets.add_message(
                    ticket_id=ticket_id, role="agent",
                    body=f"A specialist reviewed the request and did not approve it. {note or ''}".strip(),
                    author=operator_id,
                )
                escalation_service = EscalationService(session)
                await escalation_service.escalate(
                    ticket, run_id=run.id, reason_code="needs_approval",
                    hypothesis="Human denied the gated action.",
                )
                await agents.finish_run(run, status="finished", outcome="cannot_resolve")
                await emitter.emit(AgentEventType.STATE_CHANGE, {"status": ticket.status})
                await session.commit()
                return {"status": "denied", "ticket_status": ticket.status}

            # approved: execute the gated tool now (policy bypassed — a human authorized it)
            kb = KBService(session, self.retriever)
            verification = VerificationService(session, self.settings)
            executor = ToolExecutor(self.registry, session, settings=self.settings)
            ctx = ToolContext(
                session=session, ticket=ticket, run_id=run.id, attempt=ticket.attempt,
                settings=self.settings, kb_service=kb, verification_service=verification,
                backends=self.backends, emit=emitter.emit,
            )
            tool_result = await executor.execute_approved(
                name=pending["tool"], args=pending.get("args", {}), ctx=ctx
            )
            await tickets.add_message(
                ticket_id=ticket_id, role="agent",
                body=f"A specialist approved the action '{pending['tool']}', which has now been completed.",
                author=operator_id,
            )
            from app.repositories.scheduler_repository import SchedulerRepository

            await SchedulerRepository(session).cancel_for_ticket(ticket_id, kind="approval_timeout")
            ticket.status = TicketStatus.IN_PROGRESS.value
            await agents.finish_run(run, status="finished", outcome="resolved")
            await emitter.emit(AgentEventType.STATE_CHANGE, {"status": ticket.status})
            await session.commit()

        # continue the agent so it verifies + finalizes with the action done
        self.schedule(ticket_id, "approval")
        return {"status": "approved", "tool_result": tool_result.content}

    async def handle_user_message(self, ticket_id: str, body: str, author: str | None = None) -> dict:
        """Route an inbound user message based on ticket state, then act."""
        from app.services.redaction_service import RedactionService

        async with session_scope() as session:
            tickets = TicketRepository(session)
            ticket = await tickets.get_or_404(ticket_id)
            status = ticket.status

            if status == TicketStatus.FOLLOW_UP_PENDING.value:
                followups = FollowupService(session, self.settings, self.bus)
                redaction = RedactionService()
                await tickets.add_message(
                    ticket_id=ticket_id, role="user", body=redaction.redact(body), author=author
                )
                verdict = followups.classify_reply(body)
                if verdict == "positive":
                    await followups.apply_positive(ticket)
                    kb = KBService(session, self.retriever)
                    await kb.record_outcome((ticket.resolution or {}).get("cited_kb_ids", []), success=True)
                    await session.commit()
                    return {"status": "closed", "verdict": verdict}
                if verdict == "negative":
                    await followups.apply_negative(ticket)
                    kb = KBService(session, self.retriever)
                    await kb.record_outcome((ticket.resolution or {}).get("cited_kb_ids", []), success=False)
                    await session.commit()
                    self.schedule(ticket_id, "reopen")
                    return {"status": "reopened", "verdict": verdict}
                await tickets.add_message(
                    ticket_id=ticket_id, role="agent",
                    body="Sorry, I didn't catch that — is the issue resolved? Please reply YES or NO.",
                    author="agent",
                )
                await session.commit()
                return {"status": "clarify", "verdict": verdict}

            # Default: append message and (re)run the agent.
            from app.services.ticket_service import TicketService

            await TicketService(session).add_user_message(ticket=ticket, body=body, author=author)
            await session.commit()

        self.schedule(ticket_id, "user_reply")
        return {"status": "processing"}

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    async def _latest_user_text(tickets: TicketRepository, ticket_id: str) -> str:
        messages = await tickets.list_messages(ticket_id)
        user_msgs = [m for m in messages if m.role == "user"]
        return user_msgs[-1].body if user_msgs else (messages[0].body if messages else "")

    @staticmethod
    def _has_repeated_failure(tool_calls: list[ToolCall]) -> bool:
        counts: dict[str, int] = {}
        for tc in tool_calls:
            if tc.is_error:
                counts[tc.tool_name] = counts.get(tc.tool_name, 0) + 1
        return any(v >= 2 for v in counts.values())

    @staticmethod
    def _has_oscillation(tool_calls: list[ToolCall]) -> bool:
        """Same (tool, args) invoked 3+ times in a run = no-progress looping."""
        counts: dict[tuple[str, str], int] = {}
        for tc in tool_calls:
            key = (tc.tool_name, json.dumps(tc.arguments, sort_keys=True, default=str))
            counts[key] = counts.get(key, 0) + 1
        return any(v >= 3 for v in counts.values())

    @staticmethod
    def _reason_code(ctx, decision, hallucinated: bool, outcome) -> str:
        if hallucinated:
            return "no_good_kb_match"
        if ctx.escalation_requested:
            return "user_requested" if "user" in ctx.escalation_requested.lower() else "agent_requested"
        for code in (
            "injection_flag",
            "security_label",
            "privileged_action_unverified",
            "repeated_tool_failure",
            "budget_exhausted",
            "no_good_kb_match",
        ):
            if code in decision.reasons:
                return code
        if outcome == Outcome.CANNOT_RESOLVE:
            return "low_confidence"
        return "low_confidence"

    async def _fail(self, ticket_id: str, run_id: str | None, error: str) -> None:
        try:
            async with session_scope() as session:
                tickets = TicketRepository(session)
                agents = AgentRepository(session)
                ticket = await tickets.get(ticket_id)
                if ticket is None:
                    return
                if run_id:
                    run = await agents.get_run(run_id)
                    if run is not None and run.status == "running":
                        await agents.finish_run(run, status="failed", outcome="cannot_resolve", error=error)
                escalation_service = EscalationService(session)
                await escalation_service.escalate(
                    ticket, run_id=run_id, reason_code="agent_error",
                    hypothesis=f"Internal error: {error}",
                )
                await tickets.add_message(
                    ticket_id=ticket_id, role="agent",
                    body="Something went wrong on my side, so I've escalated this to a human engineer.",
                    author="agent",
                )
        except Exception:  # noqa: BLE001
            logger.exception("agent_fail_handler_error", ticket_id=ticket_id)
