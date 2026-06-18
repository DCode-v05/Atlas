# Atlas — A2A Agent-to-Agent Communication Platform

Atlas is a demonstrator of **how agents communicate, like humans**, inside a
simulated software company of **exactly 100 agents**. It is built on a faithful,
in-process implementation of the [A2A protocol](https://a2a-protocol.org), with
an organisation-specific **need-to-know** layer on top.

The project's goal is the **quality and efficiency of communication** — routing,
discovery, need-to-know sharing, redaction, human-in-the-loop escalation, 1:1 vs
group coordination, intent-carrying messages, and an out-of-scope gate. It is
**not** task-outcome oriented; agents demonstrate *how they talk*, not how well
they finish work.

---

## Mental model (read this first)

Two layers, never conflated:

- **External edge** (`atlas/api`, `atlas/events`): the only real sockets. A REST
  API + an **SSE** stream between the browser and the backend.
- **Internal bus** (`atlas/bus`): agent↔agent communication is in-process Python
  dispatch through a central **Router** that reproduces A2A method semantics
  (`message/send`, `tasks/get`, …). The Router is the single chokepoint where
  discovery, the policy engine, metrics, and event emission are enforced — agents
  cannot bypass it. 100 agents live in one process, not 100 servers.

Other invariants:

- **Determinism**: one `ATLAS_SEED` drives the org generator, the cron
  simulation, and the simulated-LLM phrasing. Same seed ⇒ identical company.
- **Idle semantics**: "100 agents running continuously" = a registry of 100
  agent objects with a live `status` + heartbeat, woken event-driven by the
  Router or cron. Idle = alive heartbeat + zero chatter (not 100 hot loops).
- **Single worker**: uvicorn runs one worker so the in-process bus stays coherent.

---

## The organisation

`generate_org(seed)` deterministically builds a true hierarchy tree of exactly
100 agents (CEO → Dept Heads → Managers/Leads → ICs):

| Dept | Head | Mgr/Lead | IC | Total |
|---|--:|--:|--:|--:|
| Exec (CEO) | — | — | — | 1 |
| Engineering | 1 | 6 | 33 | 40 |
| Product · QA | 1·1 | 1·1 | 6·6 | 8·8 |
| DevOps · Sales | 1·1 | 1·1 | 5·5 | 7·7 |
| Design · Data | 1·1 | 1·1 | 4·4 | 6·6 |
| Marketing · Support | 1·1 | 1·1 | 3·3 | 5·5 |
| Security · HR | 1·1 | 1·0 | 2·2 | 4·3 |

Every non-CEO has a resolvable `reports_to`; `clearance == level` (IC=1 … CEO=5);
agents belong to teams + 3 projects (`atlas-core`, `billing`, `mobile`). ~18
**project secrets** are seeded as `ContextItem`s spanning every sensitivity tier.

## A2A fidelity + the org-extension mechanism

Core A2A types live in `atlas/a2a` (`AgentCard`, `Message`, `Part`, `Task` +
`TaskState`, `Artifact`, `AgentExtension`). Org concepts attach via the A2A
**extensions** mechanism — never by polluting core. Three URIs:

- `urn:atlas:ext:org-profile:v1` — dept/role/level/reportsTo/clearance on the card
- `urn:atlas:ext:need-to-know:v1` — sensitivity + scope on items; **intent** on messages
- `urn:atlas:ext:coordination:v1` — group + HITL signalling

## The need-to-know policy engine (the graded core — `atlas/policy`)

`evaluate_share(requester, owner, item, intent)` returns a `ShareDecision`
(`SHARE` / `REDACT` / `DENY` / `ESCALATE`) with a human-readable `reason` and a
`rule_id`. A request lands in one of five **columns** by (scope-match × clearance
× intent legitimacy); the column + sensitivity selects the outcome:

| Sensitivity | exact&legit | exact&weak | related | out/under-cleared | illegitimate |
|---|---|---|---|---|---|
| public | SHARE | SHARE | SHARE | SHARE | SHARE |
| internal | SHARE | SHARE | SHARE | REDACT | DENY |
| confidential | SHARE | REDACT | REDACT | DENY | DENY |
| restricted | REDACT | ESCALATE | ESCALATE | DENY | DENY |
| secret | ESCALATE | ESCALATE | DENY | DENY | DENY |

Loosen-only overrides apply after the matrix (manager↔report `CHAIN1`, `CEO1`,
security-incident `SEC1`), then a hard **SECRET cap**: a secret's loosest possible
outcome is ESCALATE — no override ever leaks it. An optional Groq pass may only
**tighten** the decision, never loosen it (the rule-based result is the floor).

## How a prompt flows (`atlas/conversation/orchestrator.py`)

```
prompt → org-scope gate → Level-1 route (→ best agent) → open Task →
  agent identifies context needs → Level-2 discovery (→ owners) →
    for each owner: ask (with intent) → policy decides →
      SHARE / REDACT / DENY / ESCALATE→HITL (task input-required, operator approves) →
    or form a GROUP session when the prompt is about team coordination →
  finalize Task → metrics emitted
```

The **cron simulator** (`atlas/cron`) toggles a ~15s burst that drives this exact
pipeline from autonomous, seeded agent-initiated tasks. **Metrics**
(`atlas/metrics`) are computed at the Router: hops, messages, shared/redacted/
denied, redundant-contacts-avoided, HITL escalations, distinct agents contacted.

## LLM boundary (`atlas/llm`) — real Mistral on Amazon Bedrock, required

`BedrockProvider` is the **only** provider and drives **both** the user-prompt and
cron paths: it generates every agent message, re-ranks routing, and gives the
tighten-only share judgement via the Bedrock **Converse API** (boto3, run in a
worker thread since boto3 is sync). Two configurable Mistral model ids
(`ATLAS_BEDROCK_REASONING_MODEL` / `ATLAS_BEDROCK_PHRASING_MODEL`, default
`mistral.mistral-large-2402-v1:0`). **AWS credentials are required — a Bedrock API
key (`AWS_BEARER_TOKEN_BEDROCK`, bearer token) or classic access key/secret, plus a
region; without them the app raises at startup.** Secret payloads are appended
verbatim so the LLM can't drop them. Rate-limit safety: a **per-model token bucket
with a small burst cap** (paces calls so a 100-agent cron burst can't storm Bedrock),
concurrency limit, SDK retries off, and a self-healing cooldown on
`ThrottlingException` — throttle state is emitted as an `llm.status` event. The
`phrasing.py` templates remain only as a per-message safety net if a live call
momentarily fails — not a mode, not a provider.

---

## Run it

**Docker (single container — API + UI):** requires Bedrock credentials.
```bash
printf 'AWS_BEARER_TOKEN_BEDROCK=...\nAWS_REGION=us-east-1\n' > .env   # gitignored
docker compose up --build                                            # → http://localhost:8000
```

**Local dev:**
```bash
uv sync                                   # backend deps
uv run python -m atlas                    # backend on :8000  (serves web/dist if built)
# in another shell, for live frontend dev with HMR:
cd web && npm install && npm run dev      # → http://localhost:5173 (proxies /api to :8000)
```

**Tests:** `uv run pytest` (53 tests: org golden snapshot, exhaustive policy
matrix + SECRET-cap invariant, orchestrator HITL flow, group need-to-know,
LLM wiring + payload guard, Groq-key requirement, cron, API integration).
Tests inject an offline LLM double, so they run without a key.

**Frontend typecheck:** `cd web && npm run typecheck`

## Key environment variables (`.env.example`)

**`AWS_BEARER_TOKEN_BEDROCK`** (Bedrock API key) **or** `AWS_ACCESS_KEY_ID` +
`AWS_SECRET_ACCESS_KEY` — **required** · `AWS_REGION` (us-east-1) · `ATLAS_SEED` (42) ·
`ATLAS_CRON_BURST_SECONDS` (15) · `ATLAS_HITL_TIMEOUT_SECONDS` (0) ·
`ATLAS_BEDROCK_REASONING_MODEL` / `ATLAS_BEDROCK_PHRASING_MODEL` (model overrides).

## Repo layout

```
atlas/   a2a/ (protocol)  org/ (company+generator)  bus/ (router/discovery)
         policy/ (need-to-know)  conversation/ (orchestrator/threads/groups)
         hitl/  cron/  llm/  metrics/  events/ (SSE schema = the FE contract)
         api/  store/  main.py  runtime.py  config.py
web/     React + Vite + TS mission-control UI (force-graph, Zustand, SSE)
tests/   pytest suite     Dockerfile · docker-compose.yml
```

## The frontend contract

`atlas/events/schema.py` is the **single source of truth** for SSE events;
`web/src/types.ts` mirrors it and the SSE client warns on drift. The frontend
develops against the real backend (Vite proxy → :8000), no mock emitter.
