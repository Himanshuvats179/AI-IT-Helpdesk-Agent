"""Ticket / message API schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class TicketCreate(BaseModel):
    body: str = Field(min_length=1, max_length=8000, description="The user's message.")
    subject: str | None = Field(default=None, max_length=500)
    requester_upn: str | None = Field(
        default=None,
        description="Authenticated requester. Defaults to the demo user when omitted.",
    )
    channel: str = "chat"


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    requester_upn: str | None = None


class MessageRead(ORMModel):
    id: str
    role: str
    body: str
    author: str | None
    created_at: datetime


class TicketRead(ORMModel):
    id: str
    requester_upn: str
    subject: str
    status: str
    category: str | None
    urgency: str | None
    impact: str | None
    priority: str | None
    sentiment: str | None
    language: str
    model_confidence: float | None
    confidence: float | None
    confidence_zone: str | None
    security_label: bool
    injection_flag: bool
    duplicate_of: str | None
    cost_cents: float
    attempt: int
    entities: dict
    resolution: dict
    agent_state: dict
    sla_due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None


class TicketDetail(TicketRead):
    messages: list[MessageRead] = Field(default_factory=list)


class IntakeResponse(BaseModel):
    ticket_id: str
    run_id: str | None
    status: str
    duplicate_of: str | None = None
