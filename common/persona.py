"""
persona.py — give each agent a HUMAN VOICE and let them NEGOTIATE.
=================================================================

The specialists in this prototype don't just answer in isolation — after they
each produce a draft, they hold a short **round-table negotiation** to reconcile
trade-offs (cost vs. ambition, weather vs. outdoor plans, food vs. budget).

Two things make that feel human:

1. **A persona per agent** — a name, a job title, and a speaking style. The same
   agent that writes the formal write-up also has a personality it negotiates in.
2. **A negotiation mode** — when an A2A message arrives carrying
   `metadata.mode == "negotiate"`, the agent drops its formal report format and
   instead *talks*: 1-3 first-person sentences, addressing colleagues by name,
   coloured by a FIPA-style performative (concern / counter / propose / agree…).

The negotiation itself is REAL A2A traffic: the orchestrator streams each turn
to the relevant agent with `message/stream`, the performative rides in the
message `metadata`, and the agent's reply comes back as an artifact — exactly
like any other A2A call, so you can watch it in the protocol log.
"""
from __future__ import annotations

import asyncio
import inspect

from common.a2a import A2AClient, Progress
from common.config import base_url, specialist
from common.llm import chat, using_real_llm

# Markers we put in A2A message metadata to switch an agent's behaviour.
NEGOTIATION_MODE = "negotiate"   # the host-facilitated round-table (hierarchical)
CONSULT_MODE = "consult"          # one agent calling ANOTHER directly (mesh)

# Each specialist as a person: a name, a title, a speaking style, an emoji.
PERSONAS: dict[str, dict] = {
    "destination": {"name": "Mateo",  "title": "Destination Scout",
                    "voice": "warm and well-travelled; drops small cultural anecdotes",
                    "emoji": "🧭"},
    "itinerary":   {"name": "Priya",  "title": "Itinerary Planner",
                    "voice": "organised and upbeat; thinks in schedules, pacing and trade-offs",
                    "emoji": "🗺️"},
    "budget":      {"name": "Sam",    "title": "Budget & Packing Advisor",
                    "voice": "frank and frugal; watches every dollar but stays kind about it",
                    "emoji": "💰"},
    "weather":     {"name": "Lin",    "title": "Weather Advisor",
                    "voice": "careful and data-driven; gently cautious about the forecast",
                    "emoji": "🌦️"},
    "cuisine":     {"name": "Giulia", "title": "Local Cuisine Expert",
                    "voice": "a passionate, enthusiastic foodie who is always a little hungry",
                    "emoji": "🍜"},
}


def persona(key: str) -> dict:
    return PERSONAS.get(key, {"name": key.title(), "title": key.title(),
                              "voice": "friendly and helpful", "emoji": "🤖"})


def display_name(key: str) -> str:
    p = persona(key)
    return f"{p['name']} · {p['title']}"


# ---------------------------------------------------------------------------
# Negotiation "brain" — how an agent talks when it's negotiating
# ---------------------------------------------------------------------------
def _negotiation_system(key: str) -> str:
    p = persona(key)
    return (
        f"You are {p['name']}, the {p['title']} on a small trip-planning team. "
        f"You talk like a real person: {p['voice']}. You are in a quick verbal "
        "round-table with the other specialists to reconcile the plan. "
        "Reply in FIRST PERSON with just 1-3 short, natural sentences — like "
        "speaking up in a meeting. Address colleagues by their first name when it "
        "fits. Be constructive and move toward agreement. Do NOT use markdown "
        "headings, bullet points or lists; just talk."
    )


# Clearly-labelled offline lines so negotiation still 'works' with no Groq key.
_MOCK_BANNER = "⚠️(mock) "
_MOCK_LINES: dict[str, dict[str, str]] = {
    "budget": {
        "concern": "Honestly, this is looking a little rich for the budget — could we trim one paid attraction and lean on free sights?",
        "answer": "There's a little headroom if we keep most meals casual — one nicer dinner is fine, not three.",
        "default": "Works for me as long as we keep a buffer for surprises; I'll pad the estimate slightly.",
    },
    "itinerary": {
        "counter": "Fair point, Sam — I'll keep the two must-sees but swap a ticketed tour for a self-guided morning. Same magic, less spend.",
        "default": "I can reflow the days around that without losing the highlights.",
    },
    "weather": {
        "inform": "Heads up, Priya — one afternoon looks wet, so let's keep an indoor option ready and move the outdoor day earlier.",
        "answer": "Looking at the forecast, one afternoon skews wet — I'd keep that day flexible, but the rest is clear.",
        "default": "The forecast is mild overall, so the current pacing should hold up fine.",
    },
    "cuisine": {
        "propose": "And Sam — eating like a local at markets and street stalls is cheaper AND tastier, so the budget actually helps us here.",
        "default": "I'll point us at neighbourhood spots so the food fits both the wallet and the mood.",
    },
    "destination": {
        "agree": "Sounds like a plan, team — and a small tip: mornings are the calmest time for the big sights, so the early start helps.",
        "default": "I'm happy with this direction; it captures the place well.",
    },
}


