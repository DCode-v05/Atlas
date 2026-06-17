# A2A patterns in ATLAS — explained simply

This doc explains, in plain language, **what was built**, **how it uses the A2A
protocol** (spec: <https://a2a-protocol.org/latest/specification/>), and how it
covers the big agent-orchestration ideas: **hierarchical vs mesh**, **message
protocol design**, **coordination efficiency**, **context persistence**, **group
vs individual**, and **roles / intentions / motivations**.

The whole system is a *Smart Trip Planner*: a **host agent** coordinates five
**specialist agents** (Destination, Itinerary, Budget, Weather, Cuisine), each a
separate web service that speaks A2A.

---

## 1. What A2A actually is (30-second version)

A2A is an open protocol that lets independent AI agents — built by different
people, in different frameworks — **discover and call each other over plain
HTTP**. Think "a shared language so one agent can hire another." Three ideas do
all the work:

| A2A concept | What it means | Where it lives here |
|---|---|---|
| **Agent Card** | A public JSON file at `/.well-known/agent-card.json` listing who the agent is and its **skills**. | every agent in [`common/a2a.py`](../common/a2a.py) (`AgentCard`) |
| **Message → Task → Artifact** | You send a **Message**; the agent runs a **Task** (`submitted → working → completed`) and attaches an **Artifact** (the answer). | `Message`, `Task`, `Artifact` in `common/a2a.py` |
| **Two call styles** | `message/send` (ask once, get the result) and `message/stream` (watch it happen live via Server-Sent Events). | `A2AClient.send` / `.stream` |

Everything is **JSON-RPC 2.0 over HTTP POST** to the agent's `/`, matching A2A
protocol version **`0.3.0`** field-for-field. This repo implements the wire
format by hand (in one readable file) so you can see every byte.

---

## 2. Message protocol design

A2A messages carry a free-form **`metadata`** dict. We use it as a tiny
**FIPA-ACL-style speech-act layer** — i.e. *why* a message is being sent, not
just *what*:

```jsonc
// the message a host sends a specialist
{ "role": "user",
  "parts": [{ "kind": "text", "text": "Plan a 5-day itinerary for Kyoto…" }],
  "contextId": "ctx-1a2b3c",                 // which conversation this belongs to
  "metadata": {
    "performative": "request",               // FIPA act: request / inform / propose / counter / agree / query
    "intent": "Plan a day-by-day itinerary"  // the motivation behind the call
  }
}
```

So a single message answers three questions: **what** (the text part), **why**
(`performative` + `intent`), and **which conversation** (`contextId`). That's the
core of good agent message design — and it's what makes the negotiation below
read like people talking, not RPCs firing.

See `Message.metadata` and `RequestContext` in [`common/a2a.py`](../common/a2a.py).

---

## 3. Roles, intentions & motivations

Each specialist is more than an endpoint — it has a declared **role** and
**motivation**, and every delegation carries an **intent** (its reason):

```python
# common/config.py
{ "key": "budget", "role": "Fiscal advisor",
  "motivation": "Keep the trip affordable and the costs transparent",
  "intent": "Estimate costs and keep the trip on budget" }
```

On top of that, every agent now has a **human persona** — a name, a job title,
and a speaking style ([`common/persona.py`](../common/persona.py)):

| Agent | Persona | Voice |
|---|---|---|
| Destination | **Mateo** | warm, well-travelled, drops cultural tips |
| Itinerary | **Priya** | organised, thinks in schedules & trade-offs |
| Budget | **Sam** | frank and frugal, watches every dollar |
| Weather | **Lin** | careful, data-driven, cautious about the forecast |
| Cuisine | **Giulia** | passionate foodie, always a little hungry |

The host also models the **user's** intent every turn: an `understand` step
keeps a live picture of *beliefs* (destination, days, interests, style) and
*intent* (`goal`, `constraints`). See [`MEMORY_AND_INTENT.md`](MEMORY_AND_INTENT.md).

---

## 4. How each agent "talks" and decides for itself

An agent has **two modes**, chosen from the incoming message's `metadata.mode`
(see `persona_aware` in [`common/persona.py`](../common/persona.py)):

1. **Do its job** — no special mode → it produces its full expert write-up
   (Budget makes a budget, Weather calls its live MCP tool, etc.).
2. **Talk** — `mode: "negotiate"` or `mode: "consult"` → it drops the formal
   report and *speaks*: 1–3 first-person sentences, in persona, addressing
   colleagues by name, coloured by the `performative`.

Crucially, **the agent authors its own words.** The orchestrator sets the turn
order and a short brief; the *decision* — what to push back on, what to concede,
what to propose — is made by the agent itself (its own LLM call with its own
persona system prompt). That's what makes it feel human rather than scripted.

Some agents go further and **decide, by their own role, to consult a peer**
before speaking (see mesh, below): Priya phones Lin about the weather; Giulia
phones Sam about the budget. Nobody tells them to — it's baked into their role
(`CONSULT_POLICY`).

---

## 5. Orchestration architecture: hierarchical **and** mesh

Both patterns are used, on purpose, because each is good at a different thing.

### Hierarchical (a host coordinates specialists)
This is the backbone. The **host agent** discovers the specialists (reads their
Agent Cards), delegates to them **in parallel**, then synthesises one plan.

```
                ┌─────────────┐
                │  HOST agent │   ← decides who runs, merges the answers
                └──┬───┬───┬──┘
        request →  │   │   │  (A2A message/stream, one per specialist)
            ┌──────┘   │   └──────┐
            ▼          ▼          ▼
       Destination  Itinerary   Budget …      (specialists don't talk to each other)
```

Good for: clear control, easy to reason about, parallel speed.

### Mesh (specialists talk **directly** to each other)
During the round-table, an agent can make a **real A2A call straight to another
agent** — the host is *not* in the loop. Priya (Itinerary) calls Lin (Weather)
directly to ground her plan in the forecast before she answers Sam (Budget):

```
   Priya ───────(A2A message/stream, mode:"consult")──────▶ Lin
     ▲                                                       │
     └──────────────── Lin's answer ◀────────────────────────┘
   (the HOST never sees this call — that's the point of mesh)
```

Good for: autonomy and realism — agents resolve things peer-to-peer the way
colleagues would, without routing everything through a manager. The trade-off:
the orchestrator can't observe peer traffic, so each agent *narrates* its peer
calls (you'll see "Priya is consulting Lin directly over A2A (mesh)…" in the
protocol log). Implemented by `consult_peer()` in `common/persona.py`.

**Rule of thumb:** hierarchical for *coordination and merging*; mesh for
*autonomous, role-driven cross-checks*.

---

## 6. Group vs individual patterns

| Pattern | What it looks like here | When it's used |
|---|---|---|
| **Individual (1:1)** | Host → one specialist, `message/stream`, one focused task. | the delegation phase — five independent 1:1 calls, in parallel |
| **Group (round-table)** | All present specialists take turns in one shared discussion, each seeing the running transcript and replying to the others. | the negotiation phase (`negotiate()` in [`orchestrator/orchestrator.py`](../orchestrator/orchestrator.py)) |

So the same agents are used **individually** to gather expertise, then as a
**group** to reconcile trade-offs (cost vs ambition, weather vs outdoor plans).

---

## 7. Coordination efficiency

Re-running every agent on every follow-up wastes time and tokens. The host only
re-runs the specialists whose **inputs actually changed**, and reuses cached
answers for the rest (`SELECTION_RULES` in `orchestrator/orchestrator.py`):

```
"make it cheaper"  → travelStyle changed → re-run {budget, itinerary, cuisine}
                                            reuse  {destination, weather}  (cached)
```

You can watch this in the UI: changed agents show *working*, the rest show
*reused (cached)*.

---

## 8. Context persistence across conversations

A2A's **`contextId`** threads a multi-turn conversation. We persist that context
in **SQLite** (`data/atlas.db`) so memory survives restarts:

- **Per conversation** (keyed by `contextId`): the latest beliefs, intent, and
  each specialist's last result (for the caching above).
- **Per user** (long-term): durable preferences ("enjoys street food", "prefers
  budget travel") that carry across *different* trips.

So a follow-up like *"add 2 days and make it budget"* updates the existing plan
instead of starting over, and the next visit still remembers what you like. See
[`common/memory.py`](../common/memory.py) and [`MEMORY_AND_INTENT.md`](MEMORY_AND_INTENT.md).

---

## 9. The full lifecycle of one request

```
1. RECALL     load this conversation + your long-term preferences   (context persistence)
2. UNDERSTAND update beliefs + model the goal/intent                (intentions)
3. DISCOVER   read each specialist's Agent Card                     (A2A discovery)
4. SELECT     run only the agents whose inputs changed              (coordination efficiency)
5. DELEGATE   call them in parallel, intent in the metadata         (individual / hierarchical)
5b. NEGOTIATE the specialists discuss as a group, in persona…       (group)
              …and some phone each other directly                   (mesh)
6. SYNTHESISE merge everything — honouring the agreements reached
7. PERSIST    save beliefs, intent, results, new preferences        (context persistence)
```

Every step streams to the UI/CLI live, so you can watch the agents discover,
delegate, negotiate, and agree in real time.

---

## What was newly added (vs the original prototype)

- **A 5th specialist** — the **Local Cuisine Expert** (port 8105), a full A2A agent.
- **Human personas** for all agents + a **negotiation mode** (`common/persona.py`).
- **A group round-table** where specialists negotiate over A2A using FIPA
  performatives, before the host synthesises (`negotiate()` in the orchestrator).
- **Mesh / peer-to-peer** — agents calling each other directly over A2A
  (`consult_peer()` + `CONSULT_POLICY`), making the architecture both
  hierarchical *and* mesh.
- Live rendering of all of the above in the **web UI**, **CLI**, and the
  **orchestrator-as-an-agent** composition path.
