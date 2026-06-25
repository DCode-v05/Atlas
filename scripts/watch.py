"""Watch a task's A2A stream in plain English — one command, no curl/JSON.

Usage:
    uv run python scripts/watch.py "your prompt here"
    uv run python scripts/watch.py            # uses a default prompt

It sends the prompt, then live-streams the task via the A2A SubscribeToTask
endpoint (GET /api/tasks/{id}/subscribe), printing one readable line per frame
and exiting when the task reaches a terminal state.
"""

from __future__ import annotations

import json
import sys

import httpx

BASE = "http://localhost:8000"

_STATE_NOTE = {
    "submitted": "task created",
    "working": "agents working…",
    "input-required": "waiting for your approval (HITL) — approve in the UI, or run: cancel",
    "completed": "done ✓",
    "failed": "failed ✗",
    "canceled": "canceled ✗",
}


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "what is the engineering API style guide?"

    with httpx.Client(timeout=None) as c:
        r = c.post(f"{BASE}/api/prompt", json={"prompt": prompt})
        data = r.json()
        if data.get("rejected"):
            print(f"✗ blocked at the gate: {data.get('reason')}")
            return
        tid = data["task_id"]
        print(f'→ sent: "{prompt}"')
        print(f"  routed to {data['routed_to_name']} ({data['routed_to_role']})")
        print(f"  task {tid} — streaming live:\n")

        event = None
        with c.stream("GET", f"{BASE}/api/tasks/{tid}/subscribe") as resp:
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    payload = line.split(":", 1)[1].strip()
                    if not payload or payload == "{}":
                        continue
                    frame = json.loads(payload)
                    _print_frame(event, frame, tid)
                    su = frame.get("statusUpdate")
                    if su and su.get("final"):
                        break
        print("\n(stream closed — task reached a terminal state)")


def _print_frame(event: str | None, frame: dict, tid: str) -> None:
    if frame.get("task"):
        st = frame["task"]["status"]["state"]
        print(f"  • snapshot   → {st}")
    elif frame.get("statusUpdate"):
        su = frame["statusUpdate"]
        st = su["status"]["state"]
        note = _STATE_NOTE.get(st, "")
        flag = "  [final]" if su.get("final") else ""
        line = f"  • status     → {st}{flag}"
        if note:
            line += f"   ({note})"
        print(line)
        msg = su["status"].get("message")
        if msg and msg.get("parts"):
            txt = msg["parts"][0].get("text", "").strip()
            if txt:
                print(f"                 “{txt}”")
    elif frame.get("message"):
        m = frame["message"]
        txt = (m.get("parts") or [{}])[0].get("text", "").strip()
        if txt:
            print(f"  • message    → {txt[:100]}")
    elif frame.get("artifactUpdate"):
        a = frame["artifactUpdate"]["artifact"]
        print(f"  • artifact   → {a.get('name', 'output')}")


if __name__ == "__main__":
    main()
