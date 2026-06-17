"""
gateway/app.py — the web gateway that powers the browser UI.
============================================================

The browser only ever talks to THIS server (same origin), which keeps things
simple and avoids cross-origin (CORS) issues. The gateway, in turn, is an A2A
client of the three specialist agents (via the orchestrator).

Endpoints
---------
GET  /                 -> the single-page UI (static files in ../web)
GET  /api/status       -> whether we're using real Groq or the offline mock
GET  /api/agents       -> the three Agent Cards (for the "agent network" panel)
POST /api/plan         -> runs the orchestrator and STREAMS every A2A event
                          to the browser as Server-Sent Events, so the UI can
                          visualise the live agent-to-agent conversation.

Run it with:  python -m gateway.app
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from common.a2a import A2AClient
from common.config import (GATEWAY_PORT, ORCHESTRATOR_AGENT, SPECIALISTS,
                           WEATHER_MCP, base_url, orchestrator_url)
from common.llm import model_name, using_real_llm
from orchestrator.orchestrator import plan_trip

import socket


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Smart Trip Planner — A2A Gateway")


@app.get("/api/status")
async def api_status():
    """Tell the UI whether real AI or the offline mock is in use, and whether
    the weather MCP tool server is reachable."""
    return JSONResponse({
        "usingRealLLM": using_real_llm(),
        "model": model_name() if using_real_llm() else "offline-mock",
        "mcpOnline": _port_open(WEATHER_MCP["port"]),
    })


async def _probe(key: str, url: str, role: str) -> dict:
    """Fetch one agent's Agent Card (A2A discovery), flagging offline agents."""
    entry = {"key": key, "url": url, "role": role, "online": False, "card": None}
    try:
        card = await A2AClient(url).get_card()
        entry["card"] = card.model_dump(exclude_none=True)
        entry["online"] = True
    except Exception as exc:
        entry["error"] = str(exc)
    return entry


@app.get("/api/agents")
async def api_agents():
    """Discover the orchestrator + every specialist by fetching their Agent
    Cards. The orchestrator is itself an A2A agent (it just composes others)."""
    specialists = [await _probe(s["key"], base_url(s["port"]), "specialist")
                   for s in SPECIALISTS]
    orchestrator = await _probe(ORCHESTRATOR_AGENT["key"], orchestrator_url(), "orchestrator")
    return JSONResponse({"orchestrator": orchestrator, "agents": specialists})


@app.post("/api/plan")
async def api_plan(request: Request):
    """Run the orchestrator and stream its events to the browser as SSE."""
    body = await request.json()
    user_request = (body.get("request") or "").strip()

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            await plan_trip(user_request, emit)
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)  # sentinel: tells the generator to stop

    async def event_generator():
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            yield 'data: {"type": "done"}\n\n'
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Serve the static single-page app at "/" (registered LAST so the /api routes
# above take precedence over the catch-all static mount).
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=GATEWAY_PORT, log_level="warning")
