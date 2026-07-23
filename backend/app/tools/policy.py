"""Default-deny policy engine — the authoritative gate over every tool call.

The model's request is advisory; this engine decides. Rules are evaluated
first-match-wins with safety gates first. Identity verification, subject-binding
and privilege checks are resolved by the executor *before* this runs, so the
engine itself is pure and trivially testable.
"""
from __future__ import annotations

from app.core.constants import PolicyDecision, ToolMode
from app.schemas.tool import PolicyResult
from app.tools.account_tools import GrantAccessTool, InstallSoftwareTool
from app.tools.backends.endpoint import APPROVED_SOFTWARE_CATALOG
from app.tools.base import TIER0_RESOURCES, Tool, ToolContext


class PolicyEngine:
    def evaluate(self, tool: Tool, args: dict, ctx: ToolContext) -> PolicyResult:
        # --- Global safety gates (apply to any non-read tool) ---
        sensitive = tool.mode in (
            ToolMode.CONFIDENCE_GATED,
            ToolMode.IDENTITY_GATED,
            ToolMode.HUMAN_APPROVAL,
        )
        # Privileged/admin accounts are never modified by the agent, for ANY
        # subject-targeting sensitive tool (not only identity-gated ones).
        if sensitive and getattr(ctx, "target_is_privileged", False):
            return PolicyResult(
                decision=PolicyDecision.HARD_DENY,
                rule="privileged_account",
                reason="Refusing privileged/admin account modification by the agent.",
                security_event=True,
            )
        if sensitive and ctx.ticket.injection_flag:
            return PolicyResult(
                decision=PolicyDecision.NEEDS_APPROVAL,
                rule="injection_guard",
                reason="Prompt-injection suspected; sensitive action requires human approval.",
                security_event=True,
            )
        if sensitive and ctx.ticket.security_label:
            return PolicyResult(
                decision=PolicyDecision.NEEDS_APPROVAL,
                rule="security_guard",
                reason="Security-sensitive ticket; action requires human approval.",
                security_event=True,
            )

        # --- Mode-specific rules ---
        if tool.mode in (ToolMode.AUTO, ToolMode.AUTO_RATE_LIMITED):
            if tool.mode == ToolMode.AUTO_RATE_LIMITED and ctx.send_message_count >= 5:
                return PolicyResult(
                    decision=PolicyDecision.DENY, rule="rate_limit",
                    reason="Message rate limit reached for this run.",
                )
            return PolicyResult(decision=PolicyDecision.ALLOW, rule="auto")

        if tool.mode == ToolMode.CONFIDENCE_GATED:
            # Reversible action; confidence is enforced by the loop's gate, not here.
            return PolicyResult(decision=PolicyDecision.ALLOW, rule="confidence_gated")

        if tool.mode == ToolMode.IDENTITY_GATED:
            return self._identity_gate(args, ctx)

        if tool.mode == ToolMode.HUMAN_APPROVAL:
            return self._approval_gate(tool, args)

        return PolicyResult(
            decision=PolicyDecision.DENY, rule="default_deny", reason="No matching allow rule."
        )

    # ------------------------------------------------------------------ #
    def _identity_gate(self, args: dict, ctx: ToolContext) -> PolicyResult:
        target = (ctx.target_subject or "").lower()
        requester = (ctx.ticket.requester_upn or "").lower()

        if ctx.target_is_privileged:
            return PolicyResult(
                decision=PolicyDecision.HARD_DENY,
                rule="privileged_account",
                reason="Refusing privileged/admin account modification by the agent.",
                security_event=True,
            )
        if target and target != requester:
            return PolicyResult(
                decision=PolicyDecision.NEEDS_APPROVAL,
                rule="subject_mismatch",
                reason="Action targets a different user than the requester; needs human approval.",
                security_event=True,
            )
        if not ctx.identity_verified:
            return PolicyResult(
                decision=PolicyDecision.NEEDS_VERIFICATION,
                rule="identity_required",
                reason="Identity must be verified (step-up) before this action.",
            )
        return PolicyResult(decision=PolicyDecision.ALLOW, rule="identity_verified")

    def _approval_gate(self, tool: Tool, args: dict) -> PolicyResult:
        if tool.name == InstallSoftwareTool.name:
            package = args.get("package_id")
            if package not in APPROVED_SOFTWARE_CATALOG:
                return PolicyResult(
                    decision=PolicyDecision.DENY,
                    rule="catalog_check",
                    reason=f"Package '{package}' is not in the approved catalog.",
                )
        if tool.name == GrantAccessTool.name:
            resource = (args.get("resource_id") or "").lower()
            if resource in TIER0_RESOURCES:
                return PolicyResult(
                    decision=PolicyDecision.HARD_DENY,
                    rule="tier0_resource",
                    reason="Tier-0 resource grants are never automated.",
                    security_event=True,
                )
        return PolicyResult(
            decision=PolicyDecision.NEEDS_APPROVAL,
            rule="human_approval_required",
            reason="This action requires explicit human approval.",
        )
