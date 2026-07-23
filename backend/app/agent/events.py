"""Event emitter: persists agent events (durable, replayable) and publishes them
to the in-process bus for live SSE consumers."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AgentEventType
from app.core.ids import new_event_id
from app.db.models import AgentEvent
from app.repositories.agent_repository import AgentRepository
from app.services.notification_service import EventBus


class EventEmitter:
    def __init__(self, session: AsyncSession, ticket_id: str, run_id: str | None, bus: EventBus) -> None:
        self.agents = AgentRepository(session)
        self.ticket_id = ticket_id
        self.run_id = run_id
        self.bus = bus

    async def emit(self, event_type: AgentEventType, data: dict) -> None:
        seq = await self.agents.next_seq(self.ticket_id)
        event = AgentEvent(
            id=new_event_id(),
            ticket_id=self.ticket_id,
            run_id=self.run_id,
            seq=seq,
            type=event_type.value,
            data=data,
        )
        await self.agents.add_event(event)
        await self.bus.publish(
            self.ticket_id,
            {"id": event.id, "seq": seq, "type": event_type.value, "data": data, "run_id": self.run_id},
        )
