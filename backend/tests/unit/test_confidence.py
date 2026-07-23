"""The confidence calibration + gate."""
from __future__ import annotations

import pytest

from app.core.constants import ConfidenceZone, Priority, VerificationStatus
from app.schemas.agent import FinalizeResolution, ResolutionEvidence
from app.services.confidence_service import ConfidenceContext, ConfidenceService

svc = ConfidenceService()


def _fin(mc=0.95, cited=None, evidence=None):
    return FinalizeResolution(
        outcome="resolved",
        model_confidence=mc,
        cited_kb_ids=cited if cited is not None else ["KB-0003"],
        evidence=evidence or ResolutionEvidence(verification=VerificationStatus.VERIFIED),
        user_facing_answer="x",
    )


def test_high_confidence_auto_act():
    d = svc.calibrate(_fin(0.95), ConfidenceContext(priority=Priority.P3))
    assert d.zone == ConfidenceZone.AUTO_ACT
    assert d.calibrated_confidence >= 0.85


def test_no_citation_caps_and_escalates():
    d = svc.calibrate(_fin(0.99, cited=[]), ConfidenceContext(priority=Priority.P3))
    assert d.calibrated_confidence <= 0.55
    assert d.zone == ConfidenceZone.ESCALATE


def test_mid_confidence_is_verify_zone():
    d = svc.calibrate(_fin(0.80), ConfidenceContext(priority=Priority.P3))
    assert d.zone == ConfidenceZone.ACT_WITH_VERIFICATION


def test_injection_forces_escalation_regardless():
    d = svc.calibrate(_fin(0.99), ConfidenceContext(injection_flag=True))
    assert d.zone == ConfidenceZone.ESCALATE
    assert "injection_flag" in d.reasons


def test_no_good_match_caps_and_escalates():
    d = svc.calibrate(_fin(0.95), ConfidenceContext(no_good_match=True))
    assert d.calibrated_confidence <= 0.40
    assert d.zone == ConfidenceZone.ESCALATE


def test_privileged_unverified_escalates():
    d = svc.calibrate(_fin(0.95), ConfidenceContext(requires_privileged=True, identity_verified=False))
    assert d.zone == ConfidenceZone.ESCALATE
    assert "privileged_action_unverified" in d.reasons


def test_tool_failures_reduce_confidence():
    ev = ResolutionEvidence(tools_failed=["reset_ad_password", "unlock_account"])
    d = svc.calibrate(_fin(0.95, evidence=ev), ConfidenceContext(priority=Priority.P3))
    assert d.calibrated_confidence <= 0.5
    assert d.zone == ConfidenceZone.ESCALATE


def test_oscillation_forces_escalation():
    d = svc.calibrate(_fin(0.99), ConfidenceContext(oscillation=True))
    assert d.zone == ConfidenceZone.ESCALATE
    assert "oscillation_detected" in d.reasons


def test_budget_exhausted_forces_escalation():
    d = svc.calibrate(_fin(0.99), ConfidenceContext(budget_exhausted=True))
    assert d.zone == ConfidenceZone.ESCALATE
    assert "budget_exhausted" in d.reasons


def test_repeated_failure_forces_escalation():
    d = svc.calibrate(_fin(0.99), ConfidenceContext(repeated_failure=True))
    assert d.zone == ConfidenceZone.ESCALATE
    assert "repeated_tool_failure" in d.reasons


def test_p1_priority_penalty():
    d = svc.calibrate(_fin(0.95), ConfidenceContext(priority=Priority.P1))
    assert d.calibrated_confidence == pytest.approx(0.85, abs=0.01)
    assert "p1_bias_to_human" in d.reasons
