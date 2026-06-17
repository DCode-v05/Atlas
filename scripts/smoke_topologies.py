"""
scripts/smoke_topologies.py — run the SAME mission under all three topologies and
prove they (a) compose the identical team but (b) communicate differently.

This is the heart of the comparison mode: org composition is held constant
(deterministic mock), so any metric delta is attributable to the topology alone.

    python scripts/smoke_topologies.py
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time

os.environ["ATLAS_FORCE_MOCK"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import uvicorn

import config
from gateway.app import create_app
from memory import store
from org.runtime import PooledRuntime

MISSION = "Design and spec a privacy-first smart doorbell"
TOPOS = ["hierarchical", "mesh", "group"]


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((config.HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


async def _run(c, gw, topo):
    r = await c.post(gw + "/api/run", json={"mission": MISSION, "topology": topo})
    run_id = r.json()["runId"]
    state = {}
    for _ in range(300):
        state = (await c.get(gw + f"/api/run-state?run={run_id}")).json()
        if state.get("status") == "done":
            break
        await asyncio.sleep(0.4)
    await asyncio.sleep(0.4)             # let the run fully release its agents
    return run_id, state


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

    summary = {}
    async with httpx.AsyncClient(timeout=180) as c:
        for topo in TOPOS:
            run_id, state = await _run(c, gw, topo)
            assert state.get("status") == "done", f"{topo} did not finish"
            assert state.get("final"), f"{topo} produced no result"
            events = store.load_events(run_id)
            perfs = [e.get("performative") for e in events if e.get("type") == "message"]
            contexts = {e.get("contextId") for e in events if e.get("type") == "message"}
            meetings = [e for e in events if e.get("type") == "meeting"]
            roles = sorted(v.get("role") for v in state["org"].values())
            summary[topo] = {"messages": state["metrics"]["messages"],
                             "headcount": state["metrics"]["headcount"],
                             "maxDepth": state["metrics"]["maxDepth"],
                             "tokens": state["metrics"]["tokens"],
                             "roles": roles, "queryRef": perfs.count("query-ref"),
                             "meetings": len(meetings), "contexts": len(contexts)}
            print(f"{topo:13} msgs={summary[topo]['messages']:3} "
                  f"head={summary[topo]['headcount']} depth={summary[topo]['maxDepth']} "
                  f"consults={summary[topo]['queryRef']} meetings={summary[topo]['meetings']} "
                  f"contexts={summary[topo]['contexts']}")

    # (a) fairness: identical org composition across topologies
    base = summary["hierarchical"]["roles"]
    for t in TOPOS:
        assert summary[t]["roles"] == base, f"composition differs for {t}: {summary[t]['roles']} != {base}"
        assert summary[t]["headcount"] == summary["hierarchical"]["headcount"], f"headcount differs for {t}"

    # (b) distinctness: each topology has its signature
    assert summary["hierarchical"]["queryRef"] == 0, "hierarchical should have no peer consults"
    assert summary["mesh"]["queryRef"] > 0, "mesh should have peer consults"
    assert summary["mesh"]["messages"] > summary["hierarchical"]["messages"], "mesh should chat more"
    assert summary["group"]["meetings"] >= 2, "group should hold meetings"
    assert summary["group"]["contexts"] > summary["hierarchical"]["contexts"], \
        "group should open extra meeting contexts"

    print("\nTOPOLOGY SMOKE OK — same team, different conversations")
    rt.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