def _mock_line(key: str, performative: str) -> str:
    table = _MOCK_LINES.get(key, {})
    return _MOCK_BANNER + table.get(performative, table.get("default",
                                    "Sounds reasonable to me — let's go with that."))


async def negotiation_reply(key: str, message_text: str, performative: str) -> str:
    """Produce this agent's spoken negotiation turn (LLM, or offline mock)."""
    if using_real_llm():
        return await chat(_negotiation_system(key), message_text,
                          tag="negotiate", temperature=0.75, max_tokens=180)
    return _mock_line(key, performative)


# ---------------------------------------------------------------------------
# MESH (peer-to-peer): one agent decides, by its OWN role, to call another agent
# directly over A2A — no orchestrator in the loop. Each entry says: when THIS
# agent speaks at the round-table, it first phones a peer to ground its opinion.
# ---------------------------------------------------------------------------
CONSULT_POLICY: dict[str, dict] = {
    "itinerary": {"peer": "weather", "why": "ground the plan in the real forecast",
                  "ask": "Quick one for the plan — will the weather disrupt any "
                         "outdoor day, and which day should I keep flexible?"},
    "cuisine":   {"peer": "budget", "why": "keep the food plan within budget",
                  "ask": "How much headroom is there for food — should I lean on "
                         "cheap local eats, or can we splurge on one meal?"},
}


async def consult_peer(from_key: str, to_key: str, question: str) -> str:
    """Call ANOTHER agent directly over A2A (mesh). Returns the peer's reply text.

    This is a real `message/stream` A2A call from one specialist to another — the
    orchestrator never sees it. The `mode=consult` metadata tells the peer to
    answer briefly, in persona, rather than do its full job."""
    client = A2AClient(base_url(specialist(to_key)["port"]))
    meta = {"mode": CONSULT_MODE, "performative": "query", "from": from_key}
    said = ""
    async for event in client.stream(question, metadata=meta):
        if event.get("kind") == "artifact-update":
            said = event["artifact"]["parts"][0]["text"]
    return said.strip()


# ---------------------------------------------------------------------------
# Wrap an agent's normal "job" so it ALSO knows how to negotiate
# ---------------------------------------------------------------------------
def persona_aware(key: str, job):
    """Return a streaming A2A handler that:

      • in NEGOTIATION mode (metadata.mode == "negotiate") replies in persona
        with a short spoken turn, and
      • otherwise runs the agent's normal `job` (a coroutine returning the
        formal answer, or an async-generator that yields Progress notes + text).

    This lets every specialist keep its real expertise while gaining a voice.
    """
    p = persona(key)

    async def logic(user_text: str, ctx):
        meta = ctx.metadata or {}

        # MESH: a peer is calling THIS agent directly — answer briefly, in persona.
        if meta.get("mode") == CONSULT_MODE:
            frm = meta.get("from", "a colleague")
            yield Progress(f"{p['name']} is answering {persona(frm)['name']} directly (peer-to-peer)…")
            yield await negotiation_reply(key, user_text, "answer")
            return

        # ROUND-TABLE: this agent takes its turn in the host-facilitated discussion.
        if meta.get("mode") == NEGOTIATION_MODE:
            performative = meta.get("performative", "inform")
            yield Progress(f"{p['name']} is weighing in ({performative})…")

            # Some agents DECIDE, by their own role, to phone a peer first (mesh).
            peer_note = ""
            policy = CONSULT_POLICY.get(key)
            if policy:
                peer, peer_name = policy["peer"], persona(policy["peer"])["name"]
                yield Progress(f"{p['name']} is consulting {peer_name} directly over "
                               f"A2A (mesh) — to {policy['why']}…")
                try:
                    answer = await asyncio.wait_for(
                        consult_peer(key, peer, policy["ask"]), timeout=20)
                    if answer:
                        peer_note = (f"\n\n[{peer_name} just told you directly over "
                                     f"A2A: \"{answer}\". Weave this into your reply.]")
                except Exception:
                    pass                     # peer offline/slow → speak without it

            yield await negotiation_reply(key, user_text + peer_note, performative)
            return

        # Normal job — preserve whichever handler style the agent uses.
        if inspect.isasyncgenfunction(job):
            async for item in job(user_text):
                yield item
        else:
            yield Progress(f"{p['name']} is working on it…")
            yield await job(user_text)

    return logic
