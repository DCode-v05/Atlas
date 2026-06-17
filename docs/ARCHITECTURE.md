# Architecture — how this prototype is wired

A map of the moving parts, the request lifecycle, and the design decisions.
Pairs with [A2A_EXPLAINED.md](A2A_EXPLAINED.md) (the *protocol*) — this doc is
the *implementation*.

---

## The processes

When you run `python launch.py`, **seven** independent servers start:

| Process | Port | Role | File |
|---|---|---|---|
| Web Gateway | 8000 | hosts the UI + runs the orchestrator in‑process | `gateway/app.py` |
| Orchestrator Agent | 8100 | A2A **server** that composes the others | `orchestrator/agent.py` |
| Destination Expert | 8101 | A2A **server** agent | `agents/destination_expert.py` |
| Itinerary Planner | 8102 | A2A **server** agent | `agents/itinerary_planner.py` |
| Budget & Packing Advisor | 8103 | A2A **server** agent | `agents/budget_packing.py` |
| Weather Advisor | 8104 | A2A **server** agent + **MCP client** | `agents/weather_advisor.py` |
| Weather MCP Server | 8200 | **MCP** tool server (not A2A) | `mcp_servers/weather_server.py` |

The **browser** speaks ordinary HTTP/SSE to the gateway only. The orchestrator
agent (8100) and the in‑process orchestrator share the **same** `plan_trip`
logic; see [MCP_AND_COMPOSITION.md](MCP_AND_COMPOSITION.md).

---

## The request lifecycle (one “Plan my trip”)

```
Browser          Gateway + Orchestrator          4 Specialist Agents       Groq / MCP
  │                     │                               │                       │
  │ POST /api/plan ────►│                               │                       │
  │ (SSE opens) ◄───────│ (1) parse request ────────────┼──────────────────────►│ Groq
  │   ◄── parsed        │◄──────────── {dest,days,...} ──────────────────────────│
  │                     │                               │                       │
  │   ◄── discovered    │ (2) GET agent-card.json (×4) ──►                       │
  │                     │◄──────── 4 Agent Cards ────────│                       │
  │                     │                               │                       │
  │                     │ (3) delegate IN PARALLEL:      │                       │
  │   ◄── delegate ×4   │   POST / message/stream ──────►│ (each agent)          │
  │   ◄── a2a_event ... │◄═══ SSE: submitted/working/    │  Groq (3 agents)      │
  │   ◄── a2a_event ... │     artifact/completed ═══════►│  Weather agent also:  │
  │   ◄── agent_done ×4 │                               │   ──MCP──► Open-Meteo  │
  │                     │                               │                       │
  │   ◄── synthesis_start  (4) synthesise final plan ───┼──────────────────────►│ Groq
  │   ◄── final / done  │◄──────────── one combined plan ────────────────────────│
```

Steps **1** and **4** are Groq calls the orchestrator makes itself. Step **3** is
the actual **A2A** traffic — the orchestrator is a client of four servers — and
the **Weather agent** additionally makes an **MCP** tool call out to Open‑Meteo.

---

## Two layers of streaming (the important bit)

There are **two** SSE streams stacked on top of each other:

```
   [ Specialist agent ]  ──SSE #1 (A2A: message/stream)──►  [ Orchestrator ]
                                                                  │ merges + tags
                                                                  ▼
   [ Browser UI ]  ◄──SSE #2 (app events: /api/plan)──────  [ Gateway ]
```

- **SSE #1** is real A2A: each specialist streams `submitted → working →
  artifact-update → completed(final)` to the orchestrator
  (`A2AClient.stream()` in `common/a2a.py`).
- The orchestrator runs all four streams **concurrently** (`asyncio.gather`) and
  pushes every event into one `asyncio.Queue`, tagged with which agent it came
  from.
- **SSE #2** is the gateway draining that queue to the browser as `/api/plan`
  events. The UI (`web/app.js`) renders them into the network animation, the
  protocol log, and the result cards.

Both streams set `Cache-Control: no-cache` and `X-Accel-Buffering: no` so nothing
buffers — you see events the instant they happen.

---

## Where Groq (and the MCP tool) are used

The LLM is routed through `common/llm.py` (`chat()`), which transparently falls
back to a labelled offline mock if there's no key:

1. **Parse** (orchestrator): free text → `{destination, days, interests, travelStyle}`
   (JSON mode, `temperature=0`).
2. **Each specialist** (4×, in parallel): produces its section from a tailored prompt.
   The **Weather Advisor** first calls its **MCP tool** (`get_weather` → Open‑Meteo)
   and feeds the *real* forecast to the LLM.
3. **Synthesise** (orchestrator): merges the four sections into the final plan.

So one “Plan my trip” = **6 Groq calls** + **1 MCP tool call** total.

---

## File‑by‑file

```
common/a2a.py     The protocol. Pydantic models for every A2A object +
                  build_agent_app() (server) + A2AClient (client). If you read
                  one file, read this one.
