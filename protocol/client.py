"""
protocol/client.py — a minimal A2A client for talking TO an agent.

This is what makes an agent *also* a client of other agents: a manager that
delegates simply holds an A2AClient per report.

Performance note: we keep ONE httpx client per thread (each of our agent servers
runs in its own thread with its own event loop) and reuse it across calls, so
connections are pooled instead of re-established on every message.
"""
from __future__ import annotations

import json
import threading
from typing import AsyncIterator, Optional

import httpx

from protocol.models import (AGENT_CARD_PATH, AgentCard, Message, Task, dump,
                             new_id, user_text_message)

_local = threading.local()


def _http() -> httpx.AsyncClient:
    """A per-thread (hence per-event-loop) reusable httpx client."""
    c = getattr(_local, "client", None)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
        _local.client = c
    return c


async def post_json(url: str, payload: dict, timeout: float = 10) -> dict:
    """POST JSON over the per-thread client (used for HR calls). {} on failure."""
    try:
        r = await _http().post(url, json=payload, timeout=timeout)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


class A2AClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/") + "/"

    async def get_card(self) -> AgentCard:
        r = await _http().get(self.base_url.rstrip("/") + AGENT_CARD_PATH, timeout=10)
        r.raise_for_status()
        return AgentCard(**r.json())

    def _req(self, method: str, message: Message) -> dict:
        return {"jsonrpc": "2.0", "id": new_id("rpc"), "method": method,
                "params": {"message": dump(message)}}

    async def send(self, message: Message) -> Task:
        r = await _http().post(self.base_url, json=self._req("message/send", message))
        r.raise_for_status()
        return Task(**r.json()["result"])

    async def stream(self, message: Message) -> AsyncIterator[dict]:
        async with _http().stream("POST", self.base_url,
                                  json=self._req("message/stream", message),
                                  timeout=None) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                frame = json.loads(line[len("data:"):].strip())
                ev = frame.get("result")
                if ev is not None:
                    yield ev

    # -- convenience for the common "send text + org envelope" case ---------
    async def send_text(self, text: str, *, context_id: Optional[str] = None,
                        metadata: Optional[dict] = None,
                        reference_task_ids: Optional[list] = None,
                        task_id: Optional[str] = None) -> Task:
        return await self.send(user_text_message(
            text, context_id=context_id, metadata=metadata,
            reference_task_ids=reference_task_ids, task_id=task_id))

    async def stream_text(self, text: str, *, context_id: Optional[str] = None,
                         metadata: Optional[dict] = None,
                         reference_task_ids: Optional[list] = None,
                         task_id: Optional[str] = None) -> AsyncIterator[dict]:
        async for ev in self.stream(user_text_message(
                text, context_id=context_id, metadata=metadata,
                reference_task_ids=reference_task_ids, task_id=task_id)):
            yield ev

    async def get_task(self, task_id: str) -> Optional[Task]:
        r = await _http().post(self.base_url, json={
            "jsonrpc": "2.0", "id": new_id("rpc"),
            "method": "tasks/get", "params": {"id": task_id}}, timeout=10)
        r.raise_for_status()
        res = r.json().get("result")
        return Task(**res) if res else None

    async def cancel(self, task_id: str) -> Optional[Task]:
        r = await _http().post(self.base_url, json={
            "jsonrpc": "2.0", "id": new_id("rpc"),
            "method": "tasks/cancel", "params": {"id": task_id}}, timeout=10)
        r.raise_for_status()
        res = r.json().get("result")
        return Task(**res) if res else None
