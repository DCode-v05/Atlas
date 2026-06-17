"""
scripts/smoke_protocol.py — validate the pure A2A protocol layer in-process.

Uses httpx's ASGITransport to call the FastAPI app WITHOUT spawning a server,
so it's fast and dependency-free. Exercises discovery, message/send,
message/stream and input-required.

    python scripts/smoke_protocol.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from protocol.models import AgentCard, AgentSkill
from protocol.server import NeedInput, Progress, build_agent_app


async def _send(client, method, text):
    req = {"jsonrpc": "2.0", "id": "1", "method": method,
           "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": text}]}}}
    r = await client.post("/", json=req)
    r.raise_for_status()
    return r.json()["result"]


async def main() -> int:
    async def echo(text):
        return f"echo: {text}"

    async def streaming(text, ctx):
        yield Progress("step 1")
        yield Progress("step 2")
        yield f"done: {text}"

    async def asker(text):
        return NeedInput("Which colour?")

    card = AgentCard(name="Smoke", description="smoke-test agent", url="http://x/",
                     skills=[AgentSkill(id="echo", name="Echo", description="echoes input")])

    # --- discovery + message/send ---
    app = build_agent_app(card, echo)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/.well-known/agent-card.json")
        r.raise_for_status()
        cardj = r.json()
        assert cardj["protocolVersion"] == "0.3.0", cardj
        assert cardj["name"] == "Smoke"
        res = await _send(c, "message/send", "hi")
        assert res["kind"] == "task" and res["status"]["state"] == "completed", res
        assert res["artifacts"][0]["parts"][0]["text"] == "echo: hi", res
        print("[ok] discovery + message/send ->", res["status"]["state"])

    # --- input-required ---
    app_ask = build_agent_app(card, asker)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_ask), base_url="http://t") as c:
        res = await _send(c, "message/send", "paint it")
        assert res["status"]["state"] == "input-required", res
        assert "colour" in res["status"]["message"]["parts"][0]["text"].lower()
        print("[ok] input-required ->", res["status"]["state"])

    # --- message/stream ---
    app2 = build_agent_app(card, streaming)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t") as c:
        req = {"jsonrpc": "2.0", "id": "2", "method": "message/stream",
               "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "go"}]}}}
        kinds, final_text = [], None
        async with c.stream("POST", "/", json=req) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    ev = json.loads(line[5:].strip())["result"]
                    kinds.append(ev.get("kind"))
                    if ev.get("kind") == "artifact-update":
                        final_text = ev["artifact"]["parts"][0]["text"]
        assert kinds[0] == "task", kinds
        assert "status-update" in kinds and "artifact-update" in kinds, kinds
        assert final_text == "done: go", final_text
        print("[ok] message/stream ->", kinds)

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
