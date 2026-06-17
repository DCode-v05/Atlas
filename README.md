# ATLAS — an Organisation of Communicating A2A Agents

Give the organisation a **mission**. A **lead agent — named for the mission**
(e.g. *"Festival Director"*) — decomposes it and **hires** general-knowledge agents
by Contract-Net auction, conferring roles on them *through conversation*. Managers
recursively form sub-teams; the team then collaborates in **group meetings** over a
real, hand-rolled **A2A** protocol — and you watch every message, performative,
meeting and metric live on the **Signal Deck** UI.

A learning prototype focused on **agent-to-agent communication**:

- **Group collaboration** — the team works in shared meeting threads (one `contextId`).
- **Message-protocol design** — every message carries a FIPA *performative* plus the
  sender's *role*, *intent* and *motivation* (BDI), as an explicit A2A extension.
- **Contract-Net hiring** — roles are won by auction (`cfp → propose → accept / refuse`).
- **Coordination metrics + ledgers** — messages / tokens / depth / headcount per run;
  a Magentic-style Task + Progress ledger threaded by `contextId`.

## Quick start

This build uses a **real LLM only — there is no offline mock**, so a **Groq API key
is required**:

```bash
cp .env.example .env        # then put your GROQ_API_KEY in .env
python launch.py            # opens the Signal Deck at http://127.0.0.1:8000
```

Type a mission (or tap an example chip) and hit **Deploy**. The communication
topology is **group** (meetings).

## Verify

```bash
python scripts/demo_mission.py    # real run; asserts the expected performative handoffs
```

## Docs

- `docs/A2A_CORE_vs_ORG_EXTENSIONS.md` — exactly what is real A2A vs. the org layer
- `docs/ARCHITECTURE.md` — processes, telemetry backbone, ledgers
- `docs/COMMUNICATION_PATTERNS.md` — performatives, Contract-Net, group meetings, recursion
- `docs/WALKTHROUGH.md` — a guided first run

> The previous trip-planner prototype lives in git history at commit `2383c3f`.
