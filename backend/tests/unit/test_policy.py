"""Default-deny policy engine (pure, no DB)."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.constants import PolicyDecision
from app.tools.account_tools import (
    GrantAccessTool,
    InstallSoftwareTool,
    ResetPasswordTool,
    UnlockAccountTool,
)
from app.tools.control_tools import SendUserMessageTool
from app.tools.policy import PolicyEngine
from app.tools.readonly_tools import SearchKBTool

engine = PolicyEngine()


def ctx(**kw):
    ticket = SimpleNamespace(
        injection_flag=kw.get("injection_flag", False),
        security_label=kw.get("security_label", False),
        requester_upn=kw.get("requester", "demo.user@corp.com"),
    )
    return SimpleNamespace(
        ticket=ticket,
        target_subject=kw.get("target_subject"),
        identity_verified=kw.get("identity_verified", False),
        target_is_privileged=kw.get("target_is_privileged", False),
        send_message_count=kw.get("send_message_count", 0),
    )


def test_readonly_allowed():
    assert engine.evaluate(SearchKBTool(), {"query": "x"}, ctx()).decision == PolicyDecision.ALLOW


def test_reset_requires_verification_when_unverified():
    d = engine.evaluate(ResetPasswordTool(), {}, ctx(target_subject="demo.user@corp.com"))
    assert d.decision == PolicyDecision.NEEDS_VERIFICATION


def test_reset_allowed_when_verified_self():
    d = engine.evaluate(
        ResetPasswordTool(), {}, ctx(target_subject="demo.user@corp.com", identity_verified=True)
    )
    assert d.decision == PolicyDecision.ALLOW


def test_reset_privileged_account_hard_denied():
    d = engine.evaluate(
        ResetPasswordTool(), {"username": "admin@corp.com"},
        ctx(target_subject="admin@corp.com", identity_verified=True, target_is_privileged=True),
    )
    assert d.decision == PolicyDecision.HARD_DENY
    assert d.security_event


def test_reset_subject_mismatch_needs_approval():
    d = engine.evaluate(
        ResetPasswordTool(), {"username": "someone.else@corp.com"},
        ctx(target_subject="someone.else@corp.com", identity_verified=True),
    )
    assert d.decision == PolicyDecision.NEEDS_APPROVAL


def test_injection_makes_sensitive_tool_need_approval():
    d = engine.evaluate(
        ResetPasswordTool(), {}, ctx(target_subject="demo.user@corp.com", injection_flag=True)
    )
    assert d.decision == PolicyDecision.NEEDS_APPROVAL
    assert d.security_event


def test_install_approved_package_needs_approval():
    d = engine.evaluate(InstallSoftwareTool(), {"package_id": "slack"}, ctx())
    assert d.decision == PolicyDecision.NEEDS_APPROVAL


def test_install_unknown_package_denied():
    d = engine.evaluate(InstallSoftwareTool(), {"package_id": "evilware"}, ctx())
    assert d.decision == PolicyDecision.DENY


def test_grant_tier0_hard_denied():
    d = engine.evaluate(GrantAccessTool(), {"resource_id": "domain-admins"}, ctx())
    assert d.decision == PolicyDecision.HARD_DENY


def test_unlock_is_confidence_gated_allow():
    d = engine.evaluate(UnlockAccountTool(), {}, ctx(target_subject="demo.user@corp.com"))
    assert d.decision == PolicyDecision.ALLOW


def test_unlock_privileged_account_hard_denied():
    # The universal privileged guard applies even to confidence-gated tools.
    d = engine.evaluate(
        UnlockAccountTool(), {"username": "admin@corp.com"},
        ctx(target_subject="admin@corp.com", target_is_privileged=True),
    )
    assert d.decision == PolicyDecision.HARD_DENY
    assert d.security_event


def test_security_label_makes_sensitive_tool_need_approval():
    d = engine.evaluate(
        ResetPasswordTool(), {}, ctx(target_subject="demo.user@corp.com", security_label=True)
    )
    assert d.decision == PolicyDecision.NEEDS_APPROVAL
    assert d.security_event


def test_grant_non_tier0_needs_approval():
    d = engine.evaluate(GrantAccessTool(), {"resource_id": "finance-share"}, ctx())
    assert d.decision == PolicyDecision.NEEDS_APPROVAL


def test_send_message_rate_limit():
    assert engine.evaluate(SendUserMessageTool(), {"message": "hi"}, ctx()).decision == PolicyDecision.ALLOW
    assert (
        engine.evaluate(SendUserMessageTool(), {"message": "hi"}, ctx(send_message_count=5)).decision
        == PolicyDecision.DENY
    )
