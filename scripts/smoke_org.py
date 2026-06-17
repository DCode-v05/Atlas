"""
scripts/smoke_org.py — end-to-end check of the Phase-2 communication core.

Boots a pooled runtime + the gateway in-process (deterministic mock LLM, no API
key needed), runs one mission, and asserts: it completes, produces a result, the
metrics add up, the expected performative handoffs happened on the wire, and the
org chart grew a CEO + a team.

    python scripts/smoke_org.py
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time

os.environ["ATLAS_FORCE_MOCK"] = "1"          # deterministic; before importing llm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import uvicorn

import config
from gateway.app import create_app
from memory import store
from org.runtime import PooledRuntime


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((config.HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


async def main() -> int:
    rt = PooledRuntime(size=8)
    rt.start()
    app = create_app(rt)
    server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=config.GATEWAY_PORT,
                                           log_level="warning"))
    server.install_signal_handlers = lambda: None
    threading.Thread(target=server.run, daemon=True).start()
    assert _wait_port(config.GATEWAY_PORT), "gateway did not start"
    gw = config.gateway_url()

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(gw + "/api/run", json={
            "mission": "Design and spec a privacy-first smart doorbell",
            "topology": "hierarchical"})
        run_id = r.json()["runId"]
        print("run:", run_id)

        state = None
        for _ in range(220):
            state = (await c.get(gw + f"/api/run-state?run={run_id}")).json()
            if state.get("status") == "done":
                break
            await asyncio.sleep(0.4)

    assert state and state.get("status") == "done", f"run did not finish: {state}"
    assert state.get("final"), "no final result produced"
    m = state["metrics"]
    print("metrics:", m)
    assert m["messages"] > 0, "no messages counted"
    assert m["headcount"] >= 5, f"expected a recursive team, got headcount={m['headcount']}"
    assert m["maxDepth"] >= 2, f"expected recursion (depth>=2), got {m['maxDepth']}"

    events = store.load_events(run_id)
    perfs = {e.get("performative") for e in events if e.get("type") == "message"}
    print("performatives seen:", sorted(p for p in perfs if p))
    for p in ("cfp", "propose", "accept-proposal", "refuse", "request", "inform"):
        assert p in perfs, f"missing performative on the wire: {p}"

    org = state["org"]
    roles = sorted(v.get("role") for v in org.values())
    depths = sorted({v.get("depth") for v in org.values()})
    print("org roles:", roles)
    print("org depths:", depths)
    assert "CEO" in roles and len(org) >= 5, f"org didn't grow enough: {org}"

    print("final (first 120 chars):", (state["final"] or "")[:120].replace("\n", " "))
    print("ORG SMOKE OK")
    rt.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
