"""Perception / NLU service: raw ticket text -> structured PerceptionResult.

Uses forced tool-use ('classify_ticket') for robust structured output. The
ticket text is fenced as untrusted data; the model only classifies, it has no
action tools here, so the schema is a cage. The heuristic injection signal from
ingress is OR-ed with the model's own assessment (defense in depth).
"""
from __future__ import annotations

from app.config import Settings, get_settings
from app.core.constants import Category, Impact, Sentiment, Urgency
from app.core.logging import get_logger
from app.llm.prompts import (
    PERCEPTION_SYSTEM,
    build_perception_user,
    perception_tool_schema,
)
from app.llm.provider import LLMProvider
from app.schemas.perception import ExtractedEntities, PerceptionResult

logger = get_logger(__name__)


class PerceptionService:
    def __init__(self, provider: LLMProvider, settings: Settings | None = None) -> None:
        self.provider = provider
        self.settings = settings or get_settings()

    async def classify(self, text: str, *, heuristic_injection: bool = False) -> PerceptionResult:
        schema = perception_tool_schema()
        try:
            response = await self.provider.create_message(
                system=PERCEPTION_SYSTEM,
                messages=[{"role": "user", "content": build_perception_user(text)}],
                tools=[schema],
                tool_choice={"type": "tool", "name": "classify_ticket"},
                model=self.settings.llm_model,
                max_tokens=1024,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("perception_failed", error=str(exc))
            return self._fallback(heuristic_injection, reason="perception_error")

        tool_use = response.first_tool_use()
        if tool_use is None:
            logger.warning("perception_no_tool_use")
            return self._fallback(heuristic_injection, reason="no_tool_use")

        result = self._parse(tool_use.input)
        if heuristic_injection:
            result.injection_flag = True
        return result

    def _parse(self, data: dict) -> PerceptionResult:
        try:
            result = PerceptionResult.model_validate(data)
        except Exception:  # noqa: BLE001 - be permissive with model output
            result = PerceptionResult(
                primary_category=_coerce_category(data.get("primary_category")),
                urgency=_coerce_enum(Urgency, data.get("urgency"), Urgency.MEDIUM),
                impact=_coerce_enum(Impact, data.get("impact"), Impact.INDIVIDUAL),
                sentiment=_coerce_enum(Sentiment, data.get("sentiment"), Sentiment.NEUTRAL),
                summary=str(data.get("summary") or "Unclassified request."),
                entities=ExtractedEntities(**(data.get("entities") or {})),
                needs_clarification=bool(data.get("needs_clarification", False)),
                clarifying_questions=list(data.get("clarifying_questions", []) or []),
                injection_flag=bool(data.get("injection_flag", False)),
                security_label=bool(data.get("security_label", False)),
                kb_hint=data.get("kb_hint"),
                confidence=float(data.get("confidence", 0.5) or 0.5),
            )
        if not result.intents:
            result.intents = [result.primary_category]
        return result

    @staticmethod
    def _fallback(heuristic_injection: bool, *, reason: str) -> PerceptionResult:
        return PerceptionResult(
            primary_category=Category.OTHER,
            intents=[Category.OTHER],
            urgency=Urgency.MEDIUM,
            impact=Impact.INDIVIDUAL,
            sentiment=Sentiment.NEUTRAL,
            summary=f"Could not auto-classify ({reason}); routing for review.",
            needs_clarification=True,
            injection_flag=heuristic_injection,
            confidence=0.2,
        )


def _coerce_category(value) -> Category:
    try:
        return Category(value)
    except (ValueError, TypeError):
        return Category.OTHER


def _coerce_enum(enum_cls, value, default):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default
