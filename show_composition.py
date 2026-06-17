"""
show_composition.py — agents composing, shown on the wire.
==========================================================

A2A agents can be clients of OTHER A2A agents. Here we talk to a SINGLE agent —
the orchestrator (the "Trip Concierge") — over A2A. Internally it calls four
other A2A agents for us (one of which uses an MCP tool). From our side it looks
like hiring one capable agent; that's composition.

Run the whole stack first (`python launch.py`), then in another terminal:

    python show_composition.py "Plan a 5-day food and temples trip to Kyoto"
"""
from __future__ import annotations

import asyncio
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from common.a2a import A2AClient
from common.config import orchestrator_url


async def main(request: str) -> None:
    base = orchestrator_url()
    client = A2AClient(base)

    print("=" * 72)
    print("  DISCOVERY — the orchestrator is itself an A2A agent")
    print("=" * 72)
    try:
        card = await client.get_card()
    except Exception as exc:
        print(f"Could not reach the orchestrator agent at {base} ({exc}).")
        print("Start the whole stack first:  python launch.py")
        return
    print(json.dumps(card.model_dump(exclude_none=True), indent=2, ensure_ascii=False))

    print("\n" + "=" * 72)
    print(f"  CALLING IT over A2A (message/stream): \"{request}\"")
    print("  Watch: ONE call to us, but it coordinates 4 agents internally.")
    print("=" * 72)

    final_text = ""
    async for event in client.stream(request):
        kind = event.get("kind")
        if kind == "task":
            print(f"  · task {event['status']['state']}")
        elif kind == "status-update":
            if event.get("final"):
                print("  · completed (final)")
            else:
                msg = event["status"].get("message")
                note = " ".join(p["text"] for p in msg["parts"]) if msg else ""
                print(f"  · {note}")
        elif kind == "artifact-update":
            final_text = event["artifact"]["parts"][0]["text"]

    print("\n" + "=" * 72)
    print("  FINAL PLAN (returned by the orchestrator agent)")
    print("=" * 72)
    print(final_text)


if __name__ == "__main__":
    req = " ".join(sys.argv[1:]) or "Plan a 5-day food and temples trip to Kyoto"
    asyncio.run(main(req))
