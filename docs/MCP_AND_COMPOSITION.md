# MCP tools & agents composing

Two ideas that make this prototype more than a toy. Both are beginner‑friendly
once you've seen the [A2A basics](A2A_EXPLAINED.md).

---

## Part 1 — MCP: giving an agent a real tool

### The idea
A2A connects an agent to **other agents**. **MCP (Model Context Protocol)**
connects an agent to **tools and data** — a calculator, a database, a web API.
They're complementary halves of the same picture:

```
            A2A  (agent ⇄ agent)            MCP  (agent ⇄ tool)
 orchestrator ───────────────► Weather Advisor ───────────────► get_weather tool
   (host agent)                  (A2A server +                     (MCP server)
                                  MCP client)                          │
                                                                       ▼
                                                                 Open-Meteo API
                                                                  (live data)
```

The other three specialists answer from the LLM's own knowledge. The **Weather
Advisor** is different: it must not *guess* the forecast, so it calls a real
tool to fetch live data, then asks the LLM to interpret it.

### What we built
- **An MCP server** — [`mcp_servers/weather_server.py`](../mcp_servers/weather_server.py).
  Built with the official MCP SDK (`FastMCP`). It exposes one tool,
  `get_weather(location, days)`, which geocodes the place and fetches a daily
  forecast from the free, key‑less **Open‑Meteo** API. It runs as its own
  service on port **8200** (MCP "streamable‑HTTP" transport).
- **An MCP client** — inside [`agents/weather_advisor.py`](../agents/weather_advisor.py).
  When asked, the agent connects to the MCP server, calls `get_weather`, and
  feeds the real forecast to the LLM to produce packing advice.

### See it yourself
- In the **UI**, the Weather node has a dashed **violet** link to a `🔧 Weather
  API` tool node. That violet link is the MCP call (drawn differently on purpose
  — it isn't A2A). The Weather agent also narrates the call in the Protocol Log:
  *“Calling weather tool via MCP… Live data received via MCP — 20–25°C, drizzle.”*
- The final plan's **Weather** section then contains real numbers, with a note:
  *“🔧 Grounded in a live forecast fetched from Open‑Meteo via MCP.”*

### Two nice properties
- **The tool works without a Groq key.** Open‑Meteo needs no key, so even in
  offline‑mock mode you get a *real* forecast; only the advice wording is mock.
- **It degrades gracefully.** If the MCP server is down, the Weather agent
  catches the failure and falls back to general seasonal guidance — the trip
  plan still completes. (Try it: don't start `mcp_servers.weather_server`.)

### A note on MCP transports
MCP has two common transports. **stdio** (the agent launches the tool server as a
child process) is what you see in Claude Desktop configs. We use **HTTP** instead
so the tool server is a normal, visible service on a port that the launcher
starts — cleaner for a multi‑process demo. Same protocol, different plumbing.

---

## Part 2 — Agents composing (the orchestrator as an A2A agent)

### The idea
An A2A agent can itself be a **client of other A2A agents**. So you can wrap a
whole team behind a single Agent Card and "hire" it with one call. The caller
doesn't know (or care) that four agents did the work — that's **composition**,
and it's how big agent systems are built from small ones.

### What we built
[`orchestrator/agent.py`](../orchestrator/agent.py) exposes the orchestrator as a
standalone A2A agent (the **Trip Concierge**, port **8100**) with its own Agent
Card and a `plan_trip` skill. Call it over A2A and it internally calls the four
specialists for you (one of which uses the MCP tool), then returns the finished
plan.

Crucially, it's the **same `plan_trip` brain** the web UI uses — one piece of
logic, two front‑ends:
- the **gateway** drives it *in‑process* and forwards every internal step to the
  browser (so you can watch all four specialists light up), and
- the **A2A agent** wraps it so external callers can use it as a black box.

### See it yourself
```powershell
python show_composition.py "Plan a 5-day food and temples trip to Kyoto"
```
You talk to **one** agent (`:8100`). It prints its Agent Card, then streams
progress notes — *“Consulting Destination Expert over A2A…”* — and returns the
final plan. In the UI, the orchestrator also appears in **Discovered Agents**
with a **HOST** badge: proof it's a real A2A agent, not just glue code.

### Why the UI doesn't route *through* the :8100 agent
A true black‑box call would *hide* the specialists — but watching them is the
best part of the UI. So the UI keeps the transparent in‑process path, and the
:8100 agent exists for genuine composition (and the script above). Best of both.

---

## Recap

| | A2A | MCP |
|---|---|---|
| Connects | agent ⇄ agent | agent ⇄ tool/data |
| Here | orchestrator ⇄ 4 specialists; client ⇄ orchestrator agent | Weather agent ⇄ `get_weather` tool ⇄ Open‑Meteo |
| In the UI | solid edges, JSON‑RPC frames | dashed violet edge, "via MCP" notes |

Back to: [A2A_EXPLAINED.md](A2A_EXPLAINED.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
· [WALKTHROUGH.md](WALKTHROUGH.md)
