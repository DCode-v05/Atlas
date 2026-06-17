# Walkthrough — your first ATLAS run

Welcome! This is the "just show me" doc. We'll start the app, watch one mission
unfold in the UI, then run the test scripts so you trust what you saw. No prior
A2A knowledge needed — though if you want the *why*, read the other three docs in
`docs/` after this.

---

## Step 1 — Start it

From the project root:

```bash
python launch.py
```

That single command pre-warms the employee pool, starts the gateway, and opens
your browser at **http://127.0.0.1:8000**. You'll see a banner like:

```
============================================================
  ATLAS - an organisation of communicating A2A agents
============================================================
  pre-warming 8 employees (pooled runtime)...
  gateway live -> http://127.0.0.1:8000/
  caps: headcount <= 12 | depth <= 3 | budget 150,000 tokens
  Ctrl+C to stop.
```

**No API key needed.** With no key, ATLAS runs on a **deterministic offline
mock** — perfect for demos and the tests, and reproducible run-to-run. Want a
real LLM? Copy `.env.example` to `.env` and add a `GROQ_API_KEY`; the badge in the
UI's top-right will switch from `deterministic-mock` to the model name.

---

## Step 2 — Give the organisation a mission

In the console at the top of the page:

1. Type a mission (or use the placeholder, *"Design and spec a privacy-first
   smart doorbell"*).
2. Pick a **topology** from the selector:
   - **Hierarchical** — 1:1 delegation, in parallel.
   - **Mesh (peer-to-peer)** — reports also consult each other.
   - **Group (meetings)** — a round-robin meeting on one shared thread.
   - **Compare all three** — runs the same mission three ways, side by side.
3. Click **Start mission →**.

Under the hood the browser calls `POST /api/run` (or `POST /api/compare` for
compare), then subscribes to the live event stream at `/api/stream`.

---

## Step 3 — What you're watching

The page comes alive as telemetry streams in. Here's each panel:

```
┌───────────────────────────────────────────────────────────┐
│  metrics:  messages · headcount · max depth · tokens · time│
├──────────────────────────┬────────────────────────────────┤
│  Org chart               │  A2A protocol log              │
│  (grows as agents hired) │  (every message + performative)│
├──────────────────────────┴────────────────────────────────┤
│  Shared ledgers:  Task ledger  |  Progress ledger          │
├───────────────────────────────────────────────────────────┤
│  Result  (the org's synthesised answer)                    │
└───────────────────────────────────────────────────────────┘
```

- **Metrics bar** — live counts of `messages`, `headcount`, `max depth`,
  `tokens`, and `elapsed`. Watch messages climb as the org coordinates.
- **Org chart** — starts empty ("No agents yet"), then grows: the **CEO** appears
  first (hired by the Board), then its reports, then any sub-team. Each node shows
  a role and updates its status as it works.
- **A2A protocol log** — the star of the show. Every message on the wire, tagged
  with its **performative**. You'll watch the handshake in order:
  `propose` (onboard the CEO) → `accept-proposal` → `request` (the mission) →
  `cfp` → `propose` (bids) → `accept-proposal` / `refuse` (the auction) →
  `request` (sub-tasks) → `inform` (results).
- **Shared ledgers** — the **Task ledger** (the plan + facts the CEO wrote when it
  decomposed) and the **Progress ledger** (a row per delegated step: who, doing
  what, status).
- **Result** — when the run finishes (`run:done`), the org's synthesised answer
  renders here as Markdown.

If you chose **Compare all three**, a comparison panel shows the three runs
side-by-side — *same mission, same hired team, only the communication pattern
differs* — so you can see mesh chat more and group take longer. (Compare forces
the deterministic mock so the comparison is fair; see
`COMMUNICATION_PATTERNS.md`.)

---

## Step 4 — Verify with the scripts

The UI is the *experience*; the scripts are the *proof*. They each set
`ATLAS_FORCE_MOCK=1`, so they need no API key and run deterministically. Run them
from the project root.

### The acceptance run — `demo_mission.py`

```bash
python scripts/demo_mission.py
```

Run this one first. It runs the mission under **all three topologies**
(deterministic mock — no key needed) and prints a readable report: the org tree
it built, the performative counts, and a checklist that **verifies** the
handshakes you watched in the UI —

- onboarding `propose -> accept-proposal`;
- the hiring auction `cfp -> propose -> accept-proposal -> refuse`;
- delegation `request -> inform`;
- mesh peer consults (`query-ref`) and group meeting contexts;
- recursion — a report became a sub-manager (`depth >= 2`);
- caps respected, and the **identical team** hired across all three topologies.

Ends with `ALL CHECKS PASSED`. (`scripts/smoke_org.py` is the same idea for a
single run if you want something shorter.)

### The other smoke scripts and what each proves

| Script                          | What it proves                                                                                   |
| ------------------------------- | ----------------------------------------------------------------------------------------------- |
| `scripts/demo_mission.py`       | **The acceptance run** (above): all three topologies + the full performative-handoff checklist + determinism. Run this first. |
| `scripts/smoke_protocol.py`     | The **pure A2A layer**, no org code. Calls the FastAPI app in-process (no server): Agent Card discovery, `message/send`, `message/stream` (SSE), and an `input-required` pause. Confirms `protocolVersion` `0.3.0`. |
| `scripts/smoke_org.py`          | The **end-to-end org run** (above): completion, metrics, the performative handoffs, the org tree.|
| `scripts/smoke_topologies.py`   | Runs the same mission under **all three topologies** and asserts the key claim: **same team, different conversations** — identical roles/headcount, but mesh has peer consults (`query-ref > 0`) and chats more, and group holds meetings + opens extra contexts. |
| `scripts/smoke_compare.py`      | Exercises the **`/api/compare`** endpoint: three runs kick off, all complete, compose the **identical** team (determinism held), and the metric deltas are present (mesh > hierarchical messages). |
| `scripts/smoke_dynamic.py`      | Proves the **dynamic runtime** (`ATLAS_RUNTIME=dynamic`): a mission completes over genuinely **separate OS processes** per hire (not threads), with `>= 2` real processes spawned. |

A good first session: run `smoke_protocol.py` (see the protocol is real), then
`smoke_org.py` (see the org is real), then `smoke_topologies.py` (see the
topologies differ). Together they walk you from "this is genuine A2A" up to "and
here is the organisation we built on top."

---

## Where to go next

- **"Is this really A2A?"** → `docs/A2A_CORE_vs_ORG_EXTENSIONS.md`
- **"What are all these processes and ports?"** → `docs/ARCHITECTURE.md`
- **"What do the performatives and topologies mean?"** →
  `docs/COMMUNICATION_PATTERNS.md`

Stop everything with **Ctrl+C** in the terminal running `launch.py`.
