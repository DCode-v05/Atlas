"""
orchestrator/agent.py — the orchestrator, exposed as its OWN A2A agent.
=======================================================================

This is what demonstrates **agents composing**. The orchestrator is normally
driven in-process by the web gateway (for the rich UI). Here we wrap the very
same `plan_trip` brain as a standalone A2A server, so the whole crew can be
"hired" like any single agent:

    a client --(A2A)--> THIS orchestrator agent --(A2A)--> 4 specialist agents
                                                              (one of which also
                                                               uses an MCP tool)

It uses the streaming-handler style: it narrates each coordination step as a
Progress note, then returns the final synthesised plan. Run it with:

    python -m orchestrator.agent          # then see show_composition.py
"""
from __future__ import annotations

import asyncio

from common.a2a import AgentCard, AgentSkill, Progress, build_agent_app, run_agent
from common.config import ORCHESTRATOR_AGENT
from orchestrator.orchestrator import plan_trip

PORT = ORCHESTRATOR_AGENT["port"]

CARD = AgentCard(
    name="Trip Concierge (Orchestrator)",
    description="Plans a complete trip by coordinating specialist A2A agents "
                "(destination, itinerary, budget, weather).",
    url=f"http://127.0.0.1:{PORT}/",
    skills=[
        AgentSkill(
            id="plan_trip",
            name="Plan a Trip",
            description="Coordinate multiple specialist agents into one trip plan.",
            tags=["travel", "orchestration", "a2a"],
            examples=["Plan a 5-day food trip to Kyoto", "A romantic weekend in Rome"],
        )
    ],
)


async def logic(user_text: str):
    """Streaming handler: run plan_trip and narrate the composition.

    This is the SAME `plan_trip` the web UI uses in-process. We bridge its
    `emit(event)` callback into A2A Progress notes via a queue."""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            result = await plan_trip(user_text, emit)
            await queue.put({"type": "__final__", "text": result["final"]})
        except Exception as exc:
            await queue.put({"type": "__final__", "text": f"Sorry, planning failed: {exc}"})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    final_text = "(no plan produced)"
    while True:
        event = await queue.get()
        if event is None:
            break
        t = event.get("type")
        if t == "__final__":
            final_text = event["text"]
        elif t == "parsed":
            p = event["parsed"]
            yield Progress(f"Parsed request: {p['destination']}, {p['days']} days, {p['travelStyle']}")
        elif t == "discovered":
            names = ", ".join(a["card"]["name"] for a in event["agents"])
            yield Progress(f"Discovered {len(event['agents'])} specialist agents: {names}")
        elif t == "delegate":
            yield Progress(f"Consulting {event['agentName']} over A2A (message/stream)…")
        elif t == "agent_done":
            yield Progress(f"{event['agent'].title()} agent finished.")
        elif t == "agent_error":
            yield Progress(f"{event['agent'].title()} agent unavailable — continuing.")
        elif t == "synthesis_start":
            yield Progress("Combining all specialist responses into one plan…")
    await task
    yield final_text   # the final synthesised plan (last yield = the answer)


app = build_agent_app(CARD, logic)

if __name__ == "__main__":
    run_agent(app, PORT)
