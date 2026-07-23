"""Identity verification controls: wrong code, expiry, lockout, single-use."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.exceptions import VerificationError
from app.core.ids import utcnow
from app.db.session import session_scope
from app.repositories.verification_repository import VerificationRepository
from app.services.verification_service import VerificationService

SUBJECT = "demo.user@corp.com"


async def test_wrong_code_rejected(db):
    async with session_scope() as session:
        svc = VerificationService(session)
        await svc.create_challenge(ticket_id="tkt_v1", subject=SUBJECT)
        with pytest.raises(VerificationError):
            await svc.verify(ticket_id="tkt_v1", code="000000")
        await session.commit()


async def test_expired_code_rejected(db):
    async with session_scope() as session:
        svc = VerificationService(session)
        await svc.create_challenge(ticket_id="tkt_v2", subject=SUBJECT)
        token = await VerificationRepository(session).get_active_for_ticket("tkt_v2")
        token.expires_at = utcnow() - timedelta(seconds=1)
        await session.flush()
        with pytest.raises(VerificationError):
            await svc.verify(ticket_id="tkt_v2", code="123456")


async def test_lockout_after_max_attempts(db):
    async with session_scope() as session:
        svc = VerificationService(session)
        await svc.create_challenge(ticket_id="tkt_v3", subject=SUBJECT)
        for _ in range(5):
            with pytest.raises(VerificationError):
                await svc.verify(ticket_id="tkt_v3", code="000000")
        # locked out — even the correct code now fails
        with pytest.raises(VerificationError):
            await svc.verify(ticket_id="tkt_v3", code="123456")


async def test_token_is_single_use(db):
    async with session_scope() as session:
        svc = VerificationService(session)
        await svc.create_challenge(ticket_id="tkt_v4", subject=SUBJECT)
        await svc.verify(ticket_id="tkt_v4", code="123456")
        token = await svc.get_valid_token(ticket_id="tkt_v4", subject=SUBJECT)
        assert token is not None
        await svc.consume(token)
        assert await svc.get_valid_token(ticket_id="tkt_v4", subject=SUBJECT) is None
