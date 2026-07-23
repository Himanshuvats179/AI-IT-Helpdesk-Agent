"""Privileged / gated account & endpoint mutation tools.

These never execute on the model's say-so alone — the executor resolves identity
+ privilege, the policy engine authorizes, and only then does execute() run.
"""
from __future__ import annotations

from app.core.constants import AgentEventType, TicketStatus, ToolMode
from app.schemas.tool import ToolResult
from app.tools.base import Tool, ToolContext


class ResetPasswordTool(Tool):
    name = "reset_ad_password"
    mode = ToolMode.IDENTITY_GATED
    reversible = True  # recoverable (temp credential, must-change)
    description = (
        "Reset a user's Active Directory password. Requires a verified identity token for the "
        "requester. The new credential is delivered out-of-band; it is never returned to you."
    )

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "username": {"type": ["string", "null"], "description": "UPN; defaults to requester."}
            },
        }

    def target_subject(self, args: dict, ctx: ToolContext) -> str | None:
        return args.get("username") or args.get("subject") or ctx.ticket.requester_upn

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        subject = ctx.target_subject or ctx.ticket.requester_upn
        result = await ctx.backends.identity.reset_password(subject)
        # single-use: consume the verification token now that the action succeeded
        token = await ctx.verification_service.get_valid_token(ticket_id=ctx.ticket.id, subject=subject)
        if token is not None:
            await ctx.verification_service.consume(token)
        return ToolResult(content=result)


class UnlockAccountTool(Tool):
    name = "unlock_account"
    mode = ToolMode.CONFIDENCE_GATED
    reversible = True
    description = "Unlock a locked user account (reversible)."

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"username": {"type": ["string", "null"]}},
        }

    def target_subject(self, args: dict, ctx: ToolContext) -> str | None:
        return args.get("username") or ctx.ticket.requester_upn

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        subject = ctx.target_subject or ctx.ticket.requester_upn
        result = await ctx.backends.identity.unlock_account(subject)
        return ToolResult(content=result)


class InstallSoftwareTool(Tool):
    name = "install_software"
    mode = ToolMode.HUMAN_APPROVAL
    reversible = True
    description = "Install approved software on the user's device. Requires human approval."

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "asset_id": {"type": ["string", "null"]},
                "package_id": {"type": "string", "description": "Catalog package id, e.g. 'vpn-client'."},
            },
            "required": ["package_id"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        asset_id = args.get("asset_id") or (ctx.ticket.entities or {}).get("asset_id") or "primary-device"
        result = await ctx.backends.endpoint.install_software(asset_id, args["package_id"])
        return ToolResult(content=result)


class GrantAccessTool(Tool):
    name = "grant_access_request"
    mode = ToolMode.HUMAN_APPROVAL
    reversible = True
    description = "Grant access to a resource/group. Requires human approval; Tier-0 is forbidden."

    def input_schema(self) -> dict:
        # No 'subject' field: access is always granted to the requester. Cross-user
        # grants must go through a separate operator-initiated flow, so a poisoned
        # ticket cannot redirect a grant to another (or privileged) account.
        return {
            "type": "object",
            "properties": {"resource_id": {"type": "string"}},
            "required": ["resource_id"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        subject = ctx.ticket.requester_upn
        return ToolResult(
            content={"status": "granted", "resource_id": args["resource_id"], "subject": subject}
        )


class RequestIdentityVerificationTool(Tool):
    name = "request_identity_verification"
    mode = ToolMode.AUTO  # requesting a challenge is safe; the policy guards the *use*
    description = (
        "Start an out-of-band identity verification (OTP) for the requester. Use this before any "
        "privileged action when identity is not yet verified, then wait for the user's code."
    )

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        # Always verify the requester themselves — never an arbitrary subject.
        subject = ctx.ticket.requester_upn
        challenge = await ctx.verification_service.create_challenge(
            ticket_id=ctx.ticket.id, subject=subject
        )
        ctx.ticket.status = TicketStatus.AWAITING_VERIFICATION.value
        ctx.awaiting = "verification"
        message = (
            f"To verify your identity, I've sent a one-time code to your registered "
            f"factor ({challenge.factor}). Please reply with the code to continue."
        )
        await ctx.session.flush()
        await ctx.emit(AgentEventType.AWAITING, {"awaiting": "verification", "factor": challenge.factor})
        content = {
            "status": "verification_requested",
            "challenge_id": challenge.challenge_id,
            "factor": challenge.factor,
            "expires_in_seconds": challenge.expires_in_seconds,
            "user_message": message,
        }
        if challenge.demo_code:
            content["demo_code_hint"] = challenge.demo_code  # demo mode only
        return ToolResult(content=content, awaiting="verification")
