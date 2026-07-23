"""Agent-facing schemas: finalize output, verification, run reads, events."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.constants import ConfidenceZone, Outcome, VerificationStatus
from app.schemas.common import ORMModel


class ResolutionEvidence(BaseModel):
    tools_succeeded: list[str] = Field(default_factory=list)
    tools_failed: list[str] = Field(default_factory=list)
    unmatched_symptoms: bool = False
    verification: VerificationStatus | None = None


class FinalizeResolution(BaseModel):
    """The single terminal output schema the agent must emit to end a run."""

    outcome: Outcome
    model_confidence: float = Field(ge=0.0, le=1.0)
    cited_kb_ids: list[str] = Field(default_factory=list)
    applied_steps: list[str] = Field(default_factory=list)
    evidence: ResolutionEvidence = Field(default_factory=ResolutionEvidence)
    # Bounded so a malfunctioning/manipulated model can't persist an unbounded blob.
    user_facing_answer: str = Field(max_length=8000)
    handover_summary: str | None = Field(default=None, max_length=8000)


class ConfidenceDecision(BaseModel):
    model_confidence: float
    calibrated_confidence: float
    zone: ConfidenceZone
    reasons: list[str] = Field(default_factory=list)


class ToolCallRead(ORMModel):
    id: str
    tool_name: str
    arguments: dict
    output: dict
    is_error: bool
    policy_decision: str | None
    latency_ms: int
    created_at: datetime


class AgentRunRead(ORMModel):
    id: str
    ticket_id: str
    attempt: int
    trigger: str
    status: str
    model: str | None
    steps: int
    input_tokens: int
    output_tokens: int
    cost_cents: float
    outcome: str | None
    final_confidence: float | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    tool_calls: list[ToolCallRead] = Field(default_factory=list)


class RunResult(BaseModel):
    """Internal result returned by the agent loop to the runner."""

    outcome: Outcome
    finalize: FinalizeResolution | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    awaiting: str | None = None  # e.g. 'user' | 'verification' | 'approval'
    protocol_violation: bool = False
    steps: int = 0
