# Communication Patterns — how ATLAS agents talk

This is the heart of the project. ATLAS is really a study of **agent-to-agent
communication**: every message is legible (you can tell a request from an answer
from a bid), and the *shape* of the conversation can be swapped to compare
coordination styles. This doc covers the vocabulary (performatives + BDI), the
three topologies, Contract-Net hiring, recursion, and the comparison mode.

---

## 1. Performatives — the *speech act* of every message

A **performative** (from FIPA ACL) tells the receiver *what kind* of message this
is, independent of its text. It is the backbone of legible agent communication.
ATLAS uses a curated subset (`org/envelope.py`, class `Performative`):

| Performative      | One-line meaning              | Where it's used                                  |
| ----------------- | ----------------------------- | ------------------------------------------------ |
| `request`         | Please perform an action.     | Board → CEO; manager → report (the sub-task).    |
| `inform`          | Here is a result / a fact.    | A worker returning its deliverable; consult reply.|
| `propose`         | I offer to do X.              | Onboarding offer; a Contract-Net **bid**.        |
| `cfp`             | Call-for-proposal: who can do X? | A manager opening a hiring auction.           |
| `accept-proposal` | I take your proposal.         | Awarding the auction winner; accepting a role.   |
| `refuse`          | I decline.                    | Telling auction losers "not this time."          |
| `agree`           | I commit to your request.     | Reserved in the vocabulary.                      |
| `query-ref`       | What is X?                    | A **mesh** peer consult.                          |
| `failure`         | The action failed.            | Reserved for error signalling.                   |

Every message carries exactly one performative inside the org envelope, so the
A2A protocol log reads like a transcript of *acts*, not just text.

---

## 2. BDI — *who* is speaking and *why*

Alongside the performative, each message carries a small **Belief–Desire–Intention**
context (`make_envelope` in `org/envelope.py`):

