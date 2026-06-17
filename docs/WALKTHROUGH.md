# Walkthrough — your first ATLAS run

The "just show me" doc. We'll start the app, watch one mission unfold on the
**Signal Deck**, then run the acceptance script so you trust what you saw.

---

## Step 0 — A Groq key (required)

This build uses a **real LLM only — there is no offline mock**, so you need a
free [Groq API key](https://console.groq.com/keys):

```bash
cp .env.example .env        # then put your GROQ_API_KEY in .env
```

---

## Step 1 — Start it

```bash
python launch.py
```

That pre-warms the employee pool, starts the gateway, and opens your browser at
**http://127.0.0.1:8000**. The badge top-right shows `Groq · <model>` when your
key is live (or `GROQ_API_KEY required` if it's missing).

---

## Step 2 — Give the organisation a mission

In the console at the top, type a mission (or tap an example chip — e.g.
*"Plan a weekend coffee festival for 5,000 attendees"*) and hit **Deploy**.

There is **no topology picker**: the organisation always collaborates in
**group meetings**. Under the hood the browser calls `POST /api/run` and then
subscribes to the live event stream at `/api/stream`.

---

## Step 3 — What you're watching

```
┌──────────────────────────────────────────────────────────────┐
│  HUD:  messages · headcount · max depth · tokens · elapsed     │
├───────────────────────────────┬──────────────────────────────┤
│  02 / ORG GRAPH               │  03 / SIGNAL FEED             │
│  (grows; packets fly the wire)│  (every message + performative)│
├───────────────────────────────┴──────────────────────────────┤
│  04 / SHARED LEDGERS:  Task ledger  |  Progress ledger         │
├──────────────────────────────────────────────────────────────┤
│  05 / DELIVERABLE  (the org's synthesised result)              │
└──────────────────────────────────────────────────────────────┘
```

- **HUD metrics** — live `messages`, `headcount`, `max depth`, `tokens`, `elapsed`.
- **Org graph** — starts with just **You** (the Board), then the **lead agent
  appears** — *named for your mission* (a book fair gets a "Book Fair Manager",
  a festival a "Festival Director"). Its reports and any sub-teams grow in;
  ice-cyan **packets** travel the edges as messages fly, tinted by performative.
- **Signal feed** — every A2A message, tagged with its **performative**. You'll
  see the handshake in order: `propose` (onboard the lead) → `accept-proposal` →
  `request` (the mission) → `cfp` → `propose` (bids) → `accept-proposal` /
  `refuse` (the hiring auction) → meeting `request`s → `inform` (results).
  Click any row to expand its raw JSON.
- **Shared ledgers** — the **Task ledger** (the plan + facts the lead wrote) and
  the **Progress ledger** (a row per delegated step).
- **Deliverable** — the org's synthesised result, rendered as Markdown.

---

## Step 4 — Verify with the scripts

```bash
python scripts/demo_mission.py
```

The acceptance run. It runs one mission (real Groq, group topology) and prints a
report — the org tree it built, the performative counts, the **mission-derived
lead title** — and a checklist that **verifies** the handshakes:

- onboarding `propose -> accept-proposal`;
- the hiring auction `cfp -> propose -> accept-proposal -> refuse`;
- delegation `request -> inform`;
- a shared group-meeting `contextId`;
- caps respected (headcount + depth).

Ends with `ALL CHECKS PASSED`.

| Script                       | What it proves                                                                                  |
| ---------------------------- | ----------------------------------------------------------------------------------------------- |
| `scripts/demo_mission.py`    | **The acceptance run** (above): a real group mission + the full performative-handoff checklist. |
| `scripts/smoke_protocol.py`  | The **pure A2A layer**, no org code, no LLM: Agent Card discovery, `message/send`, `message/stream` (SSE), an `input-required` pause, `protocolVersion 0.3.0`. (No key needed.) |
| `scripts/smoke_dynamic.py`   | The **dynamic runtime** (`ATLAS_RUNTIME=dynamic`): a mission completes over genuinely **separate OS processes** per hire (not threads). |

---

## Where to go next

- **"Is this really A2A?"** → `docs/A2A_CORE_vs_ORG_EXTENSIONS.md`
- **"What are all these processes and ports?"** → `docs/ARCHITECTURE.md`
- **"What do the performatives mean?"** → `docs/COMMUNICATION_PATTERNS.md`

Stop everything with **Ctrl+C** in the terminal running `launch.py`.
