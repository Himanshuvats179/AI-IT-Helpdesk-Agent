"""The single, authoritative confidence calibration + gate.

Self-reported model confidence is never trusted alone — it is blended with
independent signals (grounding, tool outcomes, priority, KB match) and then
routed into one of three zones. Hard-safety conditions bypass the number
entirely and force escalation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.core.constants import ConfidenceZone, Priority
from app.schemas.agent import ConfidenceDecision, FinalizeResolution


@dataclass
class ConfidenceContext:
    priority: Priority | None = None
    no_good_match: bool = False
    injection_flag: bool = False
    security_label: bool = False
    requires_privileged: bool = False
    identity_verified: bool = False
    repeated_failure: bool = False
    oscillation: bool = False
    budget_exhausted: bool = False
    extra_reasons: list[str] = field(default_factory=list)


class ConfidenceService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _zone(self, score: float) -> ConfidenceZone:
        if score >= self.settings.confidence_auto_threshold:
            return ConfidenceZone.AUTO_ACT
        if score >= self.settings.confidence_verify_threshold:
            return ConfidenceZone.ACT_WITH_VERIFICATION
        return ConfidenceZone.ESCALATE

    def _hard_safety_reasons(self, ctx: ConfidenceContext) -> list[str]:
        reasons: list[str] = []
        if ctx.injection_flag:
            reasons.append("injection_flag")
        if ctx.security_label:
            reasons.append("security_label")
        if ctx.requires_privileged and not ctx.identity_verified:
            reasons.append("privileged_action_unverified")
        if ctx.repeated_failure:
            reasons.append("repeated_tool_failure")
        if ctx.oscillation:
            reasons.append("oscillation_detected")
        if ctx.budget_exhausted:
            reasons.append("budget_exhausted")
        reasons.extend(ctx.extra_reasons)
        return reasons

    def calibrate(self, finalize: FinalizeResolution, ctx: ConfidenceContext) -> ConfidenceDecision:
        c = float(finalize.model_confidence)
        reasons: list[str] = []

        if not finalize.cited_kb_ids:
            c = min(c, 0.55)
            reasons.append("no_kb_citation")

        fails = len(finalize.evidence.tools_failed)
        if fails:
            c -= 0.25 * fails
            reasons.append(f"tools_failed={fails}")

        if finalize.evidence.unmatched_symptoms:
            c -= 0.15
            reasons.append("unmatched_symptoms")

        if ctx.priority == Priority.P1:
            c -= 0.10
            reasons.append("p1_bias_to_human")

        if ctx.no_good_match:
            c = min(c, 0.40)
            reasons.append("no_good_kb_match")

        c = max(0.0, min(1.0, c))
        zone = self._zone(c)

        hard = self._hard_safety_reasons(ctx)
        if hard:
            zone = ConfidenceZone.ESCALATE
            reasons.extend(hard)

        return ConfidenceDecision(
            model_confidence=round(float(finalize.model_confidence), 4),
            calibrated_confidence=round(c, 4),
            zone=zone,
            reasons=reasons,
        )
