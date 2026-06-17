"""
scripts/smoke_compare.py — exercise the /api/compare endpoint end-to-end.

Verifies the comparison kicks off three runs, they all complete, they compose the
IDENTICAL team (determinism held), and the metric deltas are present.

    python scripts/smoke_compare.py
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

    async with httpx.AsyncClient(timeout=240) as c:
        r = (await c.post(gw + "/api/compare", json={"mission": "Build a tiny notes app"})).json()
        runs = r["runs"]
        print("compare kicked off:", [(x["topology"], x["runId"]) for x in runs])

        states = {}
        for _ in range(400):
            states = {x["topology"]: (await c.get(gw + f"/api/run-state?run={x['runId']}")).json()
                      for x in runs}
            if all(s.get("status") == "done" for s in states.values()):
                break
            await asyncio.sleep(0.5)

    assert all(s.get("status") == "done" for s in states.values()), "not all runs finished"
    comp = {}
    for x in runs:
        s = states[x["topology"]]
        roles = sorted(v.get("role") for v in s["org"].values())
        comp[x["topology"]] = {"messages": s["metrics"]["messages"],
                               "headcount": s["metrics"]["headcount"], "roles": roles}
        print(f"  {x['topology']:13} messages={s['metrics']['messages']:3} "
              f"headcount={s['metrics']['headcount']} elapsed={s['metrics']['elapsedMs']/1000:.1f}s")

    base = comp["hierarchical"]["roles"]
    for t in comp:
        assert comp[t]["roles"] == base, f"composition differs for {t}: {comp[t]['roles']} != {base}"
    assert comp["mesh"]["messages"] > comp["hierarchical"]["messages"], "mesh should chat more"
    print("COMPARE SMOKE OK")
    rt.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
