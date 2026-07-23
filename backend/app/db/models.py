"""ORM models — the persistent backbone of the system.

Design notes
------------
* Enums are stored as their string values (portable, human-readable in SQLite).
* JSON columns hold structured payloads (entities, tool I/O, handover packages).
* ``agent_runs`` + ``tool_calls`` together form the immutable audit trail an
  operator needs to *replay* any agent decision.
* ``scheduled_jobs`` is the single durable timer mechanism (follow-ups,
  approval timeouts) with a ``UNIQUE`` idempotency key and a lease for
  exactly-once execution across pollers.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import (
    new_escalation_id,
    new_event_id,
    new_job_id,
    new_message_id,
    new_run_id,
    new_ticket_id,
    new_tool_call_id,
    new_token_id,
    utcnow,
)
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    upn: Mapped[str] = mapped_column(String(255), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(40), default="employee")
    # Pre-registered out-of-band factor for step-up auth (e.g. masked phone).
    registered_factor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_privileged_account: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_ticket_id)
    requester_upn: Mapped[str] = mapped_column(String(255), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="chat")
    subject: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)

    # Perception output (nullable until triaged).
    category: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    urgency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    impact: Mapped[str | None] = mapped_column(String(20), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="en")

    # Confidence + safety signals.
    model_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_zone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    security_label: Mapped[bool] = mapped_column(Boolean, default=False)
    injection_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    # Dedup / bookkeeping.
    duplicate_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    cost_cents: Mapped[float] = mapped_column(Float, default=0.0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    entities: Mapped[dict] = mapped_column(JSON, default=dict)
    # Snapshot of the resolving run: cited_kb_ids, applied_steps, user_facing_answer.
    resolution: Mapped[dict] = mapped_column(JSON, default=dict)
    # Transient agent bookkeeping (e.g. a pending approval awaiting a human).
    agent_state: Mapped[dict] = mapped_column(JSON, default=dict)

    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="AgentRun.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_message_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | agent | human | system
    body: Mapped[str] = mapped_column(Text)  # PII-redacted before persist
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped["Ticket"] = relationship(back_populates="messages")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_run_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(40))  # intake | user_reply | approval | followup
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|finished|failed
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_cents: Mapped[float] = mapped_column(Float, default=0.0)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    final_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    transcript: Mapped[list] = mapped_column(JSON, default=list)  # checkpointed messages
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="runs")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ToolCall.created_at"
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_tool_call_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(80))
    tool_use_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped["AgentRun"] = relationship(back_populates="tool_calls")


class KBArticle(Base):
    __tablename__ = "kb_articles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40), index=True)
    symptoms: Mapped[list] = mapped_column(JSON, default=list)
    applies_to: Mapped[list] = mapped_column(JSON, default=list)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    required_tools: Mapped[list] = mapped_column(JSON, default=list)
    risk_level: Mapped[str] = mapped_column(String(20), default="safe")
    preconditions: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text)  # used for embedding + BM25
    success_rate: Mapped[float] = mapped_column(Float, default=1.0)
    resolution_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_verified: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_escalation_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str] = mapped_column(String(80))
    queue: Mapped[str] = mapped_column(String(60), index=True)
    model_self_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibrated_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # full handover package
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|assigned|resolved
    assignee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    override_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    # The poller's hot path filters on (status, run_at); a composite index lets
    # both predicates be satisfied together.
    __table_args__ = (Index("ix_scheduled_jobs_status_run_at", "status", "run_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_job_id)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # followup | approval_timeout
    ticket_id: Mapped[str] = mapped_column(String(40), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    lease_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class VerificationToken(Base):
    """Subject-bound, short-TTL, single-use step-up token for privileged tools."""

    __tablename__ = "verification_tokens"
    __table_args__ = (UniqueConstraint("ticket_id", "challenge_id", name="uq_ticket_challenge"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_token_id)
    ticket_id: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(255))  # the UPN this token authorizes
    challenge_id: Mapped[str] = mapped_column(String(40))
    code_hash: Mapped[str] = mapped_column(String(128))
    factor: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|verified|consumed|expired
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentEvent(Base):
    """Append-only event log per run — powers SSE replay and trace inspection."""

    __tablename__ = "agent_events"
    # SSE replay and next_seq both query WHERE ticket_id = ? AND seq > ?.
    __table_args__ = (Index("ix_agent_events_ticket_seq", "ticket_id", "seq"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_event_id)
    # Composite (ticket_id, seq) index above covers ticket_id-only lookups too.
    ticket_id: Mapped[str] = mapped_column(String(40))
    run_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
