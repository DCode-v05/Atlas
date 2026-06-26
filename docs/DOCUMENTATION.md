# Atlas — Complete Documentation

> **Atlas** is a demonstrator of **how AI agents communicate, like humans**, inside a
> simulated software company of **exactly 100 agents**, built on a faithful, in-process
> implementation of the [A2A (Agent-to-Agent) protocol](https://a2a-protocol.org) with an
> organisation-specific **need-to-know** layer on top — and an optional **federation** of
> many such companies that talk to each other publicly.

This is the single, complete reference: what Atlas is, everything it can do, how every part
works, and how to run and extend it. For the dense engineering contract see
[`../CLAUDE.md`](../CLAUDE.md); for the deterministic compliance rules see
[`policy.md`](policy.md); for the A2A spec-coverage matrices see
[`a2a-implemented.md`](a2a-implemented.md) and siblings.

---

## Table of contents

1. [What Atlas is (and is not)](#1-what-atlas-is-and-is-not)
2. [Quick start — run it](#2-quick-start--run-it)
3. [Mental model — two layers](#3-mental-model--two-layers)
4. [The organisation — 100 agents](#4-the-organisation--100-agents)
5. [A2A protocol fidelity](#5-a2a-protocol-fidelity)
6. [How a prompt flows — the pipeline](#6-how-a-prompt-flows--the-pipeline)
7. [The need-to-know decision](#7-the-need-to-know-decision)
8. [The Policy Engine](#8-the-policy-engine)
9. [Human-in-the-loop (HITL)](#9-human-in-the-loop-hitl)
10. [The cron simulator](#10-the-cron-simulator)
11. [Metrics](#11-metrics)
12. [The LLM boundary — Mistral on Bedrock](#12-the-llm-boundary--mistral-on-bedrock)
13. [Persistence + the authenticated network](#13-persistence--the-authenticated-network)
14. [Multi-org federation](#14-multi-org-federation)
15. [The frontend — mission control](#15-the-frontend--mission-control)
16. [Complete API reference](#16-complete-api-reference)
17. [SSE events reference](#17-sse-events-reference)
18. [Configuration reference](#18-configuration-reference)
19. [Testing](#19-testing)
20. [Repo layout](#20-repo-layout)
21. [What you can do with Atlas — scenarios](#21-what-you-can-do-with-atlas--scenarios)
22. [Glossary](#22-glossary)

---

## 1. What Atlas is (and is not)

Atlas simulates a **100-person software company** where every employee has an **AI agent**.
The agents talk to each other to get work done — discovering who knows what, asking for
context, sharing or refusing based on **need-to-know**, escalating to a human when a decision
is sensitive, and coordinating 1:1 or as a group.

The project's goal is the **quality and efficiency of communication** — routing, discovery,
need-to-know sharing, redaction, human-in-the-loop escalation, 1:1 vs group coordination,
intent-carrying messages, and an out-of-scope gate. It demonstrates *how agents talk*, not how
well they finish a task.

- **It is**: a faithful, in-process A2A protocol implementation; a real organisation with a
  hierarchy, secrets, and humans; a real LLM (Mistral on Amazon Bedrock) authoring every
  message and making the sharing judgements; a deterministic compliance engine; a live
  mission-control UI; optional Postgres persistence + an authenticated network; and an optional
  federation of many companies.
- **It is not**: task-outcome oriented; a chatbot; a mock. There are **no message templates** —
  every agent line is genuine Mistral, or it is omitted.

**Determinism**: one `ATLAS_SEED` drives the whole company generator, the cron sequence, and
phrasing variety. Same seed ⇒ identical company, every run.

---

## 2. Quick start — run it

Atlas **requires** Amazon Bedrock credentials (a Bedrock API key **or** classic AWS
access key/secret) — there is no simulated fallback; agents speak real Mistral or stay silent.

### Docker (single container — API + UI + Postgres)

```bash
printf 'AWS_BEARER_TOKEN_BEDROCK=...\nAWS_REGION=us-east-1\n' > .env   # gitignored
docker compose up --build                                            # → http://localhost:8000
```

The compose stack bundles a Postgres service and turns on persistence + the authenticated
network by default. With the DB on, **the network starts empty** — open the UI's **Network**
tab and click **Join all** to bring agents online (this is by design; see §13).

### Local development

```bash
uv sync                                   # backend deps
uv run python -m atlas                    # backend on :8000 (serves web/dist if built)
# in another shell, for live frontend dev with hot reload:
cd web && npm install && npm run dev      # → http://localhost:5173 (proxies /api to :8000)
```

For the **always-live** original demo (no membership gating), leave `ATLAS_DATABASE_URL`
unset → Atlas runs fully in-memory and every agent is live immediately.

---

## 3. Mental model — two layers

Atlas keeps two layers strictly separate — never conflate them:

- **External edge** (`atlas/api`, `atlas/events`, `atlas/push`) — the only real network sockets.
  A REST API + a Server-Sent-Events (**SSE**) stream between the browser and the backend, with
  opt-in API-key edge auth and outbound **A2A push-notification webhooks** that POST task-state
  updates to clients registered per task.
- **Internal bus** (`atlas/bus`) — agent↔agent communication is **in-process Python dispatch**
  through a central **Router** that reproduces A2A method semantics (`message/send`,
  `tasks/get`, …). The Router is the single chokepoint where discovery, need-to-know, metrics,
  and event emission are enforced — agents cannot bypass it. **100 agents live in one process,
  not 100 servers.**

Other invariants:

- **Single worker** — uvicorn runs one worker so the in-process bus stays coherent.
- **Idle semantics** — "100 agents running continuously" = a registry of 100 agent objects with
  a live `status` + heartbeat, woken event-driven by the Router or cron. Idle = alive heartbeat
  + zero chatter (not 100 hot loops).
- **The frontend contract** — `atlas/events/schema.py` is the single source of truth for SSE
  events; `web/src/types.ts` mirrors it and the SSE client warns on drift.

---

## 4. The organisation — 100 agents

`generate_org(seed)` deterministically builds a true hierarchy tree of exactly **100 agents**
(CEO → Department Heads → Managers/Leads → Individual Contributors):

| Dept | Head | Mgr/Lead | IC | Total |
|---|--:|--:|--:|--:|
| Exec (CEO) | — | — | — | 1 |
| Engineering | 1 | 6 | 33 | 40 |
| Product · QA | 1·1 | 1·1 | 6·6 | 8·8 |
| DevOps · Sales | 1·1 | 1·1 | 5·5 | 7·7 |
| Design · Data | 1·1 | 1·1 | 4·4 | 6·6 |
| Marketing · Support | 1·1 | 1·1 | 3·3 | 5·5 |
| Security · HR | 1·1 | 1·0 | 2·2 | 4·3 |

Every non-CEO has a resolvable `reports_to`; `clearance == level` (IC=1 … CEO=5). Agents belong
to **teams** and **3 projects** (`atlas-core`, `billing`, `mobile`). Each agent carries:

- a **`goal`** — a standing responsibility for its department + seniority (CEO=strategy,
  head=own-the-area, lead=coordinate, IC=execute): the agent analogue of a human's job;
- exactly one **`User`** (1:1) — the human behind the agent. `POST /api/prompt` may carry a
  `user_id` to attribute a prompt to that user (and the agent they operate); `GET /api/users`
  lists the directory.

**~18 project secrets** are seeded as `ContextItem`s spanning every sensitivity tier
(**PUBLIC → INTERNAL → CONFIDENTIAL → RESTRICTED → SECRET**), with a scope (org / project /
team / role / private), a minimum clearance, topic tags, and a pre-authored safe **redacted
summary**. These are the things agents ask each other for.

---

## 5. A2A protocol fidelity

Core A2A types live in `atlas/a2a`: `AgentCard`, `Message`, `Part` (`TextPart` / `DataPart` /
`FilePart`), `Task` + `TaskState`, `Artifact`, `AgentExtension`, named A2A errors. Org concepts
attach via the A2A **extensions** mechanism — never by polluting core. Three extension URIs:

- `urn:atlas:ext:org-profile:v1` — dept/role/level/reportsTo/clearance/goal on the card.
- `urn:atlas:ext:need-to-know:v1` — sensitivity + scope on items; **intent** on messages.
- `urn:atlas:ext:coordination:v1` — group + HITL signalling.

Implemented A2A v1.0.0 surface (see [`a2a-implemented.md`](a2a-implemented.md) for the matrix):

- **Agent Cards** — public vs authenticated **extended** card tiering (`public_agent_card`
  strips the org-profile; `extended_agent_card` includes it). `iconUrl`, `documentationUrl`,
  `defaultInputModes`/`defaultOutputModes`, capability `extensions`.
- **Discovery** — well-known endpoints (`/.well-known/agent-card.json`, `/agents.json`,
  per-agent cards).
- **Tasks** — `Task` + `TaskState` lifecycle (`submitted → working → input-required →
  completed/failed/canceled`, plus `rejected` and `auth-required`), `GetTask` (with
  `historyLength`), `ListTasks` (filters + cursor pagination), `tasks/cancel`,
  `referenceTaskIds`.
- **Messages / parts** — `TextPart`, `DataPart` (structured outcome record), `FilePart`
  (URL-only variant, e.g. a pointer to the owner's agent card).
- **The `/v1` HTTP+JSON binding** — spec-shaped colon-verb paths (`/v1/message:send`,
  `/v1/tasks/{id}:cancel`, `/v1/tasks/{id}:subscribe`), version + extension negotiation
  (`A2A-Version`, `A2A-Extensions`), named A2A error types with JSON-RPC codes mapped to HTTP
  status, required-extension enforcement.
- **Streaming** — per-task SSE subscription emitting spec-shaped `StreamResponse` frames; the
  ordered-event + terminal-close contract.
- **Push notifications** — register a webhook per task; Atlas POSTs a status update on every
  state change (`pushNotificationConfig` set/get/list/delete).

---

## 6. How a prompt flows — the pipeline

The orchestrator (`atlas/conversation/orchestrator.py`) drives this. **The judgement calls are
LLM-decided; only facts (who-owns-what, team rosters) are not.**

```
prompt → org-scope gate (LLM-judged) → Level-1 route (→ best agent) → open Task →
  agent identifies context needs → Level-2 discovery (→ owners) →
    for each owner: ask (with intent) → Policy pre-gate (deterministic floor):
        · floor already DENY/ESCALATE → decide outright, skip the owner LLM
        · else → owner LLM decides → Policy Engine reviews (tighten-only)
      → SHARE / REDACT / DENY / ESCALATE→HITL (task input-required, operator approves) →
    or form a GROUP session when Mistral decides to coordinate the team →
  finalize Task → metrics emitted
```

Stage by stage:

1. **Org-scope gate** (Mistral, lexical fallback) — admits company requests **and
   greetings/social pleasantries** (a bare "hi" routes to the CEO for a friendly reply), and
   blocks non-company topics ("write me a poem" → rejected).
2. **Level-1 routing** (fully LLM) — Mistral reads the **whole directory** (all 100 agent cards:
   id, name, role, dept, skills) and picks the owning agent. A deterministic skill-scorer is the
   fallback when the LLM is down.
3. **Open a Task** — the A2A `Task` that tracks this prompt's lifecycle.
4. **Identify context needs** — the routed agent works out which seeded items it needs.
5. **Level-2 discovery** — find the owner of each needed item.
6. **Need-to-know decision** per owner — the two-layer decision (see §7).
7. **Apply the decision** — SHARE (full), REDACT (safe summary), DENY (refuse), or
   ESCALATE → HITL (park `input-required`, operator approves).
8. **Grouping** (LLM-decided) — Mistral may choose to coordinate as a group, pulling in
   teammates **only from the agent's real team roster** (it never invents people).
9. **Finalize** — the Task completes with a summary artifact (a `TextPart` + a `DataPart`
   structured outcome + a `FilePart` pointer to the owner's card); metrics are emitted.

Greetings short-circuit to a one-line reply. The **cron path skips the org-scope gate** (goals
are in-scope by construction).

---

## 7. The need-to-know decision

**Two layers — an LLM owner-decision under a deterministic compliance floor.**

### Layer 1 — the owner decides (LLM), under a policy pre-gate

`llm.decide_share(requester, owner, item, intent)` returns **SHARE / REDACT / DENY /
ESCALATE** from the model's own judgement, weighing sensitivity, the requester's
role/clearance/teams/projects, and their stated reason — it may even choose to share a
confidential record.

**Cost/latency pre-gate**: the deterministic floor (Layer 2) is computed *first*. When it
already forces a **DENY or ESCALATE** (every denial; everything escalated — secrets via
four-eyes, out-of-scope restricted), the owner's LLM is **skipped** (the model cannot loosen a
deny, and an escalation needs a human regardless) — metered as `policy_pregates`. The model is
consulted only where its judgement can still change the result (SHARE / REDACT floors). If the
owner's LLM is unreachable on that remaining path, the decision **ESCALATEs to the human
operator** (HITL, `rule_id="LLM-UNAVAILABLE"`) — never decided arbitrarily by code.

### Layer 2 — the deterministic Policy Engine (compliance review)

The owner's decision passes through the **`atlas/policy` Policy Engine**, a **tighten-only**
ABAC control that may **tighten** (redact / escalate / deny) but never loosen — the auditable,
codified compliance floor a real security/compliance function provides. It replaced a former
LLM "Policy Officer" agent. The same floor doubles as the pre-gate above.

So the call is the **model's**, the **policy's** (denials/secrets), or a **person's** — never an
arbitrary outcome matrix's.

---

## 8. The Policy Engine

`atlas/policy` folds the owner's decision together with ~12 single-action rules, taking the
**most-restrictive-wins** outcome on the lattice **`SHARE < REDACT < ESCALATE < DENY`**
(OASIS XACML 3.0 *deny-overrides* / AWS IAM). The result is always ≥ the owner's decision
(tighten-only). Each rule cites a named framework. Full table + sources: [`policy.md`](policy.md).

| Rule | Floors to | When | Framework |
|---|---|---|---|
| Cross-organisation boundary | Deny | a federation request for anything above PUBLIC | NIST 800-53 AC-4/AC-21 |
| Clearance gate | Deny | requester clearance < item min-clearance | Bell–LaPadula / NIST AC-3 |
| Need-to-know | Redact | out of scope, confidential/restricted (non-incident) | PCI Req 7 / NIST AC-6 |
| Least-privilege escalate | Escalate | out of scope, restricted+ (non-incident) | PCI Req 7 / AWS IAM |
| Payment secret | Deny / Escalate | live payment/API secret (nexus → escalate) | PCI-DSS Req 3 & 7 |
| PII purpose | Deny | personal data for a social/non-business reason | GDPR Art. 6 / 5(1)(b) |
| PII minimisation | Redact | personal data, out of scope, legit purpose | GDPR 5(1)(c) / HIPAA |
| Compensation | Redact | comp data to non-HR, non-executive | ISO 27001 A.5.12 |
| Financial MNPI | Escalate | unreleased financials, social/out-of-scope | SOX §404 |
| Cross-department boundary | Redact | restricted team/role data across departments | NIST AC-6 / ISO 27001 |
| Secret four-eyes | Escalate | a secret-tier share/redact (maker ≠ checker) | SoD / ISO 27001 A.5.3 |
| Reviewer self-review | Escalate | the compliance authority sharing its own data | NIST AC-5 |

Every review is a `policy_review` trace span (deterministic, attributed to the Security head, the
compliance authority). A tighten re-stamps the decision `rule_id="POLICY/<rule>"`. Metered:
`policy_reviews`, `policy_overrides` (tightened a real owner decision), `policy_pregates`
(decided outright, owner skipped) — the UI's "Compliance" tile sums overrides + pre-gates.

---

## 9. Human-in-the-loop (HITL)

When a decision **ESCALATEs**, the owning agent parks its Task at `input-required` and drops a
request on the single global **HITL queue** (`atlas/hitl`). One operator (the control tower)
approves or denies; the orchestrator is suspended on an `asyncio.Future` the queue resolves — a
faithful A2A `input-required → resume`.

- The operator approves (optionally as **redact**) or denies via the UI, backed by
  `POST /api/hitl/{id}/approve` / `/deny`.
- `ATLAS_HITL_TIMEOUT_SECONDS` (default `0` = operator decides, no auto-timeout). A positive
  value auto-denies on timeout.
- **Cross-org sharing is gated here too** (see §14): every would-cross share parks for operator
  approval before any information leaves the building.

---

## 10. The cron simulator

`atlas/cron` makes the company *autonomous* — agents launch their own goals (driving the exact
same pipeline from seeded agent-initiated Tasks). Two modes (`ATLAS_CRON_LOOP`):

- **Burst** (default) — a single ~15-second window (`ATLAS_CRON_BURST_SECONDS`) firing a handful
  of goals, then **auto-stops** (the spec's "cron job, on for 15 seconds").
- **Continuous** (`ATLAS_CRON_LOOP=true`) — one goal every `ATLAS_CRON_GOAL_SECONDS` (~30s) until
  toggled off.

Either way goals are **balanced across all departments** (round-robin, so it isn't
Engineering-heavy), and load-shed by `ATLAS_CRON_MAX_INFLIGHT`. Toggle from the UI or
`POST /api/cron`.

---

## 11. Metrics

`atlas/metrics` computes communication-efficiency numbers **at the Router** — the answer to the
project's real question, *how efficiently did the agents coordinate?*

Per-context and global: **hops** to resolve, **messages** exchanged, items
**shared / redacted / denied**, **redundant contacts avoided** (a requester already holds the
data at sufficient fidelity → contact skipped), **HITL escalations**, **distinct agents
contacted**, and the policy counters (`policy_reviews` / `policy_overrides` / `policy_pregates`).
`GET /api/metrics` returns the snapshot; the UI's metrics strip renders it live.

---

## 12. The LLM boundary — Mistral on Bedrock

`atlas/llm`'s `BedrockProvider` is the **only** provider and drives **both** the user-prompt and
cron paths: it generates every agent message, re-ranks routing, and makes the owner's
need-to-know share decision via the Bedrock **Converse API** (boto3, run in a worker thread).

- Two configurable Mistral model ids (`ATLAS_BEDROCK_REASONING_MODEL` /
  `ATLAS_BEDROCK_PHRASING_MODEL`, default `mistral.mistral-large-2402-v1:0`).
- **Credentials are required** — a Bedrock API key (`AWS_BEARER_TOKEN_BEDROCK`) or classic
  access key/secret, plus a region; without them the app raises at startup.
- **No templates** — every message is authored by real Mistral or omitted. Secret payloads are
  appended verbatim so the model can't drop them.
- **Rate-limit safety** — a per-model **token bucket** agents *wait on* (paced to
  `ATLAS_BEDROCK_RPM`), a concurrency limit, SDK retries off, and a self-healing cooldown on
  throttling. The provider surfaces **`throttled`** / **`errored`** via the `llm.status` event so
  the UI shows when conversations are degraded.

---

## 13. Persistence + the authenticated network

Off by default → fully in-memory. Set **`ATLAS_DATABASE_URL`** to switch on two layers:

- **`atlas/db`** — async SQLAlchemy (asyncpg/Postgres in prod, aiosqlite in tests), portable
  JSON columns, `metadata.create_all` (no Alembic). The org is mirrored on first boot
  (`seed_org`, idempotent). **Write-through persistence** at the point of record (`DbWriter`):
  the Router persists tasks + messages, the HITL queue the approvals, the orchestrator the
  share-decisions, the push service its configs — a non-blocking `record()` onto an ordered
  queue drained by one async worker. This is what lets the **conversation timeline + history
  survive a refresh/restart** (`GET /api/history`, `POST /api/history/clear`).
- **`atlas/network`** — agents **join the network** by proving an **Ed25519** key (challenge →
  signature → verify) and receive a scoped, expiring **JWT** backed by a revocable DB session;
  thereafter they communicate without re-authenticating, while the Policy Engine still
  authorises every message. Agent ids are seed-deterministic `SEP-<16 digits>`.

**Membership gating** (DB on): the orchestrator routes/groups/sources only among joined members,
and the Router `send_message` is the backstop (the operator edge is exempt). **Consequence**:
with the DB on, **the network starts empty → prompts are rejected and cron is idle until agents
join** (UI: **Network → Join all**). This is by design (selective membership). To demo the old
always-live behaviour, leave `ATLAS_DATABASE_URL` unset.

---

## 14. Multi-org federation

A single org is a **private network** of 100 agents talking freely over one in-process Router. A
**federation** (`atlas/federation`, `ATLAS_ORG_COUNT > 1`) runs **N such sealed orgs** at once
and lets them talk to each other **publicly**, the way two real companies do.

### The rules

- **Inside an org** — unchanged: full need-to-know sharing, the two-layer owner-LLM + Policy
  Engine decision. Detailed, unrestricted-about-the-org.
- **Between orgs** — only **PUBLIC** information may cross; internal / confidential / restricted /
  secret stays in the building. Enforced by the Policy Engine's **`CROSS-ORG-RESTRICT`** rule
  (hard DENY for anything above PUBLIC). *"Only the necessary things leave."*

### Structural integrity (not a flag you must remember)

- **`build_federation`** (`atlas/runtime.py`) builds the cross-cutting singletons **once**
  (broker, llm, hitl, trace, push, metrics, db/dbwriter) and **N sealed orgs** off them — each
  with its **own** registry / router / network / orchestrator / cron. `org_count == 1` is
  byte-identical to the single-org demo, so every existing test stays green. Each org is seeded
  `seed + index` ⇒ disjoint `SEP-<16 digits>` ids.
- An org's Router only knows **its own** registry, so an org's agents **cannot reach a peer**
  except through the **`FederationGateway`** — the single door, exactly as the Router is the one
  door inside an org. The gateway is the **sole origin of `cross_org=True`**.
- A cross-org request is decided by the **target** org's own machinery (its owner agent + its
  Policy Engine, `cross_org=True`): their data, their floor. Discovery across the boundary sees
  peers' **PUBLIC** cards only (org-profile stripped) — never their hierarchy/clearances.

### Each org is a different company

A federation's orgs are not clones. A per-org **`CompanyProfile`** (`atlas/org/company.py`) gives
each org its own **projects**, its own **people** (a rotated name pool ⇒ fully disjoint names, not
just ids), org-scoped emails/cards, and **secrets reskinned** to its own projects. The principle is
**vary identity & content, keep capability & structure**:

- **Varies per org**: project names, secret titles/bodies, people, emails.
- **Stays canonical**: departments, headcounts, role archetypes, and the **skill catalogs** — this
  is load-bearing, not a shortcut: routing scores on skills, so identical capability is what keeps
  the membership-gated cross-org fallback well-defined (a prompt fits the same *kind* of agent in
  every org; only which teams have *joined* differs).
- **Never touched**: `topic_tags` + `sensitivity` on items — so the deterministic Policy Engine
  classifies and tiers every org's items identically (cross-org public/non-public behaviour is
  preserved). `atlas` (index 0) is the identity profile, so the single-org demo is byte-identical.

So departments look the same across orgs (every software company has Engineering / Product / QA /
…), but the **projects, the secrets, and the people are genuinely different**. (The seeded secret
*shapes* — ~18 items spanning every tier — are reskinned per org, not authored bespoke; fully
distinct secret sets per company would be a larger content effort.)

### Cross-org runs through the FULL pipeline

Cross-org is a first-class citizen of every pipeline stage (`_run_cross_org_request` /
`_cross_org_source`):

- **Routing** — *auto-fallback*: under membership gating, when a prompt finds **no local joined
  member** that fits, the orchestrator routes it to the **single best peer** org whose joined
  members can (`FederationGateway.route_to_peer`, one peer — never a fan-out, to respect the
  shared rate bucket).
- **Conversation / threads** — the local requester (a joined member) opens a **thread** to the
  peer owner; messages go through the **Router** via a transport-only `external_ids` exemption (a
  gateway-vouched peer agent is carried, but the *decision* still happens in the gateway).
- **History** — because messages flow through the Router's write-through, cross-org
  conversations **thread + persist** and replay after a refresh.
- **Policy** — the peer's Policy Engine decides with `cross_org=True`; non-public is hard-denied.
- **HITL** — every **would-cross share is gated by operator approval** (the same shared HITL
  queue + approve/deny endpoints) before any information leaves the building.
- **Network** — the requester is the best local **joined** member; the peer is sourced from its
  **joined** pool.

### Triggers (both live + tested)

- **Auto-fallback** — the organic live trigger above (requires the DB, because it is
  membership-gated; in pure in-memory mode every prompt always has a local owner).
- **Operator-directed** — `POST /api/federation/request` opens a real Task and runs the same
  full pipeline. `POST /api/federation/exchange` remains a **synchronous policy probe** (returns
  the boundary decision immediately, no Task/HITL) for a quick "would this cross?" check.

### API & UI

`GET /api/orgs` lists the orgs; `GET /api/org?org_id=` returns one org's structure;
`GET /api/federation/items?org_id=` lists a target org's items (operator god-view). Events carry
an optional **`org_id`** (null in N=1 ⇒ the wire is unchanged) and a **`federation.exchange`**
event names both orgs. Every org-scoped read/action takes `?org_id=` (resolved in `_rt`). When N>1
the UI shows an **org-switcher dropdown** that scopes Teams/Network/Roster/Projects + the top
chat-bar to the chosen org, and the **Comms** view renders all orgs as one hierarchical graph — so
cross-org happens organically by dispatching from the chat-bar.

### Scope

The federation works **in-memory AND with the DB**. The only seed table whose key isn't
seed-disjoint — the template-derived `context_items.item_id` — is namespaced by org **in the
value** (peers get an `<org_id>:` prefix; the primary `atlas` keeps the raw id) so the schema
stays byte-identical and an existing persisted database needs **no migration**. Each org gets its
own network signing key. Known limitation: the org switcher swaps only the *graph* —
conversations/metrics/HITL stay **pooled** across orgs on the shared broker.

---

## 15. The frontend — mission control

`web/` is a React 18 + Vite + TypeScript app (force-graph, Zustand state, SSE client). It
develops against the real backend (Vite proxy → :8000), no mock emitter. The center stage has
tabs:

| Tab | What it shows |
|---|---|
| **Conversation** | The live agent-to-agent timeline. Your prompt appears instantly as a right-aligned "Operator → recipient" bubble (optimistic dispatch), then the routed task + every message, share/redact/deny, and group session. A completed conversation stays visible until you dispatch a new prompt or refresh. |
| **History** | Completed goals, replayed from the persisted record (survives refresh/restart when the DB is on). |
| **Network** | Authenticated-network membership — join/disconnect agents (one-click or **Join all**), see who's live. Only meaningful with the DB on. |
| **Comms** | The communication topology — a live force-graph of who is talking to whom, with intent and outcome on the links. In a federation it shows **all orgs at once** as one hierarchical graph (a Federation root → each org's CEO → its department rings, clusters labelled by org name). |
| **Roster** | The 100 agent cards — identity, role, skills, what each owns. |
| **Projects** | Cross-team project workspaces — members, scoped secrets, live coordination. |

In a **federation** (N>1), an **org-switcher dropdown** appears top-right of the stage. Picking an
org scopes the left Teams panel, Network, Roster, Projects, **and the top chat-bar dispatch** to that
sealed org (every org-scoped call carries `?org_id=`). Conversations, metrics, and HITL stay pooled
across orgs — so to trigger a cross-org exchange you simply dispatch, from the chat-bar, a prompt the
selected org can't handle locally (under membership gating it auto-falls-back to a peer; see §14).

Around the stage: a **top bar** (connection, LLM status, cron toggle, dispatch box), a **teams
panel**, a **right rail** (feed + drawers: push configs, context metrics, A2A card panel, agent
context stats), a **metrics strip**, and a dismissible **out-of-scope gate banner**. HITL
requests surface for operator approval wherever they're pending.

---

## 16. Complete API reference

All under `/api` unless noted. Edge auth (opt-in via `ATLAS_API_KEY`) gates `/api/*` and `/v1/*`
(except `/api/healthz`); the `/.well-known/*` discovery endpoints are always public.

### Read — organisation & directory

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/healthz` | Liveness + agent count + LLM name + seed + cron status. |
| GET | `/api/org` `?org_id=` | The org structure the graph renders (a specific federation org with `org_id`). |
| GET | `/api/orgs` | The organisations in this deployment (1, or N in a federation). |
| GET | `/api/users` | The human users (1:1 with agents). |
| GET | `/api/agents/{id}/card` | An agent's view-model card. |
| GET | `/api/agents/{id}/card/extended` | A2A `GetExtendedAgentCard` (org-profile; auth-gated). |
| GET | `/api/projects` · `/api/projects/{id}` | Project summaries / one project as a unit. |
| GET | `/api/threads/{context_id}` | The threads in a conversation. |
| GET | `/api/snapshot` | Export the full in-memory snapshot. |

### Read — runtime

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/metrics` | The communication-efficiency snapshot. |
| GET | `/api/hitl` | Pending HITL requests + resolved count. |
| GET | `/api/tasks` | A2A **ListTasks** (`contextId`/`status`/`includeArtifacts`/`cursor`/`limit`). |
| GET | `/api/tasks/{id}` | A2A **GetTask** (`historyLength`). |
| GET | `/api/tasks/{id}/subscribe` | A2A per-task SSE stream (`StreamResponse` frames). |
| GET | `/api/history` `?limit=` | Replay persisted conversations (DB on). |
| GET | `/api/events` | The global SSE stream (see §17). |

### Actions

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/prompt` | Dispatch a prompt (`prompt`, optional `human`/`user_id`/`reference_task_ids`). |
| POST | `/api/cron` | Toggle the cron simulator (`{on: bool}`). |
| POST | `/api/tasks/{id}/cancel` | A2A `tasks/cancel`. |
| POST | `/api/hitl/{id}/approve` `?outcome=share\|redact` · `/deny` | Resolve a HITL request. |
| POST | `/api/history/clear` | Wipe the conversation/history record (org + membership untouched). |
| POST | `/api/reset` | Rebuild the runtime/federation. |

### Push notifications (A2A `pushNotificationConfig`)

`POST` / `GET` / `GET {config_id}` / `DELETE {config_id}` under
`/api/tasks/{id}/push-notification-configs` — register a webhook for a task and manage its
configs; Atlas POSTs a status update to it on every state change.

### Authenticated network (DB on)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/network` | Current members. |
| GET | `/api/network/challenge` `?agent_id=` | Get an auth challenge nonce. |
| POST | `/api/network/authenticate` | Submit a signed challenge → JWT. |
| POST | `/api/network/agents/{id}/join` | Operator one-click join (server-side challenge/response). |
| POST | `/api/network/agents/{id}/disconnect` | Revoke a session. |
| POST | `/api/network/verify` | Verify a token's claims. |

### Federation (N>1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/federation/items` `?org_id=` | A target org's items (operator god-view, to pick from). |
| POST | `/api/federation/exchange` | **Synchronous policy probe** — would this item cross? Returns the decision (no Task/HITL). |
| POST | `/api/federation/request` | **Full pipeline** — open a Task and run the cross-org scenario (threads + History + HITL gate). |

### `/v1` — the spec-shaped A2A HTTP+JSON binding

`GET /v1/card` · `GET /v1/agents/{id}/card` · `POST /v1/message:send` (version + extension
negotiation) · `GET /v1/tasks` · `GET /v1/tasks/{id}` · `POST /v1/tasks/{id}:cancel` ·
`GET /v1/tasks/{id}:subscribe`. Named A2A errors map to HTTP status with a spec-shaped body.

### Discovery (always public)

`GET /.well-known/agent-card.json` · `GET /.well-known/agents.json` ·
`GET /.well-known/agents/{id}/agent-card.json`.

---

## 17. SSE events reference

`GET /api/events` is the global stream; `atlas/events/schema.py` is the canonical contract.
Every frame is `{event, id, ts, context_id?, org_id?, data}`.

| Event | Meaning |
|---|---|
| `agent.status` | An agent's status changed (idle / thinking / speaking / waiting_hitl …). |
| `prompt.accepted` | A prompt was admitted and routed (or a cron goal launched). |
| `gate.rejected` | An out-of-scope prompt was refused. |
| `discovery.matched` | Level-1 routing or Level-2 sourcing matched candidates. |
| `task.state` | A Task changed state. |
| `thread.created` · `group.formed` | A 1:1 thread or a group session was opened. |
| `message.sent` | An agent message (with intent, thread/group, optional reasoning). |
| `context.shared` · `.redacted` · `.denied` · `.reused` | A need-to-know outcome (`reused` = redundant contact avoided). |
| `hitl.requested` · `hitl.resolved` | An escalation parked / an operator decision. |
| `metrics.updated` | New communication-efficiency numbers. |
| `cron.tick` · `cron.state` | Cron countdown / start-stop. |
| `llm.status` | Bedrock throttled / errored (degraded conversations). |
| `trace.span` | One observable agent operation (an LLM call or a policy step). |
| `push.delivered` | An outbound A2A webhook delivery attempt. |
| `network.joined` · `network.left` | An agent authenticated / a session ended. |
| `federation.exchange` | A request crossed the boundary between two orgs (names both). |

---

## 18. Configuration reference

All via environment variables (prefixed `ATLAS_`) and an optional `.env`. See
[`../.env.example`](../.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `AWS_BEARER_TOKEN_BEDROCK` **or** `AWS_ACCESS_KEY_ID`+`AWS_SECRET_ACCESS_KEY` | — | **Required** Bedrock credentials. |
| `AWS_REGION` | `us-east-1` | Bedrock region. |
| `ATLAS_BEDROCK_REASONING_MODEL` / `ATLAS_BEDROCK_PHRASING_MODEL` | `mistral.mistral-large-2402-v1:0` | Mistral model ids / inference-profile ARNs. |
| `ATLAS_BEDROCK_RPM` / `_BURST` / `_MAX_CONCURRENCY` | `22` / `5` / `2` | Rate-limit pacing. Set RPM to your real quota. |
| `ATLAS_SEED` | `42` | Determinism — drives the org, cron, phrasing. |
| `ATLAS_ORG_COUNT` | `1` | 1 = single-org demo; >1 = a federation of N sealed orgs. |
| `ATLAS_CRON_LOOP` | `false` | `false` = 15s burst; `true` = continuous. |
| `ATLAS_CRON_BURST_SECONDS` / `_GOAL_SECONDS` | `15` / `30` | Burst length / continuous cadence. |
| `ATLAS_CRON_MAX_INFLIGHT` | `2` | Max concurrent goal scenarios (load-shed). |
| `ATLAS_HITL_TIMEOUT_SECONDS` | `0` | `0` = operator decides; positive = auto-deny on timeout. |
| `ATLAS_DATABASE_URL` | unset | Unset = in-memory; set = Postgres persistence + the authenticated network. |
| `ATLAS_NETWORK_SESSION_TTL_SECONDS` | `43200` | Session/JWT lifetime (12h). |
| `ATLAS_API_KEY` | unset | Opt-in operator edge auth (401/403 on `/api/*` + `/v1/*`). |
| `ATLAS_HOST` / `ATLAS_PORT` | `0.0.0.0` / `8000` | Server bind. |

---

## 19. Testing

```bash
uv run pytest          # backend suite (127 tests)
cd web && npm run typecheck   # frontend contract typecheck
```

Coverage includes: org golden snapshot; orchestrator + HITL flow; owner-LLM share decision +
deterministic policy-engine rules; group need-to-know; LLM wiring + payload guard;
Bedrock-credential requirement; cron; API integration; push-notification webhook delivery;
edge-auth + security schemes; the `/v1` binding (negotiation + named errors); the
authenticated-network join/auth; persistence write-through; and the **federation** (the
cross-org boundary three ways, the gateway path, sealed-org isolation, the two-org lifespan boot,
DB + federation seeding/keys, the auto-fallback + operator-directed full pipeline, and the
cross-org **HITL gate** approve/deny + message persistence).

Tests inject a fake LLM double (`tests/conftest.py`, `available=True`, authors deterministic
text), so they run without a key — it is never used by the running app.

---

## 20. Repo layout

```
atlas/   a2a/ (protocol)  org/ (company + generator)  bus/ (router/discovery)
         policy/ (deterministic compliance engine)  conversation/ (orchestrator/threads/groups)
         hitl/  cron/  llm/  metrics/  events/ (SSE schema = the FE contract)
         push/ (A2A webhook delivery)  db/ (opt-in Postgres persistence + write-through)
         network/ (Ed25519 join-the-network auth + scoped JWT sessions)
         federation/ (multi-org gateway: N sealed orgs, public-only boundary)
         api/  store/  main.py  runtime.py  config.py
web/     React + Vite + TS mission-control UI (force-graph, Zustand, SSE)
tests/   pytest suite     Dockerfile · docker-compose.yml
docs/    DOCUMENTATION.md (this) · policy.md · a2a-*.md · engine.md
```

---

## 21. What you can do with Atlas — scenarios

- **Watch agents coordinate** — type a prompt ("plan the Q3 engineering roadmap") and watch it
  route, discover owners, ask with intent, and share / redact / deny on need-to-know, live in the
  Conversation + Comms views.
- **See need-to-know enforced** — ask for a secret you shouldn't have; watch the owner LLM's
  judgement, the Policy Engine tighten it, and the outcome (deny / safe summary / escalate).
- **Be the human in the loop** — when a sensitive share escalates, approve or deny it from the
  UI and watch the task resume.
- **Let the company run itself** — toggle the cron simulator and watch autonomous goals fire
  across all departments.
- **Measure communication** — read the metrics strip: hops, messages, shared/redacted/denied,
  redundant contacts avoided, escalations.
- **Drive a real A2A client** — discover via `/.well-known/`, send via the `/v1` binding,
  subscribe to a task's stream, register a push webhook.
- **Turn on persistence + the network** — set `ATLAS_DATABASE_URL`, have agents authenticate
  (Ed25519 → JWT) to join, and watch conversations survive a restart.
- **Run a federation** — set `ATLAS_ORG_COUNT > 1`, partially populate two orgs' membership, and
  watch a prompt that no local team can handle fall back across the boundary to a peer — where
  only **PUBLIC** information crosses, gated by your approval.

---

## 22. Glossary

- **A2A** — the Agent-to-Agent protocol Atlas faithfully implements in-process.
- **Agent Card** — an agent's public identity + capabilities (extended card adds the org
  profile, for authenticated callers).
- **Need-to-know** — the org layer on top of A2A: who may receive what, by sensitivity + scope.
- **Owner** — the agent that owns a requested `ContextItem` and decides about it.
- **Policy Engine** — the deterministic, tighten-only compliance floor (`atlas/policy`).
- **HITL** — human-in-the-loop: an operator approval step on escalation.
- **Router** — the single in-process chokepoint for all agent↔agent communication in an org.
- **Cron** — the simulator that makes agents launch their own goals autonomously.
- **Federation** — N sealed 100-agent orgs that communicate publicly through one gateway.
- **Cross-org boundary** — the rule that only PUBLIC information may cross between orgs.
- **SEP id** — a seed-deterministic agent id (`SEP-<16 digits>`), disjoint per org.

---

*Atlas — how agents communicate, like humans. Built on a faithful A2A core with a need-to-know
layer, a deterministic compliance engine, a real LLM, and an optional federation.*
