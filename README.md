# ATLAS — an Organisation of Communicating A2A Agents

Give the organisation a **mission**. A **CEO agent** breaks it down and **hires** a
team — conferring roles *through conversation* — and the team then **talks the plan
out in a live, multi-round round-table** before delivering a result. Everything
travels over a real, hand-rolled **A2A (Agent-to-Agent) protocol**, and you watch
every message, performative, hire and meeting happen live in the browser.

> **Worked example — the Smart Trip Planner.** Give it *"Plan a 5-day food and
> temples trip to Kyoto"* and the CEO hires a travel team — a **Travel Planner**
> (the day-by-day **itinerary**), a **Food Researcher**, a **Temple Guide**, and a
> **Logistics/Budget Coordinator** — the same specialists the original ATLAS trip
> planner had, except here the org *hires them itself*. They negotiate over several
> rounds (costs in **₹**) and hand back one refined plan.

---

## Quick start

```bash
python launch.py        # starts everything, opens the UI at http://127.0.0.1:8000
```

- Pick a **topology** (Hierarchical / Mesh / **Group · round-table** / Compare), type a
  mission (or click a chip), and hit **Start mission**.
- No API key? It runs on a **deterministic offline mock**. Add a **Groq** key to `.env`
  (copy `.env.example`) for live LLM agents — the round-table then improvises for real.

```bash
python scripts/demo_mission.py   # scripted run: asserts the expected A2A handoffs
python scripts/demo_trip.py      # the trip-planner mission, same assertions
```

---

## How it works — in plain terms

Think of it as a tiny **company of AI agents**:

1. **You give a mission.** The **CEO agent** reads it and **decomposes** it into a few
   roles (the team it needs).
2. **It hires the team — by negotiation.** For each role the CEO runs a **Contract-Net
   auction**: it asks candidates *"who can do this?"* (`cfp`), they **bid** (`propose`
   with a confidence score), the best bid is **hired** (`accept-proposal`), the rest are
   **released** (`refuse`). No central scheduler picks — the agents negotiate it.
3. **Roles are conferred by conversation.** A generic agent only *becomes* a "Travel
   Planner" when the CEO sends it an onboarding **offer** (`propose`) and it **accepts**
   (`accept-proposal`). Every agent runs the *same* code; its identity comes from the
   conversation.
4. **The team coordinates** in one of three styles (see the table below).
5. **The result is synthesised** — the CEO merges the team's work (and the decisions
   they reached in the round-table) into one final deliverable.

Each step is streamed live to the UI: the **org chart** grows as agents are hired, the
**A2A protocol log** shows every message tagged with its performative, and the
**round-table** panel shows the team talking.

---

## How agents talk to each other (the A2A protocol)

A2A lets independent agents **discover and call each other over plain HTTP**. Three
ideas do all the work:

- **Agent Card** — every agent publishes a business card at
  `/.well-known/agent-card.json` saying who it is and what it can do (discovery).
- **Message → Task → Artifact** — you send a **Message**; the agent runs a **Task**
  (`submitted → working → completed`) and returns an **Artifact** (the answer).
- **Two call styles** — `message/send` (ask once, get the result) and `message/stream`
  (watch it happen live over Server-Sent Events). (Plus `tasks/get` / `tasks/cancel`.)

It's **JSON-RPC 2.0 over HTTP**, protocol version `0.3.0`.

**What makes the conversation *legible*:** every message carries, in its `metadata`:

- a **performative** — the *kind* of message (a FIPA speech act), independent of its text:

  | Performative | Meaning | Used for |
  |---|---|---|
  | `request` | please do this | a manager handing over a sub-task |
  | `inform` | here's a result / fact | a worker returning its deliverable; a consult reply |
  | `cfp` | who can do X? | opening a hiring auction |
  | `propose` | I offer to do X / I bid | onboarding offers; auction bids |
  | `accept-proposal` | you're hired / I accept | awarding a role; accepting it |
  | `refuse` | not this time | releasing auction losers |
  | `query-ref` | what's X? | a **mesh** peer consult |
  | `agree` | I commit / I'm aligned | converging in the round-table |

- a small **BDI** context — the sender's **role** (who), **motivation** (why it exists),
  **intent** (what this message wants), and **delegationDepth** (how deep in the org).

