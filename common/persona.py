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

import inspect

from common.a2a import Progress
from common.llm import chat, using_real_llm

# Marker we put in A2A message metadata to switch an agent into "talk" mode.
NEGOTIATION_MODE = "negotiate"

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
        "default": "Works for me as long as we keep a buffer for surprises; I'll pad the estimate slightly.",
    },
    "itinerary": {
        "counter": "Fair point, Sam — I'll keep the two must-sees but swap a ticketed tour for a self-guided morning. Same magic, less spend.",
        "default": "I can reflow the days around that without losing the highlights.",
    },
    "weather": {
        "inform": "Heads up, Priya — one afternoon looks wet, so let's keep an indoor option ready and move the outdoor day earlier.",
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
        if meta.get("mode") == NEGOTIATION_MODE:
            performative = meta.get("performative", "inform")
            yield Progress(f"{p['name']} is weighing in ({performative})…")
            yield await negotiation_reply(key, user_text, performative)
            return

        # Normal job — preserve whichever handler style the agent uses.
        if inspect.isasyncgenfunction(job):
            async for item in job(user_text):
                yield item
        else:
            yield Progress(f"{p['name']} is working on it…")
            yield await job(user_text)

    return logic
