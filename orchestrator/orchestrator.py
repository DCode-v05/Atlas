"""
orchestrator.py — the stateful "host brain" that coordinates the specialists.
=============================================================================

This is the brain behind both the web UI (driven in-process) and the
orchestrator A2A agent. Beyond delegating, it now has MEMORY and INTENT:

  1. RECALL    — load this conversation's prior beliefs/intent/results (by A2A
                 contextId) and the user's long-term preferences (persistent).
  2. UNDERSTAND— one LLM call updates BELIEFS {destination, days, interests,
                 style} and the INTENT {goal, constraints} behind the
                 conversation, notes which beliefs CHANGED, and extracts durable
                 user preferences. Follow-ups ("make it cheaper") update prior
                 beliefs instead of starting over.
  3. DISCOVER  — fetch each specialist's Agent Card (+ its role & motivation).
  4. SELECT    — only re-run the specialists whose inputs CHANGED (coordination
                 efficiency); reuse cached results for the rest.
  5. DELEGATE  — call selected specialists in parallel over A2A, threading the
                 contextId and a FIPA-style performative ("request" + intent),
                 with retries.
  6. SYNTHESISE— merge everything into one plan that honours the intent.
  7. PERSIST   — save beliefs/intent/results + this turn + any new preferences.

Every step is reported via the async `emit(event)` callback for the UI/CLI.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Awaitable, Callable, Optional

from common import memory
from common.a2a import A2AClient
from common.config import SPECIALISTS, specialist, specialist_urls
from common.llm import chat, extract_json, heuristic_fields, using_real_llm
from common.persona import NEGOTIATION_MODE, display_name, persona

EmitFn = Callable[[dict], Awaitable[None]]


async def _noop(_event: dict) -> None:
    return None


DEFAULT_BELIEFS = {"destination": "your destination", "days": 3,
                   "interests": ["highlights"], "travelStyle": "mid-range"}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
async def _with_retry(make_coro, *, attempts: int = 2, base_delay: float = 0.5,
                      on_retry=None):
    """Run an async thunk, retrying with exponential backoff on failure."""
    last_exc = None
    for i in range(attempts):
        try:
            return await make_coro()
        except Exception as exc:                       # noqa: BLE001
            last_exc = exc
            if on_retry and i < attempts - 1:
                await on_retry(i + 1, exc)
            if i < attempts - 1:
                await asyncio.sleep(base_delay * (2 ** i))
    raise last_exc


def _normalize_beliefs(b: dict | None) -> dict:
    b = dict(b or {})
    try:
        days = int(b.get("days") or 3)
    except (TypeError, ValueError):
        days = 3
    interests = b.get("interests") or ["highlights"]
    if isinstance(interests, str):
        interests = [interests]
    dest = (b.get("destination") or "your destination").strip() or "your destination"
    return {"destination": dest, "days": max(1, min(days, 21)),
            "interests": list(interests),
            "travelStyle": (b.get("travelStyle") or "mid-range").strip()}


# ---------------------------------------------------------------------------
# Step 2 — UNDERSTAND (beliefs + intent + changed + new preferences)
# ---------------------------------------------------------------------------
UNDERSTAND_SYSTEM = (
    "You maintain the evolving state of a trip-planning conversation. Given the "
    "prior beliefs/intent, the user's known long-term preferences, recent "
    "requests, and a NEW_MESSAGE, respond with ONLY a JSON object with keys: "
    '"beliefs": {"destination": string, "days": integer, "interests": [string], '
    '"travelStyle": "budget"|"mid-range"|"luxury"}, '
    '"intent": {"goal": string, "constraints": [string], "openQuestions": [string]}, '
    '"changed": [the belief keys that changed vs prior], '
    '"newPreferences": [durable facts worth remembering long-term, e.g. "enjoys street food"]. '
    "If NEW_MESSAGE is a follow-up (e.g. 'make it cheaper', 'add a day'), UPDATE "
    "the prior beliefs rather than starting over. Infer sensible defaults."
)


def _understand_prompt(user_request, prior_beliefs, prior_intent, prefs, turns) -> str:
    recent = [t["request"] for t in (turns or [])][-4:]
    return (
        f"PRIOR_BELIEFS: {json.dumps(prior_beliefs) if prior_beliefs else 'none (first turn)'}\n"
        f"PRIOR_INTENT: {json.dumps(prior_intent) if prior_intent else 'none'}\n"
        f"KNOWN_USER_PREFERENCES: {json.dumps(prefs) if prefs else 'none'}\n"
        f"RECENT_REQUESTS: {json.dumps(recent) if recent else 'none'}\n"
        f"NEW_MESSAGE: {user_request}\n"
    )


def _mock_understand(user_request, prior_beliefs):
    """Offline 'understand': merge a heuristic parse into the prior beliefs."""
    guess = _normalize_beliefs(heuristic_fields(user_request))
    low = user_request.lower()
    if not prior_beliefs:
        beliefs, changed = guess, list(guess.keys())
    else:
        beliefs, changed = dict(prior_beliefs), []
        if guess["destination"] != "your destination" and guess["destination"] != beliefs.get("destination"):
            beliefs["destination"] = guess["destination"]; changed.append("destination")
        rel_days = re.search(r"add\s+(\d+)\s+(?:more\s+)?days?|(\d+)\s+more\s+days?", low)
        if rel_days:                                   # "add 2 more days" -> +2
            n = int(rel_days.group(1) or rel_days.group(2))
            beliefs["days"] = max(1, min(beliefs.get("days", 3) + n, 21)); changed.append("days")
        elif re.search(r"\d+\s*[- ]?\s*day", low) and guess["days"] != beliefs.get("days"):
            beliefs["days"] = guess["days"]; changed.append("days")
        if any(w in low for w in ("budget", "cheaper", "cheap", "backpack")) and beliefs.get("travelStyle") != "budget":
            beliefs["travelStyle"] = "budget"; changed.append("travelStyle")
        elif any(w in low for w in ("luxury", "lux", "splurge")) and beliefs.get("travelStyle") != "luxury":
            beliefs["travelStyle"] = "luxury"; changed.append("travelStyle")
        new_i = [i for i in guess["interests"] if i != "highlights" and i not in beliefs.get("interests", [])]
        if new_i:
            beliefs["interests"] = list(dict.fromkeys(beliefs.get("interests", []) + new_i))
            changed.append("interests")
    beliefs = _normalize_beliefs(beliefs)
    new_prefs = [f"enjoys {i}" for i in beliefs["interests"] if i != "highlights"]
    if beliefs["travelStyle"] in ("budget", "luxury"):
        new_prefs.append(f"prefers {beliefs['travelStyle']} travel")
    return beliefs, changed, new_prefs


async def understand(user_request, prior_beliefs, prior_intent, prefs, turns) -> dict:
    if using_real_llm():
        raw = await _with_retry(lambda: chat(
            UNDERSTAND_SYSTEM,
            _understand_prompt(user_request, prior_beliefs, prior_intent, prefs, turns),
            json_mode=True, temperature=0.2, max_tokens=500))
        data = extract_json(raw) or {}
        beliefs = _normalize_beliefs({**(prior_beliefs or DEFAULT_BELIEFS), **(data.get("beliefs") or {})})
        changed = data.get("changed") or [k for k in beliefs if not prior_beliefs or beliefs.get(k) != prior_beliefs.get(k)]
        intent = data.get("intent") or {}
        new_prefs = data.get("newPreferences") or []
    else:
        beliefs, changed, new_prefs = _mock_understand(user_request, prior_beliefs)
        intent = {}
    goal = (intent.get("goal") or "").strip()
    if len(goal) < 20:                                 # ensure a descriptive goal
        goal = (f"Plan a {beliefs['travelStyle']} {beliefs['days']}-day trip to "
                f"{beliefs['destination']} focused on {', '.join(beliefs['interests'])}")
    intent = {
        "goal": goal,
        "constraints": intent.get("constraints") or [],
        "openQuestions": intent.get("openQuestions") or [],
    }
    return {"beliefs": beliefs, "intent": intent,
            "changed": list(changed), "newPreferences": list(new_prefs)}


# ---------------------------------------------------------------------------
# Step 4 — SELECT which specialists to re-run (coordination efficiency)
# ---------------------------------------------------------------------------
# Which specialists are affected when a given belief changes.
SELECTION_RULES = {
    "destination": {"destination", "itinerary", "budget", "weather", "cuisine"},
    "days":        {"itinerary", "budget", "weather"},
    "interests":   {"destination", "itinerary", "cuisine"},
    "travelStyle": {"budget", "itinerary", "cuisine"},
}


def select_agents(changed, is_first, online_keys, cached_results) -> list:
    if is_first or not cached_results:
        return list(online_keys)                 # first turn: everyone runs
    wanted: set = set()
    for field in changed:
        wanted |= SELECTION_RULES.get(field, set())
    return [k for k in online_keys if k in wanted]


def _prompt_for(key: str, beliefs: dict) -> str:
    dest, days = beliefs["destination"], beliefs["days"]
    interests = ", ".join(beliefs["interests"])
    style = beliefs["travelStyle"]
    if key == "destination":
        return f"Tell me about {dest} for a traveler interested in {interests}."
    if key == "itinerary":
        return f"Plan a {days}-day {style} itinerary for {dest} focused on {interests}."
    if key == "budget":
        return f"Estimate a {style} budget and a packing list for a {days}-day trip to {dest}."
    if key == "weather":
        return f"Weather outlook and packing advice for a {days}-day trip to {dest}."
    if key == "cuisine":
        return f"Recommend local dishes and where to eat in {dest} for a {style} traveler interested in {interests}."
    return f"Help with a {days}-day trip to {dest}."


# ---------------------------------------------------------------------------
# Step 5b — NEGOTIATE (the specialists talk to each other, in persona, over A2A)
# ---------------------------------------------------------------------------
# A bounded, sensible round-table. Each entry is (speaker, performative, to,
# instruction). Only turns whose speaker is actually present run, so it adapts
# to whoever is online / was re-run this turn. The CONTENT is generated by the
# agents themselves (in persona); the orchestrator only facilitates the order.
def _negotiation_script(present: list[str], beliefs: dict) -> list[tuple]:
    style, days = beliefs["travelStyle"], beliefs["days"]
    p = set(present)
    plan = [
        ("budget", "concern", "itinerary",
         f"You worry the {days}-day plan may strain a {style} budget. Voice your "
         "concern to Priya and suggest where to save."),
        ("itinerary", "counter", "budget",
         "Answer Sam: protect the must-do experiences but offer one concrete tweak "
         "(a swap or reorder) that cuts cost without losing the trip's soul."),
        ("weather", "inform", "itinerary",
         "Tell the team if any day's weather could disrupt outdoor plans, and which "
         "day to keep flexible."),
        ("cuisine", "propose", "budget",
         "Make the case to Sam that eating like a local (markets, street food) is "
         "cheaper AND better. Sell the vibe; don't name specific restaurants."),
        ("destination", "agree", "itinerary",
         "Wrap up: affirm the group's consensus and add one local-culture tip that "
         "ties the plan together."),
    ]
    return [t for t in plan if t[0] in p]


async def negotiate(present: list[str], beliefs: dict, *, clients, keys, cards,
                    context_id: str, emit: EmitFn) -> list[str]:
    """Run the round-table. Each turn is a REAL A2A `message/stream` call to the
    speaking agent, carrying a FIPA-style performative in the message metadata;
    the agent replies in its persona. Returns the transcript (human lines)."""
    script = _negotiation_script(present, beliefs)
    if len(present) < 2 or len(script) < 2:
        return []                                  # nothing meaningful to discuss

    await emit({"type": "negotiate_start",
                "participants": [{"key": k, "name": display_name(k)} for k in present]})
    transcript: list[str] = []
    for speaker, performative, listener, instruction in script:
        name = persona(speaker)["name"]
        so_far = "\n".join(transcript) if transcript else "(you open the discussion)"
        turn_text = (f"DISCUSSION SO FAR:\n{so_far}\n\n"
                     f"It is your turn, {name}. {instruction}")
        meta = {"mode": NEGOTIATION_MODE, "performative": performative,
                "intent": instruction, "to": listener}
        await emit({"type": "negotiate_turn", "speaker": speaker, "listener": listener,
                    "performative": performative, "speakerName": display_name(speaker),
                    "listenerName": display_name(listener)})
        client = clients[keys.index(speaker)]
        said = ""
        try:
            async for event in client.stream(turn_text, context_id=context_id, metadata=meta):
                await emit({"type": "a2a_event", "agent": speaker, "event": event})
                if event.get("kind") == "artifact-update":
                    said = event["artifact"]["parts"][0]["text"]
        except Exception as exc:                   # one bad turn never breaks the table
            await emit({"type": "agent_error", "agent": speaker,
                        "message": f"(negotiation) {exc}"})
            continue
        said = (said or "").strip()
        if said:
            transcript.append(f"{name}: {said}")
            await emit({"type": "negotiate_said", "speaker": speaker,
                        "speakerName": display_name(speaker),
                        "performative": performative, "text": said})
    await emit({"type": "negotiate_end"})
    return transcript


# ---------------------------------------------------------------------------
# Step 6 — SYNTHESISE (honour the intent)
# ---------------------------------------------------------------------------
SYNTH_SYSTEM = (
    "You are a friendly travel concierge. You are given the conversation's GOAL "
    "and CONSTRAINTS, the latest user message, and several specialist write-ups "
    "(destination overview, day-by-day itinerary, budget, a live-weather & "
    "packing guide, and a local food & dining guide). Merge them into ONE clean "
    "Markdown trip plan that satisfies the goal and respects the constraints. Use "
    "a title, a one-paragraph intro, then sections: '## Overview', "
    "'## Day-by-day Itinerary', '## Food & Dining', '## Weather & What to Pack', "
    "'## Budget'. The specialists then held a short discussion to reconcile "
    "trade-offs — HONOUR the agreements they reached (e.g. cost-saving swaps, "
    "weather-driven reordering). Keep real forecast figures. Do not repeat "
    "yourself or mention that you received separate inputs."
)


async def synthesize(user_request, beliefs, intent, results, transcript=None) -> str:
    discussion = ("\n".join(transcript) if transcript else "(no discussion needed)")
    combined = (
        f"GOAL: {intent.get('goal')}\n"
        f"CONSTRAINTS: {json.dumps(intent.get('constraints', []))}\n"
        f"LATEST_USER_MESSAGE: {user_request}\n\n"
        f"--- DESTINATION OVERVIEW ---\n{results.get('destination', '')}\n\n"
        f"--- ITINERARY ---\n{results.get('itinerary', '')}\n\n"
        f"--- FOOD & DINING ---\n{results.get('cuisine', '')}\n\n"
        f"--- BUDGET ---\n{results.get('budget', '')}\n\n"
        f"--- WEATHER & PACKING (live data) ---\n{results.get('weather', '')}\n\n"
        f"--- SPECIALISTS' ROUND-TABLE (agreements to honour) ---\n{discussion}\n"
    )
    return await _with_retry(lambda: chat(SYNTH_SYSTEM, combined, tag="synthesize",
                                          max_tokens=1800))


# ---------------------------------------------------------------------------
# The full, context-aware orchestration
# ---------------------------------------------------------------------------
async def plan_trip(user_request: str, emit: Optional[EmitFn] = None, *,
                    context_id: str, user_id: str = memory.DEFAULT_USER) -> dict:
    emit = emit or _noop
    await emit({"type": "start", "request": user_request,
                "contextId": context_id, "usingRealLLM": using_real_llm()})

    # 1) RECALL persistent state
    prior = await asyncio.to_thread(memory.load_conversation, context_id)
    prefs = await asyncio.to_thread(memory.load_user_memory, user_id)
    turns = await asyncio.to_thread(memory.load_turns, context_id)
    is_first = prior is None
    prior_beliefs = (prior or {}).get("beliefs")
    cached_results = dict((prior or {}).get("results") or {})
    await emit({"type": "recall", "isFirst": is_first, "preferences": prefs,
                "priorBeliefs": prior_beliefs, "turnCount": len(turns)})

    # 2) UNDERSTAND — update beliefs + intent, detect change, learn preferences
    u = await understand(user_request, prior_beliefs, (prior or {}).get("intent"), prefs, turns)
    beliefs, intent, changed, new_prefs = u["beliefs"], u["intent"], u["changed"], u["newPreferences"]
    await emit({"type": "understood", "beliefs": beliefs, "intent": intent, "changed": changed})
    if new_prefs:
        added = await asyncio.to_thread(memory.add_user_memory, new_prefs, user_id)
        if added:
            await emit({"type": "memory_added", "facts": added})

    # 3) DISCOVER specialists (+ their roles/motivations)
    urls = specialist_urls()
    keys = [s["key"] for s in SPECIALISTS]
    clients = [A2AClient(url) for url in urls]
    discovered = await asyncio.gather(*[c.get_card() for c in clients], return_exceptions=True)
    cards: dict = {}
    online_payload = []
    for i, res in enumerate(discovered):
        s = SPECIALISTS[i]
        if isinstance(res, Exception):
            await emit({"type": "agent_error", "agent": keys[i], "message": f"offline ({res})"})
        else:
            cards[keys[i]] = res
            online_payload.append({"key": keys[i], "url": urls[i], "role": s["role"],
                                   "motivation": s["motivation"],
                                   "card": res.model_dump(exclude_none=True)})
    await emit({"type": "discovered", "agents": online_payload})

    # 4) SELECT which specialists to re-run; reuse the rest from cache
    selected = select_agents(changed, is_first, list(cards.keys()), cached_results)
    reused = [k for k in cards if k not in selected and k in cached_results]
    await emit({"type": "selection", "selected": selected, "reused": reused, "changed": changed})
    results = dict(cached_results)
    for k in reused:
        await emit({"type": "agent_reused", "agent": k, "text": results.get(k, "")})

    # 5) DELEGATE selected specialists in parallel (contextId + performative + retry)
    async def run_one(key: str) -> None:
        client = clients[keys.index(key)]
        s = specialist(key)
        sub_request = _prompt_for(key, beliefs)
        meta = {"performative": "request", "intent": s["intent"]}
        await emit({"type": "delegate", "agent": key, "agentName": cards[key].name,
                    "request": sub_request, "intent": s["intent"]})
        captured = {"text": ""}

        async def consume():
            async for event in client.stream(sub_request, context_id=context_id, metadata=meta):
                await emit({"type": "a2a_event", "agent": key, "event": event})
                if event.get("kind") == "artifact-update":
                    captured["text"] = event["artifact"]["parts"][0]["text"]

        try:
            await _with_retry(
                consume, attempts=2,
                on_retry=lambda n, e: emit({"type": "agent_retry", "agent": key,
                                            "attempt": n, "message": str(e)}))
            results[key] = captured["text"]
            await emit({"type": "agent_done", "agent": key, "text": captured["text"]})
        except Exception as exc:                       # noqa: BLE001
            results[key] = f"_({cards[key].name} was unavailable: {exc})_"
            await emit({"type": "agent_error", "agent": key, "message": str(exc)})

    await asyncio.gather(*[run_one(k) for k in selected])

    # 5b) NEGOTIATE — the specialists talk to each other (in persona) over A2A to
    # reconcile trade-offs before the host writes the plan. Present = everyone who
    # has a result this turn (freshly run or reused) and is online.
    present = [k for k in keys if k in cards and results.get(k)
               and not str(results.get(k, "")).startswith("_(")]
    transcript = await negotiate(present, beliefs, clients=clients, keys=keys,
                                 cards=cards, context_id=context_id, emit=emit)

    # 6) SYNTHESISE
    await emit({"type": "synthesis_start"})
    final = await synthesize(user_request, beliefs, intent, results, transcript)
    await emit({"type": "final", "text": final})

    # 7) PERSIST conversation state + this turn
    await asyncio.to_thread(memory.save_conversation, context_id, beliefs, intent, results, user_id)
    await asyncio.to_thread(memory.add_turn, context_id, user_request, final)

    return {"beliefs": beliefs, "intent": intent, "results": results, "final": final}
