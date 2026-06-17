"""
gateway/app.py — the one server the browser talks to, and the org's nerve centre.

Responsibilities:
  * serve the single-page UI
  * HR: hand a free employee to whoever asks (POST /hr/allocate) — the only bit
    of central provisioning; role conferral + work happen agent-to-agent
  * telemetry: ingest every agent's events (POST /api/ingest), timestamp+persist
    them, fold them into the live org chart / metrics / ledgers, and broadcast
    them to the browser over SSE (GET /api/stream)
  * drive a mission: onboard the CEO and hand over the mission (POST /api/run)

The gateway never does the agents' thinking — it observes and provisions.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
from llm.client import model_name, using_real_llm
from memory import store
from org import ceo, ledger
from org.metrics import Metrics
from org.registry import OrgChart
from pathlib import Path
from protocol.models import new_id, now_iso

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class RunState:
    def __init__(self, run_id: str, mission: str, topology: str):
        self.run_id = run_id
        self.mission = mission
        self.topology = topology
        self.context_id = run_id                 # one mission = one conversation thread
        self.seq = 0
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.org = OrgChart()
        self.metrics = Metrics()
        self.ledgers = ledger.blank()
        self.start = time.perf_counter()
        self.final: str | None = None
        self.done = False


def create_app(runtime) -> FastAPI:
    store.init_db()
    app = FastAPI(title="ATLAS — organisation-of-agents gateway")
    runs: dict[str, RunState] = {}
    app.state.runtime = runtime
    app.state.runs = runs

    async def emit(rs: RunState, ev: dict) -> None:
        rs.seq += 1
        ev = {**ev, "seq": rs.seq, "ts": now_iso()}
        rs.events.append(ev)
        rs.org.apply(ev)
        rs.metrics.apply(ev)
        ledger.apply(rs.ledgers, ev)
        if ev.get("type") == "ledger":
            store.save_ledgers(rs.run_id, rs.ledgers["task"], rs.ledgers["progress"])
        store.add_event(rs.run_id, ev["seq"], ev["ts"], ev)
        for q in list(rs.subscribers):
            q.put_nowait(ev)

    # ---- status -----------------------------------------------------------
    @app.get("/api/status")
    async def api_status():
        return JSONResponse({
            "usingRealLLM": using_real_llm(), "model": model_name(),
            "company": config.COMPANY_NAME, "runtime": config.RUNTIME,
            "caps": {"headcount": config.MAX_HEADCOUNT,
                     "depth": config.MAX_DELEGATION_DEPTH,
                     "tokenBudget": config.TOKEN_BUDGET},
            "poolSize": len(runtime.members())})

    # ---- HR: allocate a free employee ------------------------------------
    @app.post("/hr/allocate")
    async def hr_allocate(request: Request):
        body = await request.json()
        run_id = body.get("runId")
        role = body.get("roleHint", "Specialist")
        requester = body.get("requester", "?")
        depth = int(body.get("depth", 0) or 0)
        res = await asyncio.to_thread(runtime.allocate, run_id, role, requester, depth)
        rs = runs.get(run_id)
        if res and rs:
            await emit(rs, {"type": "hire", "agentId": res["agentId"], "role": role,
                            "parentId": requester, "depth": depth})
            return JSONResponse(res)
        return JSONResponse({})               # at capacity / unknown run

    # ---- HR: Contract-Net auction support --------------------------------
    @app.post("/hr/candidates")
    async def hr_candidates(request: Request):
        """Reserve up to k free employees for an auction (the manager interviews
        them with a cfp, then releases the losers)."""
        body = await request.json()
        cands = await asyncio.to_thread(runtime.reserve_candidates,
                                        body.get("runId"), int(body.get("k", 2)))
        return JSONResponse({"candidates": cands})

    @app.post("/hr/release")
    async def hr_release(request: Request):
        body = await request.json()
        runtime.release(body.get("agentId"))
        return JSONResponse({"ok": True})

    # ---- telemetry ingest -------------------------------------------------
    @app.post("/api/ingest")
    async def api_ingest(request: Request):
        ev = await request.json()
        rs = runs.get(ev.get("runId"))
        if rs and not rs.done:
            await emit(rs, ev)
        return JSONResponse({"ok": True})

    # Provisioning can block (the dynamic runtime spawns a process); offload it
    # so the gateway event loop keeps serving telemetry while a hire spins up.
    async def alloc_async(run_id, role_hint="", requester="", depth=0):
        return await asyncio.to_thread(runtime.allocate, run_id, role_hint, requester, depth)

    # ---- the shared run driver -------------------------------------------
    async def drive(rs: RunState) -> None:
        await emit(rs, {"type": "run", "phase": "started", "mission": rs.mission,
                        "topology": rs.topology})
        try:
            final = await ceo.run_mission(alloc_async, lambda ev: emit(rs, ev),
                                          run_id=rs.run_id, mission=rs.mission,
                                          context_id=rs.context_id, topology=rs.topology)
        except Exception as exc:                           # noqa: BLE001
            final = f"(run failed: {exc})"
        rs.final = final
        rs.metrics.set_elapsed((time.perf_counter() - rs.start) * 1000)
        rs.done = True
        store.finish_run(rs.run_id, final)
        await emit(rs, {"type": "run", "phase": "done", "final": final,
                        "metrics": rs.metrics.snapshot()})
        for m in runtime.members():
            if m["runId"] == rs.run_id:
                runtime.release(m["agentId"])

    def _new_run(mission: str, topology: str) -> RunState:
        run_id = new_id("run")
        rs = RunState(run_id, mission, topology)
        runs[run_id] = rs
        store.create_run(run_id, mission, topology, now_iso())
        return rs

    # ---- start a single mission ------------------------------------------
    @app.post("/api/plan")
    @app.post("/api/run")
    async def api_run(request: Request):
        body = await request.json()
        mission = (body.get("mission") or body.get("request") or config.DEFAULT_MISSION).strip()
        rs = _new_run(mission, body.get("topology", "group"))
        asyncio.create_task(drive(rs))
        return JSONResponse({"runId": rs.run_id, "contextId": rs.context_id})

    # ---- live event stream (SSE) -----------------------------------------
    @app.get("/api/stream")
    async def api_stream(run: str):
        rs = runs.get(run)
        if rs is None:
            return JSONResponse({"error": "unknown run"}, status_code=404)

        async def gen():
            q: asyncio.Queue = asyncio.Queue()
            rs.subscribers.add(q)
            backlog = list(rs.events)
            last = backlog[-1]["seq"] if backlog else 0
            for ev in backlog:
                yield f"data: {json.dumps(ev)}\n\n"
            if rs.done:
                rs.subscribers.discard(q)
                return
            try:
                while True:
                    ev = await q.get()
                    if ev["seq"] <= last:
                        continue
                    yield f"data: {json.dumps(ev)}\n\n"
                    if ev.get("type") == "run" and ev.get("phase") in ("done", "error"):
                        break
            finally:
                rs.subscribers.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                                          "X-Accel-Buffering": "no"})

    # ---- snapshots (for restore / the comparison view) -------------------
    @app.get("/api/agents")
    async def api_agents(run: str = ""):
        rs = runs.get(run)
        return JSONResponse({"org": rs.org.snapshot() if rs else {},
                             "pool": runtime.members()})

    @app.get("/api/run-state")
    async def api_run_state(run: str = ""):
        rs = runs.get(run)
        if rs is None:
            return JSONResponse({"exists": bool(store.get_run(run)),
                                 "run": store.get_run(run),
                                 "ledgers": store.load_ledgers(run),
                                 "events": store.load_events(run)})
        return JSONResponse({"exists": True, "mission": rs.mission, "topology": rs.topology,
                             "status": "done" if rs.done else "running", "final": rs.final,
                             "metrics": rs.metrics.snapshot(), "ledgers": rs.ledgers,
                             "org": rs.org.snapshot()})

    # static SPA last, so /api/* and /hr/* win
    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


def main() -> None:
    from org.runtime import make_runtime
    import uvicorn
    rt = make_runtime()
    rt.start()
    app = create_app(rt)
    uvicorn.run(app, host=config.HOST, port=config.GATEWAY_PORT, log_level="warning")


if __name__ == "__main__":
    main()
