"""DbWriter — durable write-through persistence for the runtime record.

The point-of-record components (Router, HitlQueue, orchestrator, push service)
call the **synchronous, non-blocking** ``record()`` to enqueue a durable row at
the moment it is created — the Router is the chokepoint every message/task passes
through, so persisting there (like metrics) cannot be bypassed. A single async
worker drains the **unbounded** queue and writes in order, so nothing is dropped.

That ordering matters: a bounded broker subscriber drops its oldest event under
backpressure (see ``EventBroker._offer``), which could drop a parent (task) while
keeping a child (message). So the broker tap is reserved here ONLY for genuinely
fire-and-forget telemetry — the high-volume ``trace.span`` stream — where a gap is
acceptable. Durable rows never travel through it.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from atlas.a2a.ids import utcnow
from atlas.db.models import (
    ConversationRow,
    HitlRow,
    MessageRow,
    PushConfigRow,
    ShareDecisionRow,
    TaskRow,
    TraceSpanRow,
)
from atlas.events import EventBroker, EventType


def _now() -> int:
    return int(utcnow().timestamp())


class DbWriter:
    def __init__(self, db) -> None:
        self.db = db
        self._q: asyncio.Queue = asyncio.Queue()  # unbounded — durable writes are never dropped
        self._broker: Optional[EventBroker] = None
        self._sub: Optional[asyncio.Queue] = None
        self._worker: Optional[asyncio.Task] = None
        self._tele: Optional[asyncio.Task] = None
        self.written = 0

    def record(self, kind: str, payload: dict) -> None:
        """Enqueue a durable row at the point of record — sync-safe and never blocks/drops."""
        try:
            self._q.put_nowait((kind, dict(payload)))
        except Exception:  # pragma: no cover — unbounded queue, put_nowait can't be full
            pass

    async def start(self, broker: EventBroker) -> None:
        self._broker = broker
        self._sub = broker.subscribe()  # telemetry tap (trace spans only)
        self._worker = asyncio.create_task(self._run())
        self._tele = asyncio.create_task(self._telemetry())

    async def stop(self) -> None:
        for t in (self._worker, self._tele):
            if t is not None:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._worker = self._tele = None
        if self._broker is not None and self._sub is not None:
            self._broker.unsubscribe(self._sub)
            self._sub = None

    async def _telemetry(self) -> None:
        assert self._sub is not None
        while True:
            evt = await self._sub.get()
            if evt.event == EventType.TRACE_SPAN.value:
                self.record("trace_span", evt.data)

    async def _run(self) -> None:
        while True:
            kind, payload = await self._q.get()
            try:
                async with self.db.session() as s:
                    await self._apply(s, kind, payload)
                    await s.commit()
                self.written += 1
            except Exception:  # best-effort durability — a single bad row never stalls the worker
                pass

    async def _apply(self, s, kind: str, p: dict) -> None:
        if kind == "conversation":
            if await s.get(ConversationRow, p["context_id"]) is None:  # header is immutable once written
                s.add(ConversationRow(
                    context_id=p["context_id"], prompt=p.get("prompt", ""), kind=p.get("kind", "user"),
                    routed_to=p.get("routed_to"), routed_to_name=p.get("routed_to_name", ""),
                    task_id=p.get("task_id"), created_at=_now(),
                ))
        elif kind == "task":
            row = await s.get(TaskRow, p["id"])
            if row is None:
                row = TaskRow(id=p["id"], context_id=p["context_id"], created_at=_now())
                s.add(row)
            row.state = p["state"]
            if p.get("summary"):  # keep the completion summary; don't clobber it on plain state ticks
                row.summary = p["summary"]
            row.updated_at = _now()
        elif kind == "message":
            s.add(MessageRow(
                id=p["id"], context_id=p.get("context_id"), task_id=p.get("task_id"), sender=p["sender"],
                recipients=p.get("recipients") or [], mode=p.get("mode", "individual"), role=p.get("role", "agent"),
                text=p.get("text", ""), thinking=p.get("thinking"), intent=p.get("intent"),
                thread_id=p.get("thread_id"), group_id=p.get("group_id"), ts=_now(),
            ))
        elif kind == "share_decision":
            s.add(ShareDecisionRow(
                context_id=p.get("context_id"), kind=p["kind"], item_id=p.get("item_id"), title=p.get("title"),
                sender=p.get("sender"), recipient=p.get("recipient"), sensitivity=p.get("sensitivity"),
                rule_id=p.get("rule_id"), reason=p.get("reason"), summary=p.get("summary"), ts=_now(),
            ))
        elif kind == "hitl_create":
            s.add(HitlRow(
                request_id=p["request_id"], task_id=p.get("task_id"), context_id=p.get("context_id"),
                owner_agent_id=p.get("owner_agent_id"), requester_agent_id=p.get("requester_agent_id"),
                item_id=p.get("item_id"), item_title=p.get("item_title"), sensitivity=p.get("sensitivity"),
                proposed_outcome=p.get("proposed_outcome"), reason=p.get("reason"), state="pending", created_at=_now(),
            ))
        elif kind == "hitl_resolve":
            row = await s.get(HitlRow, p["request_id"])
            if row is not None:
                row.state = p.get("state", row.state)
                row.decided_by = p.get("decided_by")
                row.decided_outcome = p.get("decided_outcome")
                row.decided_at = _now()
        elif kind == "push_config":
            row = await s.get(PushConfigRow, p["id"])
            if row is None:
                row = PushConfigRow(id=p["id"])
                s.add(row)
            row.task_id = p.get("task_id")
            row.url = p.get("url")
            row.token = p.get("token")
            row.authentication = p.get("authentication")
        elif kind == "push_config_delete":
            row = await s.get(PushConfigRow, p["id"])
            if row is not None:
                await s.delete(row)
        elif kind == "trace_span":
            if await s.get(TraceSpanRow, p["span_id"]) is None:
                s.add(TraceSpanRow(
                    span_id=p["span_id"], context_id=p.get("context_id"), agent_id=p.get("agent_id"),
                    kind=p.get("kind"), summary=p.get("summary"), live=bool(p.get("live")),
                    detail=p.get("detail"), ts=p.get("ts"),
                ))
