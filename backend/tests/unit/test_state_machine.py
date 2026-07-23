"""Ticket state machine transitions."""
from __future__ import annotations

import pytest

from app.agent.state_machine import assert_can_transition, can_transition
from app.core.constants import TicketStatus as S
from app.core.exceptions import ConflictError


def test_valid_transitions():
    assert can_transition(S.NEW, S.TRIAGING)
    assert can_transition(S.IN_PROGRESS, S.RESOLVED)
    assert can_transition(S.RESOLVED, S.FOLLOW_UP_PENDING)
    assert can_transition(S.FOLLOW_UP_PENDING, S.CLOSED_NO_RESPONSE)
    assert can_transition(S.ESCALATED, S.HUMAN_HANDLING)


def test_invalid_transitions():
    assert not can_transition(S.CLOSED, S.IN_PROGRESS)
    assert not can_transition(S.NEW, S.RESOLVED)
    assert not can_transition(S.RESOLVED, S.AWAITING_VERIFICATION)


def test_same_state_is_allowed():
    assert can_transition(S.IN_PROGRESS, S.IN_PROGRESS)


def test_terminal_states():
    assert S.CLOSED.is_terminal
    assert S.CLOSED_NO_RESPONSE.is_terminal
    assert not S.RESOLVED.is_terminal


def test_assert_raises():
    with pytest.raises(ConflictError):
        assert_can_transition(S.CLOSED, S.IN_PROGRESS)
