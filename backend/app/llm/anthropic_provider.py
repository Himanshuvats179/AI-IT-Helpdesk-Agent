"""Real Claude adapter over the Anthropic SDK.

Implements :class:`LLMProvider`. Handles prompt caching (cache_control on the
stable system + tools prefix), optional extended thinking, forced tool use for
structured outputs, retries, and normalization of the SDK response into our
SDK-agnostic :class:`LLMResponse`.
"""
from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.core.exceptions import ConfigurationError, LLMError
from app.core.logging import get_logger
from app.llm.provider import (
    LLMResponse,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)

logger = get_logger(__name__)


class AnthropicProvider:
    """Production LLM provider backed by Claude (Anthropic Messages API)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        api_key = self.settings.anthropic_api_key.get_secret_value()
        if not api_key:
            raise ConfigurationError(
                "ANTHROPIC_API_KEY is not set. The agent requires a Claude credential "
                "to run. Set it in .env (and ANTHROPIC_BASE_URL for Azure/Foundry)."
            )
        # Imported lazily so the package imports even if the SDK isn't installed
        # in a pure-unit-test environment (tests use the fake provider instead).
        from anthropic import AsyncAnthropic

        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "max_retries": self.settings.llm_max_retries,
            "timeout": self.settings.llm_timeout_seconds,
        }
        if self.settings.anthropic_base_url:
            client_kwargs["base_url"] = self.settings.anthropic_base_url
        self._client = AsyncAnthropic(**client_kwargs)

    # ------------------------------------------------------------------ #
    def _build_system(self, system: str | list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if system is None:
            return None
        if isinstance(system, str):
            blocks = [{"type": "text", "text": system}]
        else:
            blocks = [dict(b) for b in system]
        if self.settings.llm_enable_prompt_cache and blocks:
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
        return blocks

    def _build_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        prepared = [dict(t) for t in tools]
        if self.settings.llm_enable_prompt_cache:
            prepared[-1]["cache_control"] = {"type": "ephemeral"}
        return prepared

    @staticmethod
    def _normalize(response: Any) -> LLMResponse:
        content: list[Any] = []
        raw: list[dict[str, Any]] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                content.append(TextBlock(text=block.text))
            elif btype == "tool_use":
                content.append(ToolUseBlock(id=block.id, name=block.name, input=dict(block.input)))
            elif btype == "thinking":
                content.append(
                    ThinkingBlock(
                        thinking=getattr(block, "thinking", ""),
                        signature=getattr(block, "signature", None),
                    )
                )
            # Preserve the raw block (incl. signatures) for the next turn.
            if hasattr(block, "model_dump"):
                raw.append(block.model_dump(exclude_none=True))
        usage = response.usage
        return LLMResponse(
            stop_reason=response.stop_reason or "end_turn",
            content=content,
            usage=Usage(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            ),
            raw_assistant_content=raw,
            model=getattr(response, "model", ""),
        )

    # ------------------------------------------------------------------ #
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
        model = model or self.settings.llm_model
        # Use an explicit None check so a caller can't accidentally fall through
        # to the default by passing 0.
        if max_tokens is None:
            max_tokens = self.settings.llm_max_tokens

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        sys_blocks = self._build_system(system)
        if sys_blocks:
            kwargs["system"] = sys_blocks
        prepared_tools = self._build_tools(tools)
        if prepared_tools:
            kwargs["tools"] = prepared_tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        if thinking and self.settings.llm_thinking_enabled:
            # Extended thinking requires temperature=1 and budget < max_tokens.
            budget = min(self.settings.llm_thinking_budget_tokens, max(max_tokens - 512, 256))
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kwargs["temperature"] = 1.0
            kwargs.pop("tool_choice", None)  # cannot force tool use with thinking

        try:
            response = await self._client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - normalize any SDK failure
            logger.error("llm_call_failed", model=model, error=str(exc))
            raise LLMError(f"Claude call failed: {exc}") from exc

        return self._normalize(response)
