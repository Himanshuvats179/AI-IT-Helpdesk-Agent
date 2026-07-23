"""Perception service over the scripted LLM."""
from __future__ import annotations

from app.services.perception_service import PerceptionService
from tests.fakes.fake_llm import FakeLLM


async def test_classify_parses_structured_output():
    fake = FakeLLM(
        perception={
            "primary_category": "password_reset",
            "urgency": "high",
            "impact": "individual",
            "summary": "User forgot password.",
            "confidence": 0.9,
        }
    )
    result = await PerceptionService(fake).classify("I forgot my password")
    assert result.primary_category.value == "password_reset"
    assert result.intents  # defaulted from primary
    assert 0.0 <= result.confidence <= 1.0


async def test_heuristic_injection_is_ored_in():
    fake = FakeLLM(perception={"injection_flag": False})
    result = await PerceptionService(fake).classify("text", heuristic_injection=True)
    assert result.injection_flag is True


async def test_fallback_on_provider_error():
    class Boom:
        async def create_message(self, **_):
            raise RuntimeError("model down")

    result = await PerceptionService(Boom()).classify("hello")
    assert result.primary_category.value == "other"
    assert result.needs_clarification is True
