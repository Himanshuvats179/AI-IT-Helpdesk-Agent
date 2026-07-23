"""Tool execution + policy schemas (internal)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import PolicyDecision


class ToolResult(BaseModel):
    """Normalized result of a tool execution returned to the agent loop."""

    content: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    # Optional control signals the loop interprets (never sent verbatim to model).
    awaiting: str | None = None  # 'verification' | 'approval' | 'user'
    terminal: bool = False  # finalize/escalate end the loop

    def as_tool_content(self) -> str:
        """Serialize to the string content Anthropic expects in a tool_result."""
        import json

        return json.dumps(self.content, ensure_ascii=False, default=str)


class PolicyResult(BaseModel):
    decision: PolicyDecision
    rule: str | None = None
    reason: str = ""
    security_event: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision == PolicyDecision.ALLOW


class VerificationRequest(BaseModel):
    code: str
    challenge_id: str | None = None
