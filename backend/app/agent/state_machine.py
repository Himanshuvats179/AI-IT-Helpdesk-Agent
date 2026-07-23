"""The single ticket state machine.

Transitions are validated here so no layer can move a ticket into an illegal
state. The agent loop runs only while a ticket is ``in_progress``; everything
else is deterministic Python we own, which keeps the machine replayable.
"""
from __future__ import annotations

from app.core.constants import TicketStatus as S
from app.core.exceptions import ConflictError

ALLOWED_TRANSITIONS: dict[S, set[S]] = {
    S.NEW: {S.TRIAGING, S.ESCALATED, S.IN_PROGRESS},
    S.TRIAGING: {S.IN_PROGRESS, S.ESCALATED, S.AWAITING_USER},
    S.IN_PROGRESS: {
        S.AWAITING_USER,
        S.AWAITING_VERIFICATION,
        S.AWAITING_APPROVAL,
        S.RESOLVED,
        S.ESCALATED,
    },
    S.AWAITING_USER: {S.IN_PROGRESS, S.ESCALATED, S.CLOSED},
    S.AWAITING_VERIFICATION: {S.IN_PROGRESS, S.ESCALATED, S.AWAITING_USER},
    S.AWAITING_APPROVAL: {S.IN_PROGRESS, S.ESCALATED, S.RESOLVED},
    S.ESCALATED: {S.HUMAN_HANDLING, S.RESOLVED, S.CLOSED},
    S.HUMAN_HANDLING: {S.RESOLVED, S.CLOSED, S.IN_PROGRESS},
    S.RESOLVED: {S.FOLLOW_UP_PENDING, S.CLOSED, S.REOPENED, S.ESCALATED},
    S.FOLLOW_UP_PENDING: {S.CLOSED, S.CLOSED_NO_RESPONSE, S.REOPENED},
    S.REOPENED: {S.IN_PROGRESS, S.TRIAGING, S.ESCALATED},
    S.CLOSED: set(),
    S.CLOSED_NO_RESPONSE: set(),
}


def can_transition(current: S, target: S) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


def assert_can_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        raise ConflictError(f"Illegal ticket transition: {current.value} -> {target.value}")
