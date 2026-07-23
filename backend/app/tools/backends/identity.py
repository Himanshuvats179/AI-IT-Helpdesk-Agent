"""Identity / directory backend (mock AD).

Each method models a least-privilege service operation. Deterministic failure
injection (subject containing 'fail') keeps tests stable without randomness.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.exceptions import ToolExecutionError

_PRIVILEGED = {
    "admin@corp.com",
    "administrator@corp.com",
    "root@corp.com",
    "ceo@corp.com",
    "domain.admin@corp.com",
}


@runtime_checkable
class IdentityBackend(Protocol):
    async def get_account_status(self, subject: str) -> dict: ...
    async def is_privileged_account(self, subject: str) -> bool: ...
    async def reset_password(self, subject: str) -> dict: ...
    async def unlock_account(self, subject: str) -> dict: ...


class MockIdentityBackend:
    def __init__(self) -> None:
        # subjects that are currently locked (seeded so the unlock demo works)
        self._locked: set[str] = {"demo.user@corp.com", "jordan.lee@corp.com"}

    @staticmethod
    def _guard(subject: str) -> None:
        if "fail" in subject.lower():
            raise ToolExecutionError(f"Directory service error for {subject}")

    async def get_account_status(self, subject: str) -> dict:
        self._guard(subject)
        return {
            "subject": subject,
            "enabled": True,
            "locked": subject.lower() in self._locked,
            "mfa_enabled": True,
            "password_expired": subject.lower().endswith("expired@corp.com"),
            "last_login": "2026-06-14T08:12:00Z",
            "is_privileged": subject.lower() in _PRIVILEGED,
        }

    async def is_privileged_account(self, subject: str) -> bool:
        return subject.lower() in _PRIVILEGED

    async def reset_password(self, subject: str) -> dict:
        self._guard(subject)
        return {
            "status": "reset",
            "subject": subject,
            "delivery": "A temporary credential was sent to the registered factor out-of-band.",
            "must_change_at_next_login": True,
        }

    async def unlock_account(self, subject: str) -> dict:
        self._guard(subject)
        self._locked.discard(subject.lower())
        return {"status": "unlocked", "subject": subject, "locked": False}
