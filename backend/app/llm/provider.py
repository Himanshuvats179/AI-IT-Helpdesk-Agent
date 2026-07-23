"""LLM provider abstraction.

The agent loop depends only on :class:`LLMProvider` (a Protocol), never on the
Anthropic SDK directly. This is the seam that lets tests inject a scripted fake
while production uses the real Claude adapter (Dependency Inversion).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.constants import usage_cost_cents


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ThinkingBlock:
    thinking: str
    signature: str | None = None
    type: str = "thinking"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0

    def cost_cents(self, model: str) -> float:
        return usage_cost_cents(model, self.input_tokens, self.output_tokens)


@dataclass
class LLMResponse:
    """Normalized model response, decoupled from any SDK types."""

    stop_reason: str
    content: list[ContentBlock] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    # Anthropic-format assistant content (list of dicts) to append to `messages`.
    raw_assistant_content: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""

    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    def first_tool_use(self) -> ToolUseBlock | None:
        uses = self.tool_uses()
        return uses[0] if uses else None


@runtime_checkable
class LLMProvider(Protocol):
    async def create_message(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str | list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        thinking: bool = False,
    ) -> LLMResponse:
        """Send one turn to the model and return a normalized response."""
        ...


class UnconfiguredProvider:
    """Placeholder used when no Anthropic credential is configured.

    Lets the API start (so the KB, dashboard and frontend work) while making any
    attempt to actually run the agent fail with a clear, actionable message.
    """

    async def create_message(self, **_: Any) -> LLMResponse:
        from app.core.exceptions import LLMError

        raise LLMError(
            "No Anthropic credential configured. Set ANTHROPIC_API_KEY (and "
            "ANTHROPIC_BASE_URL for Azure/Foundry) in backend/.env to run the agent."
        )
