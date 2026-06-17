"""
scripts/demo_mission.py — scripted acceptance run (real Groq, GROUP topology).

Runs ONE mission and VERIFIES the expected agent-to-agent handoffs on the wire:

  * onboarding ....... propose -> accept-proposal           (role conferral)
  * hiring (CNP) ..... cfp -> propose -> accept-proposal -> refuse
  * delegation ....... request -> inform
  * group ............ turns sharing ONE meeting contextId
  * mission-named lead the top agent's title is derived from the mission
  * caps ............. headcount / depth within limits

Requires GROQ_API_KEY (this build is real-LLM only — no mock).

    python scripts/demo_mission.py
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import httpx
import uvicorn

import config
from gateway.app import create_app
from llm.client import using_real_llm
from memory import store
from org.runtime import PooledRuntime

MISSION = "Plan a small community book fair"
OK, BAD = "[ok]", "[!!]"
_fails = []


def check(cond, label):
    print(f"   {OK if cond else BAD} {label}")
    if not cond:
        _fails.append(label)


def _wait_port(port, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((config.HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def _tree(org):
    kids = {}
    for aid, m in org.items():
        kids.setdefault(m.get("parentId"), []).append((aid, m))
    lines = ["      - Board (you)"]

    def walk(parent, depth):
        for aid, m in sorted(kids.get(parent, []), key=lambda x: x[0]):
            lines.append("      " + "  " * depth + f"- {m.get('role')}  ({aid})")
            walk(aid, depth + 1)
    walk("Board", 0)
    return "\n".join(lines)


async def main():
    if not using_real_llm():
        print("GROQ_API_KEY required — this build is real-LLM only (no mock). Set it in .env.")
        return 1

    rt = PooledRuntime(size=8)
    rt.start()
    app = create_app(rt)
    server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=config.GATEWAY_PORT, log_level="warning"))
    server.install_signal_handlers = lambda: None
    threading.Thread(target=server.run, daemon=True).start()
    assert _wait_port(config.GATEWAY_PORT), "gateway did not start"
    gw = config.gateway_url()

    print("=" * 66)
    print(f"  ATLAS acceptance run (real LLM · group) — {MISSION}")
    print("=" * 66)

    async with httpx.AsyncClient(timeout=300) as c:
        run_id = (await c.post(gw + "/api/run", json={"mission": MISSION, "topology": "group"})).json()["runId"]
        state = {}
        for _ in range(600):
            state = (await c.get(gw + f"/api/run-state?run={run_id}")).json()
            if state.get("status") == "done":
                break
            await asyncio.sleep(0.5)

    events = store.load_events(run_id)
    msgs = [e for e in events if e.get("type") == "message"]
    perf = Counter(m.get("performative") for m in msgs)
    meet_ctxs = {m.get("contextId") for m in msgs if str(m.get("contextId")).startswith("meet-")}
    org = state.get("org", {})
    m = state.get("metrics", {})
    lead = next((v.get("role") for v in org.values() if v.get("parentId") == "Board"), None)

    print(_tree(org))
    print("      performatives: " + "  ".join(f"{k}×{v}" for k, v in sorted(perf.items()) if k))
    print(f"      lead title: {lead!r}  ·  headcount {m.get('headcount')}  ·  depth {m.get('maxDepth')}"
          f"  ·  {m.get('elapsedMs', 0) / 1000:.1f}s  ·  {m.get('tokens')} tokens")

    check(state.get("status") == "done" and bool(state.get("final")), "mission completed with a result")
    check(bool(lead) and lead != "CEO", "lead agent has a mission-derived title (not 'CEO')")
    check(perf.get("propose", 0) and perf.get("accept-proposal", 0), "onboarding: propose -> accept-proposal")
    check(perf.get("cfp", 0) > 0, "hiring auction ran (cfp -> propose -> accept/refuse)")
    check(perf.get("request", 0) and perf.get("inform", 0), "delegation: request -> inform")
    check(len(meet_ctxs) >= 1, "group: turns shared a dedicated meeting contextId")
    check(perf.get("query-ref", 0) > 0, "agents talked to EACH OTHER (peer query-ref consults)")
    card_events = [e for e in events if e.get("type") == "card"]
    check(len(card_events) >= 2, f"Agent Cards discovered over A2A ({len(card_events)} cards)")
    check(m.get("headcount", 0) >= 2, "a team was hired")
    check(m.get("headcount", 0) <= config.MAX_HEADCOUNT and m.get("maxDepth", 0) <= config.MAX_DELEGATION_DEPTH,
          "caps respected (headcount + depth)")

    print("=" * 66)
    print(f"  FAILED {len(_fails)} check(s): " + "; ".join(_fails) if _fails
          else "  ALL CHECKS PASSED — the organisation communicates as designed.")
    print("=" * 66)
    rt.shutdown()
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
