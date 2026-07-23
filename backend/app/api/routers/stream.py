"""Server-Sent Events: live agent-trace stream for a ticket.

On connect we subscribe first (so nothing is missed), replay the persisted event
backlog, then stream live events — de-duplicated by sequence number.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_bus
from app.db.session import session_scope
from app.repositories.agent_repository import AgentRepository
from app.services.notification_service import EventBus

router = APIRouter(prefix="/v1/tickets", tags=["stream"])


@router.get("/{ticket_id}/stream")
async def stream_events(
    ticket_id: str, request: Request, bus: EventBus = Depends(get_bus)
) -> EventSourceResponse:
    async def event_generator():
        # Subscribe first so live events emitted during backlog replay are queued
        # (and de-duplicated by seq), never missed.
        async with bus.subscribe(ticket_id) as queue:
            # 1) replay persisted backlog in its own short-lived session, which is
            #    released before the (potentially long-lived) live loop begins.
            async with session_scope() as session:
                backlog = await AgentRepository(session).list_events(ticket_id, 0)
            last_seq = 0
            for ev in backlog:
                last_seq = max(last_seq, ev.seq)
                yield {
                    "event": ev.type,
                    "id": str(ev.seq),
                    "data": json.dumps({"type": ev.type, "seq": ev.seq, "data": ev.data}),
                }

            # 2) live stream until the client disconnects or the task is cancelled.
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield {"event": "ping", "data": "{}"}
                        continue
                    seq = item.get("seq")
                    if seq is not None and seq <= last_seq:
                        continue  # already delivered (e.g. backlog overlap)
                    if seq is not None:
                        last_seq = max(last_seq, seq)
                    yield {
                        "event": item.get("type", "message"),
                        "id": str(seq if seq is not None else ""),
                        "data": json.dumps(item),
                    }
            except asyncio.CancelledError:
                # sse_starlette cancels this task on disconnect; let the
                # `subscribe` context manager unwind and detach our queue.
                raise

    return EventSourceResponse(event_generator())
