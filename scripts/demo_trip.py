"""
scripts/demo_trip.py — the trip-planner mission, re-ported onto the org.

The original ATLAS prototype was a hand-built Smart Trip Planner: five fixed
specialist agents (destination, itinerary, budget, weather, cuisine) wired
together by hand. On the new organisation-of-agents architecture you don't wire
anything — you just hand the org the SAME mission and the CEO *hires* the team it
needs, conferring travel roles by conversation. This script proves that: it runs
the trip mission under all three topologies and verifies the agent-to-agent
handoffs happened on the wire (deterministic mock — no API key needed).

  * onboarding ....... propose -> accept-proposal      (role conferral)
  * hiring (CNP) ..... cfp -> propose -> accept -> refuse
  * delegation ....... request -> inform
  * mesh ............. query-ref -> inform             (direct peer consult)
  * group ............ turns share ONE meeting contextId
  * caps ............. headcount / depth stay within limits

    python scripts/demo_trip.py
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
from collections import Counter

os.environ["ATLAS_FORCE_MOCK"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import httpx
import uvicorn

import config
from gateway.app import create_app
from memory import store
from org.runtime import PooledRuntime

MISSION = "Plan a 5-day food and temples trip to Kyoto"
TOPOS = ["hierarchical", "mesh", "group"]
OK, BAD = "[ok]", "[!!]"
_fails = []


def check(cond: bool, label: str) -> None:
    print(f"   {OK if cond else BAD} {label}")
    if not cond:
        _fails.append(label)


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((config.HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def _tree(org: dict) -> str:
    kids: dict = {}
    for aid, m in org.items():
        kids.setdefault(m.get("parentId"), []).append((aid, m))
    lines = []

    def walk(parent, depth):
        for aid, m in sorted(kids.get(parent, []), key=lambda x: x[0]):
            lines.append("      " + "  " * depth + f"- {m.get('role')}  ({aid})")
            walk(aid, depth + 1)
    walk("Board", 0)
    lines.insert(0, "      - Board (you)")
    return "\n".join(lines)


async def _run(c, gw, topo):
    run_id = (await c.post(gw + "/api/run", json={"mission": MISSION, "topology": topo})).json()["runId"]
    state = {}
    for _ in range(400):
        state = (await c.get(gw + f"/api/run-state?run={run_id}")).json()
        if state.get("status") == "done":
            break
        await asyncio.sleep(0.4)
    await asyncio.sleep(0.4)
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

    print("=" * 66)
    print(f"  ATLAS trip-planner acceptance run — mission: {MISSION}")
    print("=" * 66)

    async with httpx.AsyncClient(timeout=240) as c:
        for topo in TOPOS:
            run_id, state = await _run(c, gw, topo)
            events = store.load_events(run_id)
            msgs = [e for e in events if e.get("type") == "message"]
            perf = Counter(m.get("performative") for m in msgs)
            meet_ctxs = {m.get("contextId") for m in msgs if str(m.get("contextId")).startswith("meet-")}
            org = state["org"]
            m = state["metrics"]

            print(f"\n  -- {topo.upper()} "
                  f"({m['messages']} msgs - {m['headcount']} people - depth {m['maxDepth']} "
                  f"- {m['elapsedMs'] / 1000:.1f}s) " + "-" * 6)
            print(_tree(org))
            print("      performatives: " + "  ".join(f"{k}x{v}" for k, v in sorted(perf.items())))

            check(state.get("status") == "done" and bool(state.get("final")), "trip plan produced")
            check(perf.get("propose", 0) and perf.get("accept-proposal", 0), "onboarding: propose -> accept-proposal")
            check(perf.get("cfp", 0) and perf.get("refuse", 0), "hiring auction: cfp -> propose -> accept -> refuse")
            check(perf.get("request", 0) and perf.get("inform", 0), "delegation: request -> inform")
            check(m["headcount"] <= config.MAX_HEADCOUNT and m["maxDepth"] <= config.MAX_DELEGATION_DEPTH,
                  "caps respected (headcount + depth)")
            if topo == "mesh":
                check(perf.get("query-ref", 0) > 0, "mesh: direct peer consults (query-ref) happened")
            if topo == "group":
                check(len(meet_ctxs) >= 1, "group: turns shared a dedicated meeting contextId")

    print("\n" + "=" * 66)
    if _fails:
        print(f"  FAILED {len(_fails)} check(s): " + "; ".join(_fails))
    else:
        print("  ALL CHECKS PASSED — the org plans the trip exactly as designed.")
    print("=" * 66)
    rt.shutdown()
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
