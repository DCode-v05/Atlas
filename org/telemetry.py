"""
org/telemetry.py — how an agent narrates what it does, back to the gateway.

The org is decentralised: messages fly directly between employee processes. To
make all of it *observable* in one place, every agent POSTs a small structured
event to the gateway (POST /api/ingest) whenever something notable happens. The
gateway timestamps, persists and broadcasts these to the browser over SSE, and
derives the metrics + progress ledger from them.

Convention: the SENDER of a message emits a `message` event for its outbound act
(its performative); the RECEIVER emits its own reply as another `message` event.
So a request/response round-trip shows up as two events — exactly what you want
to see on the wire.
"""
from __future__ import annotations

import httpx

from config import gateway_url


class Reporter:
    """An employee's telemetry line to the gateway, bound to one run."""

    def __init__(self, run_id: str, agent_id: str, role_getter, *, gw: str | None = None):
        self.run_id = run_id
        self.agent_id = agent_id
        self._role = role_getter          # callable -> current role string
        self.gw = (gw or gateway_url()).rstrip("/")

    async def emit(self, type: str, **fields) -> None:
        payload = {"type": type, "runId": self.run_id,
                   "from": self.agent_id, "fromRole": self._role(), **fields}
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(self.gw + "/api/ingest", json=payload)
        except Exception:
            pass                           # telemetry must never break the work

    # -- convenience wrappers -------------------------------------------------
    async def message(self, *, to: str, to_role: str, performative: str,
                      intent: str = "", scope: str = "", text: str = "",
                      depth: int = 0, context_id: str = "") -> None:
        await self.emit("message", to=to, toRole=to_role, performative=performative,
                        intent=intent, scope=scope, text=text[:280], depth=depth,
                        contextId=context_id)

    async def status(self, state: str, note: str = "") -> None:
        await self.emit("status", agentId=self.agent_id, state=state, note=note)

    async def llm(self, tokens: int, purpose: str) -> None:
        await self.emit("llm", agentId=self.agent_id, tokens=tokens, purpose=purpose)

    async def onboarded(self, role: str, goal: str, depth: int, parent_id: str) -> None:
        await self.emit("onboard", agentId=self.agent_id, role=role, goal=goal,
                        depth=depth, parentId=parent_id)

    async def ledger(self, **fields) -> None:
        await self.emit("ledger", **fields)

    async def cap(self, kind: str, message: str) -> None:
        await self.emit("cap", kind=kind, message=message)
