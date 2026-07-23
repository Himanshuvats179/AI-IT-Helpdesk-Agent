"""Identity step-up (OTP) verification — the gate in front of privileged tools.

A verification token is subject-bound, short-TTL and single-use. The code is
'delivered out-of-band' to the user's pre-registered factor (mocked here). In
demo mode (``OTP_DEMO_CODE``) a fixed code is used so the flow can be completed
end-to-end without a real SMS/MFA provider — but the subject-binding, expiry and
single-use logic are all real.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import VerificationError
from app.core.ids import new_token_id, utcnow
from app.db.models import VerificationToken
from app.repositories.user_repository import UserRepository
from app.repositories.verification_repository import VerificationRepository

_MAX_ATTEMPTS = 5


@dataclass
class Challenge:
    challenge_id: str
    factor: str
    expires_in_seconds: int
    demo_code: str | None = None


def _hash_code(secret: str, challenge_id: str, code: str) -> str:
    # HMAC (keyed) rather than a bare hash: a 6-digit OTP has only ~1e6 possible
    # values, so an unkeyed digest in a leaked column is brute-forceable offline
    # in milliseconds. The server-side secret defeats that.
    return hmac.new(
        secret.encode(), f"{challenge_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


class VerificationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repo = VerificationRepository(session)
        self.users = UserRepository(session)
        self._otp_secret = self.settings.otp_secret.get_secret_value()

    async def create_challenge(self, *, ticket_id: str, subject: str) -> Challenge:
        user = await self.users.ensure(subject)
        factor = user.registered_factor or "sms:•••-•••-0000"

        code = self.settings.otp_demo_code or f"{secrets.randbelow(1_000_000):06d}"
        challenge_id = new_token_id()
        token = VerificationToken(
            ticket_id=ticket_id,
            subject=subject,
            challenge_id=challenge_id,
            code_hash=_hash_code(self._otp_secret, challenge_id, code),
            factor=factor,
            status="pending",
            expires_at=utcnow() + timedelta(seconds=self.settings.otp_ttl_seconds),
        )
        await self.repo.create(token)
        return Challenge(
            challenge_id=challenge_id,
            factor=factor,
            expires_in_seconds=self.settings.otp_ttl_seconds,
            demo_code=self.settings.otp_demo_code,
        )

    async def verify(self, *, ticket_id: str, code: str, challenge_id: str | None = None) -> VerificationToken:
        token = await self.repo.get_active_for_ticket(ticket_id)
        if token is None:
            raise VerificationError("No active verification challenge for this ticket.")
        if challenge_id and token.challenge_id != challenge_id:
            raise VerificationError("Challenge id mismatch.")
        if token.expires_at <= utcnow():
            token.status = "expired"
            await self.session.flush()
            raise VerificationError("Verification code expired. Request a new one.")
        if token.attempts >= _MAX_ATTEMPTS:
            token.status = "expired"
            await self.session.flush()
            raise VerificationError("Too many attempts. Challenge locked.")

        token.attempts += 1
        if not hmac.compare_digest(
            token.code_hash, _hash_code(self._otp_secret, token.challenge_id, code)
        ):
            await self.session.flush()
            raise VerificationError("Incorrect verification code.")

        token.status = "verified"
        token.verified_at = utcnow()
        await self.session.flush()
        return token

    async def get_valid_token(self, *, ticket_id: str, subject: str) -> VerificationToken | None:
        """Return a verified, unconsumed, subject-bound token (the policy gate)."""
        return await self.repo.get_verified_unconsumed(ticket_id, subject)

    async def consume(self, token: VerificationToken) -> None:
        token.status = "consumed"
        token.consumed_at = utcnow()
        await self.session.flush()
