# ATLAS — an Organisation of Communicating A2A Agents

Give the organisation a **mission**. A **CEO agent** decomposes it and **hires**
general-knowledge agents, conferring roles on them *through conversation*. Managers
recursively form sub-teams. Everyone talks over a real, hand-rolled **A2A** protocol
— and you watch every message, performative, meeting and metric live.

This is a learning prototype focused on **agent-to-agent communication**:

- **Topologies** — hierarchical, mesh, and group "meetings" (and a mode to *compare* them).
- **Message-protocol design** — every message carries a FIPA *performative* plus the
  sender's *role*, *intent* and *motivation* (BDI), as an explicit A2A extension.
- **Coordination efficiency** — messages, tokens, latency, depth and headcount per run.
- **Context persistence** — Magentic-style Task + Progress ledgers, threaded by `contextId`.

## Quick start

```bash
python launch.py        # starts everything and opens the UI at http://127.0.0.1:8000
```

No API key? It runs on a **deterministic offline mock** (perfect for demos and the test
suite). Add a Groq key in `.env` (copy `.env.example`) for live LLM agents.

## Verify

```bash
python scripts/demo_mission.py    # scripted run; asserts the expected performative handoffs
```

## Docs

- `docs/A2A_CORE_vs_ORG_EXTENSIONS.md` — exactly what is real A2A vs. the org layer
- `docs/ARCHITECTURE.md` — processes, telemetry backbone, ledgers
- `docs/COMMUNICATION_PATTERNS.md` — hierarchical / mesh / group, Contract-Net, performatives
- `docs/WALKTHROUGH.md` — a guided first run

> The previous trip-planner prototype lives in git history at commit `2383c3f`.
