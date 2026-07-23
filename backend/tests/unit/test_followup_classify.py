"""Follow-up reply classification edge cases (word-level, not substring)."""
from __future__ import annotations

import pytest

from app.services.followup_service import FollowupService


@pytest.mark.parametrize(
    "text,expected",
    [
        ("yes", "positive"),
        ("Yes, it's working now, thanks!", "positive"),
        ("it works now", "positive"),
        ("No", "negative"),
        ("No, it's still broken.", "negative"),
        ("not working, thanks", "negative"),  # negative wins over positive
        ("notification sent", "unclear"),     # 'no' inside 'notification' must NOT match
        ("", "unclear"),
        ("maybe later", "unclear"),
    ],
)
def test_classify_reply(text, expected):
    assert FollowupService.classify_reply(text) == expected
