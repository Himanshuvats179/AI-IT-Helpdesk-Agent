"""Priority matrix + SLA mapping (feeds SLA timers and the P1 escalation bias)."""
from __future__ import annotations

from app.core.constants import SLA_MINUTES, Impact, Priority, Urgency, compute_priority


def test_priority_matrix_high_impact():
    assert compute_priority(Urgency.CRITICAL, Impact.ORG) == Priority.P1
    assert compute_priority(Urgency.HIGH, Impact.ORG) == Priority.P1
    assert compute_priority(Urgency.CRITICAL, Impact.TEAM) == Priority.P1


def test_priority_matrix_individual():
    assert compute_priority(Urgency.MEDIUM, Impact.INDIVIDUAL) == Priority.P3
    assert compute_priority(Urgency.LOW, Impact.INDIVIDUAL) == Priority.P4


def test_sla_decreases_with_priority():
    assert SLA_MINUTES[Priority.P1] < SLA_MINUTES[Priority.P2]
    assert SLA_MINUTES[Priority.P2] < SLA_MINUTES[Priority.P3]
    assert SLA_MINUTES[Priority.P3] < SLA_MINUTES[Priority.P4]
