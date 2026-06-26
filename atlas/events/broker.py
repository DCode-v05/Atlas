"""In-process pub/sub broker that fans realtime events out to SSE clients.

Each SSE client gets a bounded queue; if a slow client falls behind, the broker
drops that client's oldest event rather than stalling the whole org. ``emit`` is
synchronous (no await points) so both sync and async code can publish freely on
the single event loop.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from pydantic import BaseModel

from atlas.a2a.ids import utcnow
from atlas.events.schema import Event, EventType


class EventBroker:
    def __init__(self, history_size: int = 1000, queue_size: int = 2000) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._seq = 0
        self._queue_size = queue_size
        self.history: deque[Event] = deque(maxlen=history_size)

    def emit(
        self,
        event_type: EventType | str,
        payload: BaseModel | dict[str, Any] | None = None,
        *,
        context_id: str | None = None,
        org_id: str | None = None,
    ) -> Event:
        self._seq += 1
        if isinstance(payload, BaseModel):
            data = payload.model_dump(mode="json")
        else:
            data = dict(payload or {})
        if context_id is None:
            context_id = data.get("context_id")
        etype = event_type.value if isinstance(event_type, EventType) else str(event_type)
        evt = Event(event=etype, id=self._seq, ts=utcnow().isoformat(), context_id=context_id,
                    org_id=org_id, data=data)
        self.history.append(evt)
        for q in list(self._subscribers):
            self._offer(q, evt)
        return evt

    @staticmethod
    def _offer(q: asyncio.Queue, evt: Event) -> None:
        try:
            q.put_nowait(evt)
        except asyncio.QueueFull:
            try:
                q.get_nowait()  # drop oldest
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def recent(self, limit: int = 200) -> list[Event]:
        return list(self.history)[-limit:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