So one message says *who* is speaking, *why*, *what they want*, and *what kind of act it
is*. The protocol log reads like a transcript of decisions, not opaque API calls. (BDI +
performatives live under a namespaced extension key — see
`docs/A2A_CORE_vs_ORG_EXTENSIONS.md`.)

---

## The three topologies — same team, different way of talking

The *same* hired team can coordinate three ways. Only the **wiring** changes, which is
exactly what the **Compare** mode measures.

| | **Hierarchical** | **Mesh** | **Group (round-table)** |
|---|---|---|---|
| **Shape** | manager → each report, 1:1 | reports also talk to **each other** | one shared meeting room |
| **How** | manager delegates, reports work in isolation, in parallel | a report consults a peer directly (`query-ref → inform`), bypassing the manager | the manager convenes a meeting; everyone shares **one `contextId`** and takes turns |
| **Good for** | speed, simplicity, clear control | resilience & cross-checks (peers fill each other's gaps) | reaching consensus & refining a plan together |
| **Cost** | fewest messages | more chatter | most messages, best alignment |
| **In the trip** | each specialist drafts its part alone | Itinerary checks with Weather directly | the whole team negotiates the plan out loud |

You can run **Compare all three** to see messages / tokens / latency side by side on the
same mission.

---

## How the round-table iteration works (the part that feels human)

In **Group** mode the team doesn't just answer once — it holds a **multi-round
discussion** that *refines* the plan:

- Each agent is given a **persona** (a first name) so it reads like people talking —
  e.g. *Aarav · Travel Planner*, *Diya · Food Researcher*, *Kabir · Temple Guide*.
- The conversation runs **several rounds** (`ATLAS_MEETING_ROUNDS`, default **3**). Each
  round, every agent speaks **once**, *seeing the full transcript so far* and building on it.
- The discussion has an **arc**, driven by performatives:
  - **Round 1** — `concern` / `inform`: surface issues and facts.
  - **Round 2** — `counter` / `propose`: debate and offer concrete alternatives.
  - **Round 3** — `agree`: converge and lock the decisions in.
- Costs are discussed in **₹ (Indian Rupees)**.
- The whole back-and-forth is fed into the final synthesis, so the delivered plan
  **honours what the team agreed** (e.g. *"visit Fushimi Inari early morning; the extra
  ₹500/person is worth it"*).

Each spoken turn streams to the dedicated **Agent Round-Table** panel as a chat bubble,
grouped by round and colour-coded by speech act.

---

## What you see in the UI

- **Org chart** — grows live as agents are hired and onboarded; packets flow along edges
  as messages travel.
- **A2A protocol log** — every message, tagged with its performative (click to see the
  raw JSON-RPC frame).
- **Agent Round-Table** — the multi-round negotiation, in the agents' own words.
- **Shared ledgers** — the org's task plan + progress, threaded by `contextId`.
- **Metrics** — messages, headcount, depth, tokens, elapsed.
- **Final result** — the synthesised deliverable (e.g. the Kyoto itinerary, in ₹).

---

## Configuration (`.env` / env vars)

| Variable | Default | Meaning |
|---|---|---|
| `GROQ_API_KEY` | *(empty)* | Live LLM agents. Empty → deterministic offline mock. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Any Groq chat model. |
| `ATLAS_MEETING_ROUNDS` | `3` | Round-table back-and-forth passes. |
| `ATLAS_CURRENCY` | `Indian Rupees (₹)` | Currency the agents use for costs. |
| `ATLAS_MAX_HEADCOUNT` / `ATLAS_MAX_DEPTH` | `12` / `3` | Caps that keep an emergent org bounded. |
| `ATLAS_RUNTIME` | `pooled` | `pooled` (pre-warm servers) or `dynamic` (spawn per hire). |

---

## Docs

- `docs/COMMUNICATION_PATTERNS.md` — hierarchical / mesh / group, Contract-Net, performatives
- `docs/A2A_CORE_vs_ORG_EXTENSIONS.md` — exactly what is real A2A vs. the org layer
- `docs/ARCHITECTURE.md` — processes, telemetry backbone, ledgers
- `docs/WALKTHROUGH.md` — a guided first run

> The original Smart Trip Planner prototype lives in git history at commit `2383c3f`;
> its ideas (specialist agents, an itinerary, a negotiated plan) are re-ported here as a
> mission the organisation hires for and discusses in the round-table.
