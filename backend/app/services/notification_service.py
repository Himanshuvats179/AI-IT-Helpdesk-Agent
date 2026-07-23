"""In-process event bus powering live SSE agent traces.

A single-process pub/sub keyed by ticket id. The agent persists every event to
the DB (durable, replayable) *and* publishes it here for any live SSE subscriber.
For multi-process deployment this would be swapped for Redis pub/sub behind the
same interface — the rest of the app is unaffected.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class EventBus:
    def __init__(self, max_queue: int = 1000) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._max_queue = max_queue
        self._lock = asyncio.Lock()

    async def publish(self, ticket_id: str, event: dict[str, Any]) -> None:
        # Snapshot under the lock so a concurrent (un)subscribe can't mutate the
        # set mid-iteration; delivery itself happens outside the lock.
        async with self._lock:
            subscribers = list(self._subscribers.get(ticket_id, set()))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer — drop oldest, keep latest
                with _suppress():
                    queue.get_nowait()
                    queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self, ticket_id: str) -> AsyncIterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._subscribers.setdefault(ticket_id, set()).add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                subs = self._subscribers.get(ticket_id)
                if subs is not None:
                    subs.discard(queue)
                    if not subs:
                        self._subscribers.pop(ticket_id, None)


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
