"""Perception (NLU) output schema — the structured triage of a raw ticket."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.constants import Category, Impact, Sentiment, Urgency


class ExtractedEntities(BaseModel):
    username: str | None = None
    asset_id: str | None = None
    app_name: str | None = None
    error_code: str | None = None
    os: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class PerceptionResult(BaseModel):
    """Structured classification produced by the perception service.

    ``priority`` is intentionally absent — it is recomputed server-side from
    (urgency, impact) so a hallucinated priority can never skip the SLA queue.
    """

    primary_category: Category
    intents: list[Category] = Field(default_factory=list)
    urgency: Urgency
    impact: Impact
    sentiment: Sentiment = Sentiment.NEUTRAL
    language: str = "en"
    summary: str
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    needs_clarification: bool = False
    clarifying_questions: list[str] = Field(default_factory=list)
    injection_flag: bool = False
    security_label: bool = False
    kb_hint: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
