"""Identity verification (OTP submission) endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import AgentRunner
from app.api.deps import get_runner, get_session
from app.schemas.tool import VerificationRequest
from app.services.verification_service import VerificationService

router = APIRouter(prefix="/v1/tickets", tags=["verification"])


@router.post("/{ticket_id}/verify")
async def verify_identity(
    ticket_id: str,
    payload: VerificationRequest,
    session: AsyncSession = Depends(get_session),
    runner: AgentRunner = Depends(get_runner),
) -> dict:
    service = VerificationService(session)
    token = await service.verify(
        ticket_id=ticket_id, code=payload.code, challenge_id=payload.challenge_id
    )
    await session.commit()
    # resume the agent now that identity is verified
    runner.schedule(ticket_id, "verified")
    return {"status": "verified", "subject": token.subject}
