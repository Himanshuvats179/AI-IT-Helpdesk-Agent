"""Tool registry and the cache-stable tool-definition list."""
from __future__ import annotations

from app.tools.account_tools import (
    GrantAccessTool,
    InstallSoftwareTool,
    RequestIdentityVerificationTool,
    ResetPasswordTool,
    UnlockAccountTool,
)
from app.tools.base import Tool
from app.tools.control_tools import (
    EscalateToHumanTool,
    FinalizeResolutionTool,
    SendUserMessageTool,
    UpdateTicketTool,
)
from app.tools.readonly_tools import (
    CheckAccountStatusTool,
    RunEndpointDiagnosticTool,
    SearchKBTool,
)

_TOOL_CLASSES: list[type[Tool]] = [
    SearchKBTool,
    CheckAccountStatusTool,
    RunEndpointDiagnosticTool,
    ResetPasswordTool,
    UnlockAccountTool,
    InstallSoftwareTool,
    GrantAccessTool,
    RequestIdentityVerificationTool,
    SendUserMessageTool,
    UpdateTicketTool,
    EscalateToHumanTool,
    FinalizeResolutionTool,
]


def build_default_registry() -> dict[str, Tool]:
    return {cls.name: cls() for cls in _TOOL_CLASSES}


def tool_definitions(registry: dict[str, Tool]) -> list[dict]:
    """Anthropic tool defs in a stable, name-sorted order (prompt-cache friendly)."""
    return [registry[name].definition() for name in sorted(registry)]
