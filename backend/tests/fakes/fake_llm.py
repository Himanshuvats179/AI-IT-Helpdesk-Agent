"""Scripted LLM provider for tests (implements the LLMProvider Protocol).

It distinguishes the two call shapes the app makes:
  * perception: forced tool_choice {"type":"tool"} -> returns a classify_ticket call
  * resolution loop: tool_choice auto -> returns the next scripted turn

A 'turn' is a list of (tool_name, input_dict). An empty/exhausted turn returns
end_turn (which the loop treats as a protocol violation unless finalize ran).
"""
from __future__ import annotations

from app.llm.provider import LLMResponse, TextBlock, ToolUseBlock, Usage

DEFAULT_PERCEPTION = {
    "primary_category": "vpn",
    "intents": ["vpn"],
    "urgency": "medium",
    "impact": "individual",
    "sentiment": "neutral",
    "language": "en",
    "summary": "User reports a VPN connection problem.",
    "entities": {},
    "needs_clarification": False,
    "injection_flag": False,
    "security_label": False,
    "confidence": 0.85,
}


class FakeLLM:
    def __init__(self, perception: dict | None = None, script: list | None = None) -> None:
        self.perception = {**DEFAULT_PERCEPTION, **(perception or {})}
        self.script = script or []
        self.turn = 0
        self.calls: list[dict] = []
        self._id = 0

    def _next_id(self) -> str:
        self._id += 1
        return f"tu_{self._id}"

    async def create_message(
        self,
        *,
        messages,
        system=None,
        tools=None,
        tool_choice=None,
        model=None,
        max_tokens=None,
        temperature=0.0,
        thinking=False,
    ) -> LLMResponse:
        self.calls.append({"tool_choice": tool_choice, "n_messages": len(messages)})
        if tool_choice and tool_choice.get("type") == "tool":
            return self._classify()
        spec = self.script[self.turn] if self.turn < len(self.script) else []
        self.turn += 1
        return self._tools_response(spec)

    def _classify(self) -> LLMResponse:
        tid = self._next_id()
        payload = dict(self.perception)
        return LLMResponse(
            stop_reason="tool_use",
            content=[ToolUseBlock(id=tid, name="classify_ticket", input=payload)],
            usage=Usage(input_tokens=80, output_tokens=40),
            raw_assistant_content=[{"type": "tool_use", "id": tid, "name": "classify_ticket", "input": payload}],
            model="fake-haiku",
        )

    def _tools_response(self, spec: list[tuple[str, dict]]) -> LLMResponse:
        if not spec:
            return LLMResponse(
                stop_reason="end_turn",
                content=[TextBlock(text="(no action)")],
                usage=Usage(input_tokens=40, output_tokens=10),
                raw_assistant_content=[{"type": "text", "text": "(no action)"}],
                model="fake-sonnet",
            )
        blocks: list = []
        raw: list[dict] = []
        for name, inp in spec:
            tid = self._next_id()
            blocks.append(ToolUseBlock(id=tid, name=name, input=inp))
            raw.append({"type": "tool_use", "id": tid, "name": name, "input": inp})
        return LLMResponse(
            stop_reason="tool_use",
            content=blocks,
            usage=Usage(input_tokens=120, output_tokens=60),
            raw_assistant_content=raw,
            model="fake-sonnet",
        )


def finalize_call(
    *,
    outcome: str = "resolved",
    confidence: float = 0.95,
    cited: list[str] | None = None,
    steps: list[str] | None = None,
    verification: str | None = "verified",
    answer: str = "Here is the fix.",
    tools_failed: list[str] | None = None,
) -> tuple[str, dict]:
    return (
        "finalize_resolution",
        {
            "outcome": outcome,
            "model_confidence": confidence,
            "cited_kb_ids": cited or [],
            "applied_steps": steps or [],
            "evidence": {
                "tools_succeeded": [],
                "tools_failed": tools_failed or [],
                "unmatched_symptoms": False,
                "verification": verification,
            },
            "user_facing_answer": answer,
        },
    )
