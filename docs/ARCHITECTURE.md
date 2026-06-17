# ATLAS Architecture — the moving parts

This doc is the map. After reading it you should be able to point at any process,
port, or event in a running mission and say what it is and who produced it.

There are really just two kinds of process:

```
        browser (you)
            │  HTTP + SSE
            ▼
   ┌───────────────────────┐        every agent POSTs telemetry here
   │   GATEWAY  :8000      │◀───────────────────────────────────────┐
   │  UI · telemetry · HR  │                                         │
   │  · run driver         │                                         │
   └───────────┬───────────┘                                         │
               │ provisions (HR)                                     │
   ┌───────────┴───────────────────────────────────────┐            │
   ▼                       ▼                       ▼     │ A2A        │
┌────────┐            ┌────────┐            ┌────────┐   │ (JSON-RPC) │
│ E1 :9001│  ◀──A2A──▶ │ E2 :9002│  ◀──A2A──▶ │ E3 :9003│ ──telemetry─┘
│  CEO    │            │ report  │            │ report  │
└────────┘            └────────┘            └────────┘
   employee servers (ports 9001, 9002, 9003, …)
```

- **One gateway** on port **8000**.
- **Many employee servers** on ports **9001, 9002, 9003, …** (`EMPLOYEE_PORT_BASE
  = 9001` in `config.py`). Every employee runs the *same* code (`org/employee.py`).

The golden rule: **the gateway observes and provisions; it never does the agents'
thinking.** Decomposing, hiring decisions, and the actual work all happen
agent-to-agent over A2A.

---

## The gateway (`gateway/app.py`, port 8000)

One server, four jobs:

1. **Serves the UI.** The single-page app in `web/` is mounted at `/` (so
   `/api/*` and `/hr/*` win first, static files last).
2. **HR / provisioning.** The only bit of central plumbing. It hands free
   employees to whoever asks:
   - `POST /hr/allocate` — give me one free employee.
   - `POST /hr/candidates` — reserve up to *k* free employees for an auction
     (so two managers never interview the same candidate).
   - `POST /hr/release` — I'm done with this employee; free it.
3. **Telemetry aggregator + SSE broadcaster.**
   - `POST /api/ingest` — every agent posts its events here.
   - `GET /api/stream?run=…` — the browser subscribes here; the gateway replays
     the backlog then streams new events live.
4. **Run driver.** Kicks off a mission:
   - `POST /api/run` (alias `POST /api/plan`) — run one mission with one topology.
   - `POST /api/compare` — run the same mission under three topologies.

Per-run state lives in a `RunState` object: its event log, the live `OrgChart`,
the `Metrics`, the `ledgers`, the SSE `subscribers`, and the `contextId` (which
is just the `run_id` — **one mission = one conversation thread**).

---

## The employee servers (`org/employee.py`, ports 9001+)

Every agent — **the CEO included** — is the *same* generic employee. It boots as
an anonymous **"Generalist"** and only becomes a "VP Engineering" (or whatever)
by being **onboarded** over the wire. Its `logic()` dispatches on the incoming
message's **performative**:

- `propose` + an offer → **role conferral**: write the identity, reply
  `accept-proposal`.
- `cfp` → **bid** in a Contract-Net auction (reply `propose` with a score).
- `query-ref` + `consult` → **peer reply** (mesh): a short `inform`, no fan-out.
- `request` → **do the work**: either solo, or — if it's a manager — hire a team
  and synthesise.

Because they are all identical, "hiring" is just handing a role to a free one.

---

## Two runtimes behind one interface

"Hiring" needs a physical agent to hand a role to. *How* that agent comes to exist
is hidden behind the `Runtime` interface (`org/runtime.py`), so the communication
layer never has to care. There are two implementations:

| Runtime          | How an agent exists                          | When                              |
| ---------------- | -------------------------------------------- | --------------------------------- |
| `PooledRuntime`  | Pre-warmed employee servers, each in its own background **thread** on its own port. | **Default.** Fast, robust.        |
| `DynamicRuntime` | A real OS **process** per hire (`python -m org.employee`), spawned on demand and recycled. | `ATLAS_RUNTIME=dynamic`.          |

```python
# org/runtime.py
def make_runtime() -> Runtime:
    if config.RUNTIME == "dynamic":
        from org.dynamic_runtime import DynamicRuntime
        return DynamicRuntime()
    return PooledRuntime()
```

Both speak **real A2A on real TCP ports** — only the provisioning differs.
`PooledRuntime` pre-warms `POOL_SIZE` (default 8) servers up front.
`DynamicRuntime` pre-warms a few, then spawns the rest on demand up to the
headcount cap (and keeps spent processes warm rather than killing them). Because a
dynamic spawn can block, the gateway offloads provisioning with
`asyncio.to_thread(...)` so the event loop keeps serving telemetry while a hire
spins up.

---

## The CEO is just employee #1

There is exactly **one** privileged step in the whole system. The **Board** — the
gateway, acting on your behalf — onboards employee #1 as the **CEO** and hands it
the mission (`org/ceo.py`):

