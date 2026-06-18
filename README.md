# ⚡ Atlas — A2A Control Tower

A real-time **mission-control dashboard** that visualizes **agent-to-agent (A2A)
communication** inside a simulated software company of **100 AI agents**.

Atlas is about **how agents communicate like humans** — discovering each other,
sharing only what's needed-to-know, redacting or escalating sensitive data to a
human, coordinating 1:1 vs in groups, and carrying *intent* on every message —
not about how well they finish tasks. It implements the
[A2A protocol](https://a2a-protocol.org) faithfully in-process, with an
organisation-specific need-to-know policy layer on top.

## What you can see & do

- **100 agents** across 12 departments with a real hierarchy, each an A2A
  **Agent Card** with skills, clearance, and private/sensitive context.
- **Live communication graph** — who is talking to whom, individually vs in
  groups, with edges colored by **intent** and **outcome** (shared / redacted /
  withheld / awaiting-approval).
- **Task an agent** with a prompt → watch it get routed, discover colleagues,
  and request context — with sensitive items **redacted** or **escalated**.
- **Human-in-the-loop queue** — approve / redact / deny sensitive shares as the
  single control-tower operator.
- **Out-of-scope gate** — prompts unrelated to the company are blocked.
- **Cron simulation** — toggle a 15-second burst of autonomous agent activity.
- **Coordination-efficiency metrics** — hops, messages, shared vs redacted vs
  withheld, redundant contacts avoided, HITL escalations.

## Quick start

Atlas runs **real Groq agents** and requires a key (no simulated mode):

```bash
echo "GROQ_API_KEY=gsk_your_key_here" > .env    # gitignored; get one at console.groq.com/keys

# Single container (API + UI):
docker compose up --build      # → http://localhost:8000

# …or local dev:
uv sync && uv run python -m atlas          # backend on :8000
cd web && npm install && npm run dev       # UI on :5173 (proxies to :8000)
```

Then open the UI and try the suggested prompts (e.g. *"Fix the billing Stripe
payment integration and get the API credentials"* → escalates to approval;
*"What is the Q3 launch date?"* → redacted; *"What's the weather in Paris?"* →
gated), or hit **SIMULATE** to watch the org light up.

## Groq (required)

Atlas runs **real Groq agents on every path** — user prompts *and* the cron
simulation. The LLM generates every agent message, re-ranks routing, and makes
the (tighten-only) share-vs-redact judgement. **There is no simulated mode**: set
`GROQ_API_KEY` or the app exits with a clear error. Models are configurable
(`ATLAS_GROQ_REASONING_MODEL`, `ATLAS_GROQ_PHRASING_MODEL`).

## Tech

Python · FastAPI · Pydantic v2 · SSE · React 18 · Vite · TypeScript · Tailwind ·
react-force-graph · Zustand · Groq (optional).

See **[CLAUDE.md](./CLAUDE.md)** for the architecture, the need-to-know policy
matrix, and the full design. `uv run pytest` runs the test suite.
