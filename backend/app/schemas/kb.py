"""Knowledge base + retrieval schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.constants import Category, RiskLevel
from app.schemas.common import ORMModel


class KBStep(BaseModel):
    text: str
    requires_tool: str | None = None
    destructive: bool = False


class KBArticleIn(BaseModel):
    id: str
    title: str
    category: Category
    symptoms: list[str] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)
    steps: list[KBStep] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.SAFE
    preconditions: list[str] = Field(default_factory=list)
    content: str | None = None  # auto-derived from title+symptoms+steps if absent


class KBArticleRead(ORMModel):
    id: str
    title: str
    category: str
    symptoms: list
    applies_to: list
    steps: list
    required_tools: list
    risk_level: str
    preconditions: list
    success_rate: float
    resolution_count: int
    version: int
    last_verified: datetime


class RetrievalHit(BaseModel):
    article_id: str
    title: str
    category: str
    risk_level: str
    score: float
    dense_score: float | None = None
    keyword_score: float | None = None
    steps: list = Field(default_factory=list)
    required_tools: list = Field(default_factory=list)
    snippet: str = ""


class RetrievalResult(BaseModel):
    query: str
    hits: list[RetrievalHit] = Field(default_factory=list)
    confidence: str = "none"  # high | medium | low | none
    no_good_match: bool = True

    def cited_ids(self) -> set[str]:
        return {h.article_id for h in self.hits}