```
Board ──propose (offer: role=CEO, goal=mission)──▶ E1     # "you are the CEO"
E1    ──accept-proposal──▶ Board                          # "I accept"
Board ──request (mission, topology)──▶ E1                 # "go"
E1    ── … decompose · hire · delegate · synthesise … ──▶ result
```

After that handover, **everything is agents talking to agents.** The CEO is at
`delegationDepth` 0; everyone it hires is depth 1; their reports are depth 2; and
so on.

---

## The telemetry backbone

The org is decentralised — messages fly directly between employee processes. To
make all of it observable in *one* place, every agent narrates what it does
(`org/telemetry.py`, the `Reporter` class):

```
agent ──POST /api/ingest {type, runId, from, …}──▶ gateway
                                                      │ stamps seq + ts
                                                      │ persists to SQLite
                                                      │ folds into OrgChart / Metrics / ledgers
                                                      └─SSE /api/stream──▶ browser
```

Event types you'll see: `message` (a performative act on the wire), `status`,
`llm` (token usage), `hire`, `onboard`, `ledger`, `meeting`, `cap`, and `run`.
Convention: the **sender** of a message emits a `message` event for its outbound
act, and the **receiver** emits its reply as another `message` event — so one
round-trip shows up as two events, exactly what you want on the wire.

Three projections are derived from this single event stream:

- **`OrgChart`** (`org/registry.py`) — the who-works-for-whom tree, built from
  `hire` / `onboard` / `status` events.
- **`Metrics`** (`org/metrics.py`) — `messages`, `tokens`, `maxDepth`,
  `headcount`, a per-performative breakdown, and `elapsedMs`.
- **Ledgers** (`org/ledger.py`) — the Task ledger (mission + facts + plan) and the
  Progress ledger (a row per delegated step).

Because they are pure projections of the event log, the whole run can be rebuilt
by replaying events (which is how `/api/run-state` restores a finished run from
SQLite, via `memory/store.py`).

---

## The caps — what's enforced, and where

ATLAS lets an org *emerge*, so it needs guardrails to stay bounded. Be precise
about which are **hard caps** (a code path actually stops you) versus **metered
budgets** (measured and shown, but not enforced):

| Cap (`config.py`)         | Default  | Enforced? | Where                                                                 |
| ------------------------- | -------- | --------- | --------------------------------------------------------------------- |
| `MAX_HEADCOUNT`           | 12       | **Hard**  | `runtime.py` `allocate` / `reserve_candidates` (and `dynamic_runtime.py`) refuse to hand out more per run. |
| `MAX_DELEGATION_DEPTH`    | 3        | **Hard**  | `should_manage` and `run_as_manager` in `org/delegation.py`; recursion is gated in `org/cognition.py`. |
| `MAX_REPORTS_PER_MANAGER` | 4        | **Hard**  | `org/delegation.py` slices the plan's roles to this many.             |
| `TOKEN_BUDGET`            | 150 000  | **Metered, not enforced** | Tracked in `Metrics.tokens` and shown in the launch banner, `/api/status`, and the UI badge. No path halts a run on overspend — treat it as an observability budget. |
| `MEETING_MAX_PARTICIPANTS`| 5        | **Not wired** | The constant exists but no code reads it. Meeting size is bounded in practice by `MAX_REPORTS_PER_MANAGER` (a meeting is the manager's reports). |

> Honesty matters here: `config.py` calls the caps "enforced," but for
> `TOKEN_BUDGET` that's aspirational — it's metered and surfaced, not a hard stop.
> If you need a true token guard, that's a known gap to add (e.g. in the run
> driver or the `Reporter.llm` path).

---

## One mission run, end to end (ASCII)

Here is a hierarchical run, top to bottom, with who emits what:

```
you ─POST /api/run {mission, topology}─▶ gateway
                                          │ create RunState, contextId = runId
                                          │ emit run:started
                                          ▼
gateway (Board) ─allocate──────────────▶ runtime → E1
gateway (Board) ─propose(offer CEO)────▶ E1            E1 ─accept-proposal─▶ Board
gateway (Board) ─request(mission)──────▶ E1
                                          │
                          ┌───────────────┴── E1 is a manager (depth 0) ──┐
                          │  decompose → roles + sub-tasks (Task ledger)   │
                          │  for each role: Contract-Net auction           │
                          │    cfp ─▶ candidates                           │
                          │    propose ◀─ each candidate (a bid score)     │
                          │    accept-proposal ─▶ winner ; refuse ─▶ rest  │
                          │    onboard winner (propose offer → accept)     │
                          └───────────────┬──────────────────────────────-┘
                                          │ coordinate (topology = hierarchical)
                          E1 ─request(sub-task)─▶ E2, E3, E4   (in parallel)
                          E2,E3,E4 ─inform(result)─▶ E1
                                          │ E1: synthesize → final result
                                          ▼
                                   gateway emit run:done {final, metrics}
                                          │ release all agents on this run
                                          ▼
                          browser shows org chart, protocol log, ledgers, result
```

Every arrow above is also a telemetry event streaming to your browser in real
time over `/api/stream`. Swap the topology and only the **coordinate** step
changes — the hiring above it is identical (that's what makes the comparison
mode fair; see `COMMUNICATION_PATTERNS.md`).
