"""
Weather Advisor — an A2A server agent (port 8104) that uses a REAL tool via MCP.
================================================================================

This agent is special: instead of answering purely from the LLM's memory, it
calls a live weather tool. That tool lives in a separate **MCP server**
(mcp_servers/weather_server.py); this agent is the MCP **client**.

    orchestrator --(A2A)--> THIS agent --(MCP)--> weather tool --> Open-Meteo

It uses the *streaming* handler style (an async generator): it yields Progress
notes so you can watch the MCP tool call happen in the A2A protocol log, then
yields the final advice. The live forecast is fetched even without a Groq key
(it's a real API), so the tool works in offline-mock mode too.

    python -m agents.weather_advisor
"""
from __future__ import annotations

import re

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from common.a2a import AgentCard, AgentSkill, Progress, build_agent_app, run_agent
from common.llm import chat

PORT = 8104
MCP_URL = "http://127.0.0.1:8200/mcp"   # the weather MCP server

CARD = AgentCard(
    name="Weather Advisor",
    description="Gives weather-aware packing advice grounded in a live forecast (via an MCP tool).",
    url=f"http://127.0.0.1:{PORT}/",
    skills=[
        AgentSkill(
            id="weather_packing",
            name="Weather & Packing",
            description="Fetch a live forecast (MCP tool) and advise what the weather means + what to pack.",
            tags=["travel", "weather", "packing", "mcp"],
            examples=["What's the weather like for a trip to Kyoto?"],
        )
    ],
)

SYSTEM_WITH_DATA = (
    "You are a travel weather and packing advisor. You are given a REAL live "
    "multi-day forecast. In Markdown: (1) summarise in 2-3 sentences what that "
    "weather means for the trip, then (2) give a short bulleted packing list "
    "tailored to those temperatures and conditions. Be concise. Do not invent "
    "numbers beyond the forecast you are given."
)
SYSTEM_NO_DATA = (
    "You are a travel weather and packing advisor. A live forecast is "
    "unavailable, so give brief general seasonal guidance and a short packing "
    "list for the destination, and note that it is general guidance."
)

# The orchestrator phrases the sub-request as "...trip to <Destination>." so we
# can recover the place name deterministically (no LLM needed — works offline).
_LOC_RE = re.compile(r"\b(?:to|in|for|visit(?:ing)?)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,2})")
_DAYS_RE = re.compile(r"(\d+)\s*[- ]?\s*day", re.IGNORECASE)


def _extract_location(text: str) -> str:
    m = _LOC_RE.search(text)
    if m:
        return m.group(1).strip(" .,'")
    caps = re.findall(r"\b([A-Z][A-Za-z]+)\b", text)
    return caps[-1] if caps else text.strip()[:40]


def _extract_days(text: str) -> int:
    m = _DAYS_RE.search(text)
    return max(1, min(int(m.group(1)), 16)) if m else 5


async def fetch_weather(location: str, days: int) -> str | None:
    """Call the weather tool on the MCP server. Returns forecast text or None."""
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("get_weather", {"location": location, "days": days})
            if res.isError or not res.content:
                return None
            text = res.content[0].text
            return None if text.startswith("No location") else text


async def logic(user_text: str):
    """Streaming handler: narrate the MCP tool call, then give advice."""
    location = _extract_location(user_text)
    days = _extract_days(user_text)

    yield Progress(f"Calling weather tool via MCP for {location}…")
    forecast = None
    try:
        forecast = await fetch_weather(location, days)
    except Exception as exc:
        yield Progress(f"Weather tool unreachable ({exc}).")

    if forecast:
        lines = forecast.splitlines()
        peek = lines[1].strip("- ") if len(lines) > 1 else location
        yield Progress(f"Live data received via MCP — e.g. {peek}")
        prompt = f"{user_text}\n\nUse this REAL live forecast as ground truth:\n{forecast}"
        advice = await chat(SYSTEM_WITH_DATA, prompt, tag="weather")
        advice += "\n\n---\n*🔧 Grounded in a live forecast fetched from Open-Meteo via MCP.*"
    else:
        yield Progress("Weather tool unavailable — giving general seasonal guidance.")
        advice = await chat(SYSTEM_NO_DATA, user_text, tag="weather")

    yield advice   # the final answer (plain string, yielded last)


app = build_agent_app(CARD, logic)

if __name__ == "__main__":
    run_agent(app, PORT)