- **`role`** — who is speaking (`"CEO"`, `"Design Lead"`, `"Board"`).
- **`motivation`** — the deeper goal (often the mission, or the role's goal).
- **`intent`** — what *this* message is trying to do (`"execute the mission"`,
  `"bid 73 for Design Lead"`).
- **`beliefs`** — optional facts the sender is acting on.
- **`delegationDepth`** — how deep in the org tree the sender sits.

So a single message says: *who* I am (role), *why* I exist (motivation), *what I
want right now* (intent), and *what kind of act this is* (performative). That is
what makes the conversation readable by a human watching the log.

The envelope lives under one namespaced key in `message.metadata` (see
`A2A_CORE_vs_ORG_EXTENSIONS.md`):

```json
{ "https://atlas.org/ext/org/v1": {
    "performative": "request", "role": "CEO", "intent": "deliver the architecture",
    "motivation": "privacy-first doorbell", "delegationDepth": 1 } }
```

---

## 3. Contract-Net hiring — roles decided by negotiation

A manager doesn't grab the first free employee. It runs a real **FIPA
Contract-Net auction** (`org/contract_net.py`). The role is decided by a
negotiation *on the wire*, not by a central scheduler:

```
manager ──cfp──────────────▶ candidate A   "who can be the Design Lead?"
manager ──cfp──────────────▶ candidate B
        ◀──propose (score 73)── candidate A   a bid (a confidence score)
        ◀──propose (score 41)── candidate B
manager ──accept-proposal──▶ candidate A     "you're hired"  (best bid wins)
manager ──refuse───────────▶ candidate B     "thanks, not this time" (released)
```

Step by step:

1. The manager asks HR to **reserve** a few candidates
   (`POST /hr/candidates`, `k = CNP_CANDIDATES`, default 2). HR reserves them so
   two managers never interview the same person — but the *choice* is the
   manager's.
2. The manager sends each candidate a `cfp`. Each replies `propose` with a
   `bid_score` — a deterministic 0–99 "fit" (`sha1(agentId:role) % 100`). It's
   stable per (agent, role) so auctions reproduce.
3. The highest bid wins `accept-proposal`; the losers get `refuse` and are
   **released** back to the pool (`POST /hr/release`).
4. The manager records the hire itself (decentralised — *the manager* hired
   them). Then it **onboards** the winner: a `propose` carrying the role offer
   → the winner writes its identity and replies `accept-proposal`. You literally
   watch an agent receive its identity over the wire.

---

## 4. The three topologies

Here's the elegant part. *Who* gets hired (by the auction above) is **identical**
across all three topologies — only **how** the team coordinates changes
(`org/topology.py`, function `coordinate`). That is exactly what the comparison
mode measures.

### Hierarchical — 1:1 delegation, in parallel

The manager delegates to each report 1:1 with a `request`; reports work in
isolation and reply `inform`. Fast, minimal chatter.

```
            CEO
   ┌─────────┼─────────┐        request (sub-task) ─▶ each report
   ▼         ▼         ▼        inform (result)     ◀─ each report
 Report    Report    Report     (all in parallel)
```

### Mesh — reports also consult peers directly

Same delegation tree, but each report may also reach **another report directly**
(peer-to-peer A2A, bypassing the manager): a `query-ref` → the peer's `inform`.
More chatter, more resilience.

```
            CEO
   ┌─────────┼─────────┐
   ▼         ▼         ▼
 Report ◀─▶ Report ◀─▶ Report     query-ref / inform between peers
   └──────── ▲ ────────┘          (in addition to manager delegation)
```

The manager passes each worker a `peers` list (everyone *except* itself); the
worker consults `peers[0]` before doing its own work (`Employee._consult_peer`).

### Group — a meeting on one shared `contextId`

A2A is natively 1:1, so a multi-party meeting is an **extension**
(`org/meeting.py`). The manager convenes a meeting room — **one shared
`contextId`** (`meet-{runId}-{managerId}`) — and gives each participant the floor
in turn (**round-robin speaker selection**). Each speaker sees the transcript so
far, so a genuine group conversation emerges from 1:1 A2A calls.

```
      ┌──────────────── meeting room (one shared contextId) ───────────────┐
      │  manager: floor ─▶ Report A   (A speaks; sees nothing prior)        │
      │  manager: floor ─▶ Report B   (B speaks; sees A's turn)             │
      │  manager: floor ─▶ Report C   (C speaks; sees A + B)                │
      └────────────────────────────────────────────────────────────────────┘
                          turns are sequential, not parallel
```

The manager emits `meeting` events (`phase: "open"` / `"close"`) so the UI can
group all the turns into one room.

---

## 5. Recursion — a report can become a sub-orchestrator

Delegation is a clean two-stage routine (`org/delegation.py`): **(1)** decompose
+ hire every report, then **(2)** coordinate. A report onboarded with
`manage = True` (and with depth budget left) runs that **same** routine on its
sub-task — turning an "expert" agent into a sub-manager:

```
CEO (depth 0)
 └─ Engineering Lead (depth 1, manage=True)     ← becomes a sub-orchestrator
     ├─ Engineering Specialist A (depth 2)
     └─ Engineering Specialist B (depth 2)
```

Recursion is **depth-capped**: `should_manage` requires `depth <
MAX_DELEGATION_DEPTH` (default 3), and the `manage` flag is only granted when
there's room below. In the deterministic offline planner, the Engineering Lead is
the role that gets a sub-team — so a default run reaches depth 2.

---

## 6. Comparison mode — and why it forces the mock

The comparison mode (`POST /api/compare`, or the "Compare all three" option) runs
the **same mission** under hierarchical, mesh, and group. To make the metric
deltas meaningful it **forces the deterministic mock LLM** for the duration:

```python
# gateway/app.py  → drive_all()
set_force_mock(True)        # deterministic => apples-to-apples
try:
    for rs in created:     # sequential: the three runs share the employee pool
        await drive(rs)
finally:
    set_force_mock(False)
```

**Why force the mock?** Because the org's *reasoning* (decompose / do_work /
synthesize) must be identical run-to-run. If a live LLM invented a different team
each time, you couldn't tell whether a metric changed because of the *topology*
or because the agents simply *thought* something different. With the mock, **org
composition is held constant**, so any delta is attributable to the communication
pattern alone. The smoke test `scripts/smoke_topologies.py` asserts exactly this:
identical roles + headcount across topologies, but different message counts and
performatives.

### The measured deltas (an illustration)

On the default doorbell mission with the mock, the three topologies compose the
same team but talk very differently (approximate figures):

| Topology     | Messages | Signature                                         | Speed         |
| ------------ | -------- | ------------------------------------------------- | ------------- |
| Hierarchical | ~54      | No peer consults (`query-ref` count = 0).         | **Fastest**   |
| Mesh         | ~62      | Extra `query-ref`/`inform` peer consults → more msgs. | Mid           |
| Group        | ~54      | Same message count, but extra meeting contexts.   | **Slowest** (turns are sequential) |

The takeaways the comparison is designed to teach:

- **Mesh trades chatter for resilience** — more messages (peer consults), same
  team.
- **Group costs latency, not messages** — the meeting is sequential (each speaker
  waits for the prior), so it's the slowest even when the message count matches
  hierarchical. It also opens extra `contextId`s (the meeting rooms).
- **Hierarchical is the lean baseline** — fewest interactions, fully parallel.

> These numbers come from the deterministic mock, so they reproduce. Want the
> exact figures on your machine? Run `python scripts/smoke_topologies.py` — it
> prints `msgs / head / depth / consults / meetings / contexts` per topology.
