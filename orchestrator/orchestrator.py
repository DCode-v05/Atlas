"""
orchestrator.py — the "host agent" that coordinates the specialist agents.
==========================================================================

The orchestrator is an A2A *client*. It does NOT do travel knowledge itself —
instead it:

  1. PARSES the user's free-text request into structured fields, using the LLM.
  2. DISCOVERS each specialist by fetching its Agent Card (capabilities).
  3. DELEGATES a tailored sub-task to all three specialists *in parallel*,
     using the A2A `message/stream` method so we can watch progress live.
  4. SYNTHESISES the three answers into one polished trip plan, using the LLM.

Every interesting step is reported through an async `emit(event)` callback so a
UI (or the CLI) can visualise the whole A2A conversation as it happens.

This file demonstrates the core A2A value proposition: independent agents,
each discoverable and callable over HTTP, composed by a coordinator that only
needs their Agent Cards and URLs.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from common.a2a import A2AClient
from common.config import SPECIALISTS, specialist_urls
from common.llm import chat, extract_json, using_real_llm

# An emit callback receives one dict-shaped event. Default: do nothing.
EmitFn = Callable[[dict], Awaitable[None]]


async def _noop(_event: dict) -> None:
    return None


# --------------------------------------------------------------------------
# Step 1 — understand the request (LLM turns free text into structured fields)
# --------------------------------------------------------------------------
PARSE_SYSTEM = (
    "You convert a traveler's free-text request into JSON. Respond with ONLY a "
    'JSON object with exactly these keys: "destination" (string), "days" '
    '(integer), "interests" (array of short strings), "travelStyle" (one of '
    '"budget", "mid-range", "luxury"). Infer sensible defaults if unstated '
    "(days=3, travelStyle=\"mid-range\")."
)


async def parse_request(user_request: str) -> dict:
    raw = await chat(PARSE_SYSTEM, user_request, tag="parse",
                     json_mode=True, temperature=0.0, max_tokens=300)
    data = extract_json(raw)
    try:
        days = int(data.get("days") or 3)
    except (TypeError, ValueError):
        days = 3
    interests = data.get("interests") or ["highlights"]
    if isinstance(interests, str):
        interests = [interests]
    return {
        "destination": (data.get("destination") or "your destination").strip(),
        "days": max(1, min(days, 21)),
        "interests": interests,
        "travelStyle": (data.get("travelStyle") or "mid-range").strip(),
    }


# --------------------------------------------------------------------------
# Step 3 — the sub-task we send to each specialist
# --------------------------------------------------------------------------
def _prompt_for(key: str, parsed: dict) -> str:
    dest = parsed["destination"]
    days = parsed["days"]
    interests = ", ".join(parsed["interests"])
    style = parsed["travelStyle"]
    if key == "destination":
        return f"Tell me about {dest} for a traveler interested in {interests}."
    if key == "itinerary":
        return (f"Plan a {days}-day {style} itinerary for {dest} focused on "
                f"{interests}.")
    if key == "budget":
        return (f"Estimate a {style} budget and a packing list for a {days}-day "
                f"trip to {dest}.")
    if key == "weather":
        # phrased "...to {dest}." so the weather agent can recover the place
        # name with a simple regex (no LLM) and pass it to its MCP tool.
        return f"Weather outlook and packing advice for a {days}-day trip to {dest}."
    return f"Help with a {days}-day trip to {dest}."


# --------------------------------------------------------------------------
# Step 4 — combine everything into one plan
# --------------------------------------------------------------------------
SYNTH_SYSTEM = (
    "You are a friendly travel concierge. You are given a traveler's request and "
    "several specialist write-ups (a destination overview, a day-by-day "
    "itinerary, a budget guide, and a live-weather & packing guide). Merge them "
    "into ONE clean, well-structured trip plan in Markdown. Use a title, a "
    "one-paragraph intro, then clear sections: '## Overview', '## Day-by-day "
    "Itinerary', '## Weather & What to Pack', '## Budget'. Keep any real forecast "
    "figures from the weather input. Do not repeat yourself, do not mention that "
    "you received separate inputs, and keep it tidy."
)


async def synthesize(user_request: str, parsed: dict, results: dict) -> str:
    combined = (
        f"Traveler's request: {user_request}\n\n"
        f"--- DESTINATION OVERVIEW ---\n{results.get('destination', '')}\n\n"
        f"--- ITINERARY ---\n{results.get('itinerary', '')}\n\n"
        f"--- BUDGET ---\n{results.get('budget', '')}\n\n"
        f"--- WEATHER & PACKING (live data) ---\n{results.get('weather', '')}\n"
    )
    return await chat(SYNTH_SYSTEM, combined, tag="synthesize", max_tokens=1800)


# --------------------------------------------------------------------------
# The full orchestration
# --------------------------------------------------------------------------
async def plan_trip(user_request: str, emit: Optional[EmitFn] = None) -> dict:
    emit = emit or _noop
    await emit({"type": "start", "request": user_request,
                "usingRealLLM": using_real_llm()})

    # 1) understand
    parsed = await parse_request(user_request)
    await emit({"type": "parsed", "parsed": parsed})

    # 2) discover specialists via their Agent Cards. This is resilient: if an
    #    agent is offline, we flag it and carry on with whoever answered
    #    (return_exceptions=True stops one bad agent from killing the trip).
    urls = specialist_urls()
    clients = [A2AClient(u) for u in urls]
    keys = [s["key"] for s in SPECIALISTS]
    discovered = await asyncio.gather(
        *[c.get_card() for c in clients], return_exceptions=True)

    cards: dict = {}                 # key -> AgentCard, only for agents that answered
    online_payload = []
    for i, res in enumerate(discovered):
        if isinstance(res, Exception):
            await emit({"type": "agent_error", "agent": keys[i],
                        "message": f"offline ({res})"})
        else:
            cards[keys[i]] = res
            online_payload.append({"key": keys[i], "url": urls[i],
                                   "card": res.model_dump(exclude_none=True)})
    await emit({"type": "discovered", "agents": online_payload})

    # 3) delegate to every ONLINE specialist in parallel (streaming)
    results: dict[str, str] = {}

    async def run_one(key: str) -> None:
        client = clients[keys.index(key)]
        sub_request = _prompt_for(key, parsed)
        await emit({"type": "delegate", "agent": key,
                    "agentName": cards[key].name, "request": sub_request})
        artifact_text = ""
        try:
            async for event in client.stream(sub_request):
                # forward the raw A2A event so the UI can show real protocol data
                await emit({"type": "a2a_event", "agent": key, "event": event})
                if event.get("kind") == "artifact-update":
                    artifact_text = event["artifact"]["parts"][0]["text"]
            results[key] = artifact_text
            await emit({"type": "agent_done", "agent": key, "text": artifact_text})
        except Exception as exc:  # a mid-stream failure shouldn't kill the trip
            results[key] = f"_({cards[key].name} was unavailable: {exc})_"
            await emit({"type": "agent_error", "agent": key, "message": str(exc)})

    await asyncio.gather(*[run_one(k) for k in cards])

    # 4) synthesise the final plan
    await emit({"type": "synthesis_start"})
    final = await synthesize(user_request, parsed, results)
    await emit({"type": "final", "text": final})

    return {"parsed": parsed, "results": results, "final": final}
