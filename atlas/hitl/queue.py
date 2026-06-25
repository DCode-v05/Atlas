"""The single global human-in-the-loop approval queue.

When the policy engine returns ESCALATE, the owning agent parks its task at
``input-required`` and drops a request here. One operator (the control tower)
approves or denies; the orchestrator is suspended on an ``asyncio.Future`` that
this queue resolves — a faithful A2A input-required → resume.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from atlas.a2a.ids import utcnow
from atlas.events import EventBroker, EventType, HitlRequestedPayload, HitlResolvedPayload, IntentView
from atlas.org.ext_models import HitlRequest, ShareOutcome


class HitlQueue:
    def __init__(self, broker: EventBroker) -> None:
        self.broker = broker
        self.pending: dict[str, HitlRequest] = {}
        self.resolved: list[HitlRequest] = []
        self._futures: dict[str, asyncio.Future] = {}
        self.dbwriter = None  # set by build_runtime; durable write-through when persistence is on

    def create(self, req: HitlRequest) -> asyncio.Future:
        """Enqueue a request, emit ``hitl.requested``, return a future to await."""
        self.pending[req.request_id] = req
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - only outside an event loop
            loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._futures[req.request_id] = fut
        self.broker.emit(
            EventType.HITL_REQUESTED,
            HitlRequestedPayload(
                request_id=req.request_id,
                task_id=req.task_id,
                context_id=req.context_id,
                owner=req.owner_agent_id,
                requester=req.requester_agent_id,
                item_id=req.item_id,
                item_title=req.item_title,
                sensitivity=req.sensitivity.value,
                intent=IntentView(
                    motivation=req.intent.motivation,
                    purpose_tag=req.intent.purpose_tag.value,
                    requested_topic=req.intent.requested_topic,
                    declared_scope=req.intent.declared_scope.value,
                ),
                proposed_outcome=req.proposed_outcome.value,
                reason=req.reason,
            ),
            context_id=req.context_id,
        )
        if self.dbwriter is not None:
            self.dbwriter.record("hitl_create", {
                "request_id": req.request_id, "task_id": req.task_id, "context_id": req.context_id,
                "owner_agent_id": req.owner_agent_id, "requester_agent_id": req.requester_agent_id,
                "item_id": req.item_id, "item_title": req.item_title, "sensitivity": req.sensitivity.value,
                "proposed_outcome": req.proposed_outcome.value, "reason": req.reason,
            })
        return fut

    async def wait(self, request_id: str, timeout: float = 0.0) -> HitlRequest:
        fut = self._futures[request_id]
        if timeout and timeout > 0:
            done, _ = await asyncio.wait({fut}, timeout=timeout)
            if not done:
                self.resolve(request_id, approved=False, outcome=ShareOutcome.DENY, decided_by="timeout")
        return await fut

    def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        outcome: Optional[ShareOutcome] = None,
        decided_by: str = "control-tower",
    ) -> Optional[HitlRequest]:
        req = self.pending.pop(request_id, None)
        if req is None:
            return None
        req.state = "approved" if approved else "denied"
        req.decided_by = decided_by
        req.decided_outcome = (outcome or (ShareOutcome.SHARE if approved else ShareOutcome.DENY))
        req.decided_at = utcnow()
        self.resolved.append(req)
        self.broker.emit(
            EventType.HITL_RESOLVED,
            HitlResolvedPayload(
                request_id=request_id,
                decision=req.state,
                outcome=req.decided_outcome.value,
                decided_by=decided_by,
            ),
            context_id=req.context_id,
        )
        if self.dbwriter is not None:
            self.dbwriter.record("hitl_resolve", {
                "request_id": request_id, "state": req.state,
                "decided_by": decided_by, "decided_outcome": req.decided_outcome.value,
            })
        fut = self._futures.get(request_id)
        if fut is not None and not fut.done():
            fut.set_result(req)
        return req

    def list_pending(self) -> list[HitlRequest]:
        return list(self.pending.values())
