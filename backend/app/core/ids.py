"""Prefixed identifier helpers and time utilities.

Prefixed ids (``tkt_…``, ``run_…``) make logs and traces self-describing and
avoid accidental cross-entity id mix-ups.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _short() -> str:
    # Full 128-bit uuid4 hex: collision-safe for public ids at scale (the old
    # 12-char/48-bit truncation hit ~0.1% birthday collisions by ~60M ids).
    return uuid.uuid4().hex


def new_ticket_id() -> str:
    return f"tkt_{_short()}"


def new_message_id() -> str:
    return f"msg_{_short()}"


def new_run_id() -> str:
    return f"run_{_short()}"


def new_tool_call_id() -> str:
    return f"tc_{_short()}"


def new_escalation_id() -> str:
    return f"esc_{_short()}"


def new_job_id() -> str:
    return f"job_{_short()}"


def new_event_id() -> str:
    return f"evt_{_short()}"


def new_token_id() -> str:
    return f"vtok_{_short()}"


def utcnow() -> datetime:
    """Naive UTC now. The one place we read the clock.

    We use naive-UTC (not tz-aware) so comparisons stay consistent across the DB
    boundary: SQLite stores datetimes without timezone, so mixing tz-aware values
    would raise 'can't compare offset-naive and offset-aware datetimes'.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
