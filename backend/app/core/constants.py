"""Domain enumerations and constants — the shared vocabulary of the system.

These enums are the *single* authoritative definition referenced everywhere
(DB, schemas, services, agent). Keeping one copy avoids the classic bug where a
category typo silently breaks KB filtering or a state name drifts between layers.
"""
from __future__ import annotations

from enum import Enum


class TicketStatus(str, Enum):
    """The one ticket state machine vocabulary (see state_machine.py)."""

    NEW = "new"
    TRIAGING = "triaging"
    IN_PROGRESS = "in_progress"
    AWAITING_USER = "awaiting_user"
    AWAITING_VERIFICATION = "awaiting_verification"
    AWAITING_APPROVAL = "awaiting_approval"
    ESCALATED = "escalated"
    HUMAN_HANDLING = "human_handling"
    RESOLVED = "resolved"
    FOLLOW_UP_PENDING = "follow_up_pending"
    CLOSED = "closed"
    CLOSED_NO_RESPONSE = "closed_no_response"
    REOPENED = "reopened"

    @property
    def is_terminal(self) -> bool:
        return self in (TicketStatus.CLOSED, TicketStatus.CLOSED_NO_RESPONSE)


class Category(str, Enum):
    """IT request taxonomy. Drives KB filtering and routing."""

    PASSWORD_RESET = "password_reset"
    VPN = "vpn"
    SOFTWARE_INSTALL = "software_install"
    ACCESS_REQUEST = "access_request"
    HARDWARE_DIAG = "hardware_diag"
    EMAIL = "email"
    NETWORK = "network"
    ACCOUNT_LOCKOUT = "account_lockout"
    MFA = "mfa"
    PRINTER = "printer"
    PERFORMANCE = "performance"
    OTHER = "other"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Impact(str, Enum):
    INDIVIDUAL = "individual"
    TEAM = "team"
    ORG = "org"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    ANGRY = "angry"


class Outcome(str, Enum):
    """Terminal outcome reported by the agent via finalize_resolution."""

    RESOLVED = "resolved"
    NEEDS_USER = "needs_user"
    CANNOT_RESOLVE = "cannot_resolve"


class ConfidenceZone(str, Enum):
    AUTO_ACT = "auto_act"
    ACT_WITH_VERIFICATION = "act_with_verification"
    ESCALATE = "escalate"


class ToolMode(str, Enum):
    """How the policy engine treats a tool by default."""

    AUTO = "auto"                       # read-only / reversible, always allowed
    AUTO_RATE_LIMITED = "auto_rate_limited"
    CONFIDENCE_GATED = "confidence_gated"
    IDENTITY_GATED = "identity_gated"   # requires a fresh verification token
    HUMAN_APPROVAL = "human_approval"   # always needs a human


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    INCONCLUSIVE = "inconclusive"


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    NEEDS_APPROVAL = "needs_approval"
    NEEDS_VERIFICATION = "needs_verification"
    DENY = "deny"
    HARD_DENY = "hard_deny"  # logs a security event


class RunPhase(str, Enum):
    PERCEIVE = "perceive"
    PLAN = "plan"
    ACT = "act"
    REFLECT = "reflect"
    FINALIZE = "finalize"


class AgentEventType(str, Enum):
    """SSE event kinds streamed to the frontend agent-trace."""

    RUN_STARTED = "run_started"
    PHASE = "phase"
    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    POLICY = "policy"
    STATE_CHANGE = "state_change"
    CONFIDENCE = "confidence"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    AWAITING = "awaiting"
    ERROR = "error"
    RUN_FINISHED = "run_finished"


# --- Priority matrix: (urgency, impact) -> priority. Computed server-side. ---
_PRIORITY_MATRIX: dict[tuple[Urgency, Impact], Priority] = {
    (Urgency.CRITICAL, Impact.ORG): Priority.P1,
    (Urgency.CRITICAL, Impact.TEAM): Priority.P1,
    (Urgency.CRITICAL, Impact.INDIVIDUAL): Priority.P2,
    (Urgency.HIGH, Impact.ORG): Priority.P1,
    (Urgency.HIGH, Impact.TEAM): Priority.P2,
    (Urgency.HIGH, Impact.INDIVIDUAL): Priority.P3,
    (Urgency.MEDIUM, Impact.ORG): Priority.P2,
    (Urgency.MEDIUM, Impact.TEAM): Priority.P3,
    (Urgency.MEDIUM, Impact.INDIVIDUAL): Priority.P3,
    (Urgency.LOW, Impact.ORG): Priority.P3,
    (Urgency.LOW, Impact.TEAM): Priority.P4,
    (Urgency.LOW, Impact.INDIVIDUAL): Priority.P4,
}


def compute_priority(urgency: Urgency, impact: Impact) -> Priority:
    """Deterministically derive priority from urgency x impact.

    A model-hallucinated 'P1' can never skip the SLA queue because priority is
    *always* recomputed here from the (urgency, impact) the perception produced.
    """
    return _PRIORITY_MATRIX.get((urgency, impact), Priority.P3)


# SLA targets (minutes to first resolution attempt / response) by priority.
SLA_MINUTES: dict[Priority, int] = {
    Priority.P1: 15,
    Priority.P2: 60,
    Priority.P3: 240,
    Priority.P4: 1440,
}

# --- LLM token pricing (USD per 1M tokens). Used for the per-ticket cost meter. ---
# Keyed by a coarse model family substring.
MODEL_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # family substring : (input, output)
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
    "haiku": (0.80, 4.0),
}


def price_for_model(model: str) -> tuple[float, float]:
    """Return (input, output) USD per-MTok for a model id (best-effort match)."""
    lowered = model.lower()
    for family, price in MODEL_PRICING_USD_PER_MTOK.items():
        if family in lowered:
            return price
    return MODEL_PRICING_USD_PER_MTOK["sonnet"]


def usage_cost_cents(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute cost in cents for a single LLM call."""
    in_price, out_price = price_for_model(model)
    dollars = (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
    return round(dollars * 100, 4)
