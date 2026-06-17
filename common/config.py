"""
Central configuration for the Smart Trip Planner A2A prototype.

This is the single place that lists *where* every agent lives (its port and
base URL). The orchestrator uses this list to DISCOVER each specialist by
fetching its Agent Card from `<url>/.well-known/agent-card.json`.

Ports:
    8000  Web Gateway + UI       (serves the browser app, runs the orchestrator)
    8100  Orchestrator Agent     (A2A server: the host agent, also callable via A2A)
    8101  Destination Expert     (A2A server agent)
    8102  Itinerary Planner      (A2A server agent)
    8103  Budget & Packing       (A2A server agent)
    8104  Weather Advisor        (A2A server agent; uses an MCP tool)
    8105  Local Cuisine Expert   (A2A server agent)
    8200  Weather MCP Server     (MCP tool server, NOT an A2A agent)
"""
from __future__ import annotations

GATEWAY_PORT = 8000

# Each specialist is an independent A2A server (its own process + Agent Card).
# `key`    -> short id used internally + in the UI
# `module` -> python module the launcher runs with `python -m <module>`
# `port`   -> TCP port the agent's HTTP server listens on
# Each specialist also declares its ROLE and MOTIVATION (why it exists) and the
# INTENT the orchestrator attaches when delegating to it (the FIPA "request"
# performative's reason). This is the explicit "roles & motivations" layer.
SPECIALISTS: list[dict] = [
    {
        "key": "destination",
        "module": "agents.destination_expert",
        "port": 8101,
        "role": "Destination scout",
        "motivation": "Help the traveler understand the place and its culture",
        "intent": "Understand the destination, best time to go, and etiquette",
    },
    {
        "key": "itinerary",
        "module": "agents.itinerary_planner",
        "port": 8102,
        "role": "Itinerary planner",
        "motivation": "Make every day enjoyable and well-paced",
        "intent": "Plan a day-by-day itinerary matched to the interests",
    },
    {
        "key": "budget",
        "module": "agents.budget_packing",
        "port": 8103,
        "role": "Fiscal advisor",
        "motivation": "Keep the trip affordable and the costs transparent",
        "intent": "Estimate costs and keep the trip on budget",
    },
    {
        "key": "weather",
        "module": "agents.weather_advisor",
        "port": 8104,
        "role": "Weather & packing advisor",
        "motivation": "Make sure the traveler packs right for real conditions",
        "intent": "Ground packing advice in a live weather forecast",
    },
    {
        "key": "cuisine",
        "module": "agents.cuisine_expert",
        "port": 8105,
        "role": "Local cuisine guide",
        "motivation": "Help the traveler eat well and taste the local culture",
        "intent": "Recommend signature local dishes, where to eat, and dining tips",
    },
]


def specialist(key: str) -> dict:
    """Look up a specialist's config entry by key."""
    return next(s for s in SPECIALISTS if s["key"] == key)

# The orchestrator is ALSO exposed as a standalone A2A agent (so it can be
# "hired" like any other agent — this is what demonstrates agents composing).
# It is deliberately NOT in SPECIALISTS: plan_trip() delegates to SPECIALISTS,
# and the orchestrator must never delegate to itself.
ORCHESTRATOR_AGENT: dict = {
    "key": "orchestrator",
    "module": "orchestrator.agent",
    "port": 8100,
}

# The weather agent's tool lives in a separate MCP server (not an A2A agent).
WEATHER_MCP: dict = {
    "module": "mcp_servers.weather_server",
    "port": 8200,
}


def base_url(port: int) -> str:
    """The HTTP base URL an agent serves on (note the trailing slash —
    the A2A JSON-RPC endpoint is the root `/` of this URL).

    We use 127.0.0.1 (not "localhost") on purpose: on Windows "localhost"
    can resolve to IPv6 (::1) while our servers listen on IPv4, which would
    cause confusing connection failures."""
    return f"http://127.0.0.1:{port}/"


def specialist_urls() -> list[str]:
    """Base URLs of every specialist, in display order."""
    return [base_url(s["port"]) for s in SPECIALISTS]


def orchestrator_url() -> str:
    """Base URL of the orchestrator exposed as a standalone A2A agent."""
    return base_url(ORCHESTRATOR_AGENT["port"])
