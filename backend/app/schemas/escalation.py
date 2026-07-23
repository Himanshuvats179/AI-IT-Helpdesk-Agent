"""Escalation / human-handover schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class HandoverPackage(BaseModel):
    """The structured, pre-filled summary handed to a human engineer."""

    ticket_id: str
    why_escalated: str
    reason_code: str
    category: str | None = None
    priority: str | None = None
    model_self_confidence: float | None = None
    calibrated_confidence: float | None = None
    structured_summary: str = ""
    current_hypothesis: str | None = None
    recommended_next_steps: list[str] = Field(default_factory=list)
    kb_articles_considered: list[str] = Field(default_factory=list)
    tool_call_trace: list[dict] = Field(default_factory=list)
    entities: dict = Field(default_factory=dict)
    conversation: list[dict] = Field(default_factory=list)


class EscalationRead(ORMModel):
    id: str
    ticket_id: str
    run_id: str | None
    reason: str
    queue: str
    model_self_confidence: float | None
    calibrated_confidence: float | None
    payload: dict
    status: str
    assignee: str | None
    override_of: str | None
    created_at: datetime
    resolved_at: datetime | None


class HitlAction(BaseModel):
    """A human override / decision applied to a ticket."""

    action: str = Field(
        description="approve | deny | force_resolve | force_escalate | take_over | reply"
    )
    operator_id: str = "operator@corp"
    note: str | None = None
    message: str | None = None  # for 'reply' / resolution text


class ApprovalDecision(BaseModel):
    approve: bool
    operator_id: str = "operator@corp"
    note: str | None = None
