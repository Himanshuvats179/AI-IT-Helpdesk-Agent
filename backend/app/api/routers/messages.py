"""Inbound user messages (chat replies, OTP-in-chat, follow-up answers)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.agent.runner import AgentRunner
from app.api.deps import get_runner
from app.schemas.ticket import MessageCreate

router = APIRouter(prefix="/v1/tickets", tags=["messages"])


@router.post("/{ticket_id}/messages")
async def post_message(
    ticket_id: str,
    payload: MessageCreate,
    runner: AgentRunner = Depends(get_runner),
) -> dict:
    """Route a user message based on ticket state and (re)run the agent as needed."""
    return await runner.handle_user_message(ticket_id, payload.body, author=payload.requester_upn)