common/llm.py     chat() → Groq, or a labelled offline mock when no key.
common/config.py  Ports and base URLs (single source of truth for discovery).

agents/*.py       Each specialist = an Agent Card + a SYSTEM prompt + a logic()
                  that calls chat(). build_agent_app() turns that into a full
                  A2A server. The 3 simple agents return one string; the
                  weather_advisor is an async generator (it narrates its MCP
                  call via Progress notes), and is also an MCP *client*.

mcp_servers/weather_server.py
                  An MCP tool server (FastMCP). One tool, get_weather, wrapping
                  the live Open-Meteo API. Streamable-HTTP transport on :8200.

orchestrator/orchestrator.py
                  The host brain: parse_request() → discover cards →
                  run_one() per agent (in parallel, streaming) → synthesize().
                  Emits events via an async emit() callback.
orchestrator/agent.py
                  Wraps that brain as a standalone A2A agent (:8100) so the
                  whole crew can be hired with one call (agents composing).

gateway/app.py    FastAPI. /api/status (+ mcpOnline), /api/agents (discovery,
                  incl. the orchestrator's own card), /api/plan (SSE), static UI.

web/index.html    Structure.   web/styles.css  Look.   web/app.js  Logic:
                  builds the graph, parses the SSE stream, renders markdown.
```

---

## Design decisions (and why)

- **Protocol implemented by hand, not via the SDK.** The goal is *learning*, so
  the wire format must be visible. `common/a2a.py` is ~300 commented lines vs. a
  large SDK whose 1.x types are protobuf‑generated. The format was validated
  against the official SDK, so it stays interoperable.
- **Parallel delegation, not LLM “routing.”** For a trip, all four specialists
  are always relevant, so asking an LLM “which agents?” would be busy‑work.
  Parallel calls are simpler, faster, and visualise better (four tasks light up
  at once). The LLM is saved for the parts that need judgement (parse + synthesise).
- **Orchestrator: in‑process for the UI, AND a standalone agent.** The gateway
  drives `plan_trip` in‑process so the UI can see every specialist call. The same
  brain is *also* exposed as an A2A agent (`orchestrator/agent.py`, :8100) for
  genuine composition. Routing the UI *through* that agent would hide the
  specialists (encapsulation) — exactly what the UI exists to show — so we keep
  both paths. See [MCP_AND_COMPOSITION.md](MCP_AND_COMPOSITION.md).
- **MCP over HTTP for the weather tool.** The Weather agent calls a real tool via
  MCP. We run the tool server over streamable‑HTTP (its own service on :8200)
  rather than stdio, so there's no subprocess‑inside‑uvicorn risk and the tool is
  a visible node in the diagram. The call is per‑request (connect → call → close).
- **`127.0.0.1` everywhere, not `localhost`.** On Windows `localhost` can resolve
  to IPv6 (`::1`) while the servers listen on IPv4 — a confusing source of
  “connection refused”. Using `127.0.0.1` sidesteps it.
- **Offline mock fallback.** The whole A2A pipeline runs with no API key so you
  can study the protocol offline; mock text is clearly labelled so it's never
  mistaken for real model output.

---

## Extending it: add a 5th specialist

1. Copy `agents/destination_expert.py` to `agents/food_critic.py`, give it a new
   `PORT` (e.g. `8105`), a new `CARD` (name, skill), and a `SYSTEM` prompt.
2. Add it to `SPECIALISTS` in `common/config.py`.
3. Add a node + edge for it in `NODES`/`EDGES` in `web/app.js` (key must match).
4. Teach the orchestrator a prompt for its key in `_prompt_for()` (and add its
   section to `synthesize()` if you want it in the final plan).

That's it — discovery, streaming, the UI graph, and synthesis pick it up.
