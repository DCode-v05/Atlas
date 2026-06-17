"""
scripts/smoke_dynamic.py — prove the DYNAMIC runtime: a real OS process per hire.

Runs one group mission with ATLAS_RUNTIME=dynamic and checks it completes over
genuinely separate employee processes. Requires GROQ_API_KEY (real-LLM only).

    python scripts/smoke_dynamic.py
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time

os.environ["ATLAS_RUNTIME"] = "dynamic"
os.environ["ATLAS_MAX_HEADCOUNT"] = "8"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import uvicorn

import config
from gateway.app import create_app
from llm.client import using_real_llm
from org.runtime import make_runtime


def _wait_port(port, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((config.HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


async def main():
    if not using_real_llm():
        print("GROQ_API_KEY required — this build is real-LLM only (no mock).")
        return 1

    rt = make_runtime()
    print("runtime:", type(rt).__name__)
    assert type(rt).__name__ == "DynamicRuntime", "expected the dynamic runtime"
    rt.start()
    try:
        app = create_app(rt)
        server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=config.GATEWAY_PORT, log_level="warning"))
        server.install_signal_handlers = lambda: None
        threading.Thread(target=server.run, daemon=True).start()
        assert _wait_port(config.GATEWAY_PORT), "gateway did not start"
        gw = config.gateway_url()

        async with httpx.AsyncClient(timeout=300) as c:
            run_id = (await c.post(gw + "/api/run", json={"mission": "Plan a small community book fair",
                                                          "topology": "group"})).json()["runId"]
            state = {}
            for _ in range(600):
                state = (await c.get(gw + f"/api/run-state?run={run_id}")).json()
                if state.get("status") == "done":
                    break
                await asyncio.sleep(0.5)

        assert state.get("status") == "done", f"run did not finish: {state.get('status')}"
        assert state.get("final"), "no final result"
        print("metrics:", state["metrics"])
        assert state["metrics"]["headcount"] >= 2
        procs = rt.members()
        print("real processes spawned:", len(procs))
        assert len(procs) >= 2, "no employee processes were spawned"
        print("DYNAMIC SMOKE OK")
        return 0
    finally:
        rt.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
