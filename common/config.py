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
    8200  Weather MCP Server     (MCP tool server, NOT an A2A agent)
"""
from __future__ import annotations

GATEWAY_PORT = 8000

# Each specialist is an independent A2A server (its own process + Agent Card).
# `key`    -> short id used internally + in the UI
# `module` -> python module the launcher runs with `python -m <module>`
# `port`   -> TCP port the agent's HTTP server listens on
SPECIALISTS: list[dict] = [
    {
        "key": "destination",
        "module": "agents.destination_expert",
        "port": 8101,
    },
    {
        "key": "itinerary",
        "module": "agents.itinerary_planner",
        "port": 8102,
    },
    {
        "key": "budget",
        "module": "agents.budget_packing",
        "port": 8103,
    },
    {
        "key": "weather",
        "module": "agents.weather_advisor",
        "port": 8104,
    },
]

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
