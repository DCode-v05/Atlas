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


async def logic(user_text: str, ctx):
    """Streaming handler: run plan_trip and narrate the composition.

    This is the SAME `plan_trip` the web UI uses in-process. We use the incoming
    A2A `contextId` as the conversation id, so multi-turn works over A2A too: a
    caller that reuses the same contextId continues the same conversation. We
    bridge plan_trip's `emit(event)` callback into A2A Progress notes."""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            result = await plan_trip(user_text, emit, context_id=ctx.context_id)
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
        elif t == "recall":
            if event.get("preferences"):
                yield Progress(f"Recalled {len(event['preferences'])} known user preference(s).")
            if not event["isFirst"]:
                yield Progress(f"Continuing the conversation (turn {event['turnCount'] + 1}).")
        elif t == "understood":
            b = event["beliefs"]
            yield Progress(f"Understood — goal: {event['intent']['goal']}")
        elif t == "selection":
            yield Progress(f"Running {len(event['selected'])} agent(s); reusing "
                           f"{len(event['reused'])} cached result(s).")
        elif t == "delegate":
            yield Progress(f"Consulting {event['agentName']} over A2A — intent: {event['intent']}")
        elif t == "agent_reused":
            yield Progress(f"{event['agent'].title()} unchanged — reusing its cached answer.")
        elif t == "agent_done":
            yield Progress(f"{event['agent'].title()} agent finished.")
        elif t == "agent_error":
            yield Progress(f"{event['agent'].title()} agent unavailable — continuing.")
        elif t == "synthesis_start":
            yield Progress("Combining all responses into one plan…")
    await task
    yield final_text   # the final synthesised plan (last yield = the answer)


app = build_agent_app(CARD, logic)

if __name__ == "__main__":
    run_agent(app, PORT)
