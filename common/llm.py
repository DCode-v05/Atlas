"""
llm.py — the "brain" each agent uses to think, powered by Groq.
================================================================

Every agent in this prototype calls `chat(...)` to get an answer from a Large
Language Model. We use Groq because it serves open models (Llama, etc.) very
fast and has a generous free tier.

GRACEFUL FALLBACK
-----------------
If no GROQ_API_KEY is set, `chat(...)` returns a built-in MOCK answer instead of
calling Groq. That lets you run and understand the whole A2A system offline.
Mock answers are clearly labelled so you never mistake them for real AI output.
Set your key in `.env` to get genuine Groq responses.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Optional

from dotenv import load_dotenv

# Load variables from a local .env file (GROQ_API_KEY, GROQ_MODEL) if present.
load_dotenv()

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MOCK_BANNER = "> ⚠️ **Mock answer** — set `GROQ_API_KEY` in `.env` for real Groq output.\n\n"

_groq_client = None  # created lazily on first real call


def using_real_llm() -> bool:
    """True when a *real-looking* Groq API key is configured.

    Set `ATLAS_FORCE_MOCK=1` to force offline mock mode without touching your
    `.env` (safe on Windows, where blanking an env var is finicky). We also
    ignore blanks and the placeholder values shipped in .env.example so that
    copying the example file verbatim still falls back to the offline mock
    instead of firing failing API calls. Real Groq keys start with "gsk_"."""
    if os.environ.get("ATLAS_FORCE_MOCK", "").strip().lower() in ("1", "true", "yes"):
        return False
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return False
    placeholders = {"your_groq_api_key_here", "your-groq-api-key", "changeme"}
    if key.lower() in placeholders or "your_groq" in key.lower():
        return False
    return True


def model_name() -> str:
    return os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_MODEL


def _client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"].strip())
    return _groq_client


async def chat(system: str, user: str, *, tag: str = "",
               json_mode: bool = False, temperature: float = 0.6,
               max_tokens: int = 900) -> str:
    """Ask the model a question.

    system     - the role/instructions for the agent
    user       - the user's request
    tag        - a hint used ONLY by the offline mock to pick a canned answer
    json_mode  - ask the model to return strict JSON (used for request parsing)
    """
    if not using_real_llm():
        return _mock(tag, user, json_mode)

    def _call() -> str:
        # The Groq SDK is synchronous; run it in a thread so we never block the
        # async event loop (this is what lets 3 agents work concurrently).
        kwargs = dict(
            model=model_name(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = _client().chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()

    try:
        return await asyncio.to_thread(_call)
    except Exception as exc:  # surface a clear, friendly error upstream
        raise RuntimeError(f"Groq call failed ({type(exc).__name__}): {exc}") from exc


def heuristic_fields(text: str) -> dict:
    """Public access to the offline heuristic request parser — used by the
    orchestrator's mock 'understand' step when there's no Groq key."""
    return _guess_request(text)


def extract_json(text: str) -> dict:
    """Best-effort: pull the first {...} JSON object out of a model reply."""
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {}


# ===========================================================================
# OFFLINE MOCK  — deterministic, clearly-labelled stand-in for the real model
# ===========================================================================

_DEST_RE = re.compile(r"\b(?:to|in|visit|visiting)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})")
_DAYS_RE = re.compile(r"(\d+)\s*[- ]?\s*day", re.IGNORECASE)
_INTEREST_WORDS = [
    "food", "foodie", "history", "historic", "art", "museums", "nature",
    "hiking", "nightlife", "shopping", "beaches", "temples", "adventure",
    "family", "romantic", "culture", "photography", "wildlife",
]


def _guess_request(user: str) -> dict:
    """Very rough parse of a trip request — only used by the offline mock."""
    days_match = _DAYS_RE.search(user)
    days = int(days_match.group(1)) if days_match else 3
    dest_match = _DEST_RE.search(user)
    destination = dest_match.group(1) if dest_match else "your destination"
    style = "mid-range"
    low = user.lower()
    if any(w in low for w in ("budget", "cheap", "backpack")):
        style = "budget"
    elif any(w in low for w in ("luxury", "lux", "5-star", "five star")):
        style = "luxury"
    interests = sorted({w for w in _INTEREST_WORDS if w in low}) or ["highlights"]
    return {"destination": destination, "days": days,
            "interests": interests, "travelStyle": style}


def _mock(tag: str, user: str, json_mode: bool) -> str:
    info = _guess_request(user)
    dest, days = info["destination"], info["days"]
    interests = ", ".join(info["interests"])
    style = info["travelStyle"]

    if tag == "parse" or json_mode:
        return json.dumps(info)

    if tag == "destination":
        return (MOCK_BANNER +
                f"### About {dest}\n\n"
                f"{dest} is a rewarding place to visit, especially if you enjoy "
                f"{interests}. The best seasons are spring and autumn, when the "
                f"weather is mild and crowds are thinner.\n\n"
                f"**Good to know**\n"
                f"- Learn a couple of local greetings — locals appreciate it.\n"
                f"- Carry some cash; not every spot takes cards.\n"
                f"- Mornings are the calmest time to see the popular sights.")

    if tag == "itinerary":
        lines = [MOCK_BANNER, f"### {days}-Day {dest} Itinerary ({interests})\n"]
        for d in range(1, days + 1):
            lines.append(f"**Day {d}** — Morning: a signature {dest} sight. "
                         f"Afternoon: explore a {interests.split(',')[0]} spot. "
                         f"Evening: dinner at a well-loved local place.")
        return "\n".join(lines)

    if tag == "cuisine":
        return (MOCK_BANNER +
                f"### What to Eat in {dest}\n\n"
                f"{dest} rewards hungry travelers, especially if you enjoy {interests}.\n\n"
                f"**Must-try dishes**\n"
                f"- **A signature local specialty** — the dish the city is known for.\n"
                f"- **A hearty street-food staple** — cheap, quick, and everywhere.\n"
                f"- **A regional comfort dish** — what locals eat at home.\n"
                f"- **A sweet local treat** — save room for dessert.\n\n"
                f"**Where to eat ({style})**\n"
                f"- Markets and street stalls for the most authentic, affordable bites.\n"
                f"- Neighbourhood spots away from the main sights for better value.\n\n"
                f"**Dining tips**\n"
                f"- Eat where you see a local crowd.\n"
                f"- Learn how tipping works before you go.")

    if tag == "budget":
        per_day = {"budget": 70, "mid-range": 160, "luxury": 420}[style]
        total = per_day * days
        return (MOCK_BANNER +
                f"### Budget & Packing ({style}) — {days} days in {dest}\n\n"
                f"**Estimated budget:** ~${per_day}/day → **~${total} total** "
                f"(lodging + food + local transport + activities).\n\n"
                f"**Packing list**\n"
                f"- Comfortable walking shoes\n- Weather-appropriate layers\n"
                f"- Reusable water bottle\n- Power adapter + portable charger\n"
                f"- Copies of bookings and ID")

    if tag == "weather":
        # the live forecast (fetched via MCP) is embedded in `user` by the agent
        forecast_lines = [l for l in user.splitlines() if l.strip().startswith("-")]
        fc = "\n".join(forecast_lines[:7])
        intro = f"Based on the live forecast:\n\n{fc}\n\n" if fc else ""
        return (MOCK_BANNER + f"### Weather & What to Pack\n\n{intro}"
                "Expect a mix of conditions, so pack flexible layers you can add "
                "or remove, a compact umbrella or light rain shell for showers, "
                "comfortable walking shoes, and sun protection for clear spells.\n\n"
                "- Lightweight layers + one warm layer\n- Packable rain jacket / umbrella\n"
                "- Comfortable walking shoes\n- Sunglasses & sunscreen\n- Reusable water bottle")

    if tag == "synthesize":
        return (MOCK_BANNER +
                f"# Your Trip Plan: {days} Days in {dest}\n\n"
                f"Here is a combined plan built from all three specialist agents.\n\n"
                f"{user}\n")

    # generic fallback
    return MOCK_BANNER + f"(Mock answer for: {user[:120]})"
