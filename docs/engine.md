# Engine Integration

## What this document is

Atlas today runs 100 agents inside a single program. They talk to one another through an in-process router,
using A2A-style concepts (messages, tasks, parts, extensions, and human-in-the-loop approval). The goal of this
design is to refit Atlas so that **each agent is backed by its own September Engine, and agent-to-agent messages
become engine-to-engine calls** — so that engines, not in-process objects, do the communicating.

The document answers the two questions that were asked:

- Section 1: what to change, do, and implement on the Engine side.
- Section 2: what to do on the A2A side.

## Summary of the decisions

1. **Target the v2 "clean-break" Engine API.** Two source documents describe a redesigned Engine API
   (`engine-api-shape-v2.html` and `engine-api.html`): a single `POST /execute` endpoint that streams typed
   "blocks", a persistent `thread_id`, an input field tagged by `kind` (`input` or `block_input`), a `done`
   status of completed / awaiting / failed / cancelled, output "gates", a replay endpoint, and a separate
   live-data channel system. The currently shipping API (version 2.3, which uses `message` + `task_id`, a
   `/hitl/respond` endpoint, raw events, MCP connectors, sub-agents, and the `bap-engine` fleet) is treated as
   the migration baseline and shown as a second column. The v2 redesign maps far more cleanly onto A2A, so it
   leads.

   Note on terminology: the "v2 clean-break" is the API redesign (blocks, threads, gates). "Version 2.3.0" is
   the shipping product version. These are two different things; in this document, "v2" means the API redesign.

2. **One Engine per agent.** A fleet of 100 engines, one per agent, provisioned by `bap-engine`. This is the
   literal meaning of "engines communicate". A lighter alternative — running all agents as sub-agents inside a
   single engine — is described but not chosen, because that is one engine with helpers, not engines talking to
   each other.

3. **The new work is the bridge between engines.** September engines do not talk to each other by design. In
   September, "multi-agent" means sub-agents nested inside one `/execute` call; the fleet runs one engine per
   user but the engines never message one another; any cross-engine coordination lives in a separate upstream
   layer (BAP). So Atlas must supply the engine-to-engine layer that September deliberately leaves out — and
   that layer is the A2A binding. Everything below revolves around this one fact.

4. **Atlas keeps the "what"; the Engine becomes the "how".** Atlas keeps the organisation model, the
   need-to-know rules, the routing directory, the human-approval console, the scheduled-goal simulator, and the
   metrics. The Engine takes over each agent's per-turn reasoning, message writing, the visible thinking step,
   streaming, the human-approval primitive, tools, and memory.

## The central constraint, and what it is not

- **Engines are single-tenant and isolated.** One engine is one memory for one user. There is no
  engine-to-engine remote call, no built-in A2A, and no shared bus.
- **The channel system is not for agent-to-agent traffic.** Channels carry live data from external services
  (for example, vehicles on a map) into generated dashboards. A2A maps only onto the `/execute` block stream,
  never onto channels.
- **`bap-engine` is a fleet manager, not a message bus.** It provisions, finds, and health-checks one engine per
  user, then stays out of the data path. Atlas uses it to create the 100 engines and to look up a peer's
  address, but the actual agent-to-agent call is a direct `POST /execute` from one engine to another, made by a
  bridge tool that Atlas adds.

So the whole integration reduces to one thing: give each agent's engine a way to call another agent's engine's
`/execute`, and a convention for what to put in that call. That is the A2A binding.

## 1. The topology and the engine-to-engine path

One engine per agent. `bap-engine` provisions 100 engine containers, one per agent, each with its own memory,
its own catalogue (system prompt, skills, tools), and its own API key. Atlas's in-process agent registry becomes
a real fleet registry, and `bap-engine` provides the lookup ("admit") entry point.

The core mechanism, which is essentially the whole integration: when agent A's engine needs information item X
from agent B:

```
 Agent A's engine  (thread_id = the shared conversation id)      Agent B's engine
 ----------------------------------------------------------      -------------------------------
  the loop decides it needs X
   -> calls the tool  a2a.ask(target = AGT-B,
        intent = {motivation, purpose, scope}, item = X)
          |
          |- look up B's address and key:
          |    bap-engine  POST /engines/AGT-B/admit
          |
          |- POST /execute to B with the A2A request envelope
          |                                                       the loop in B decides the share:
          |                                                         it weighs X's sensitivity and scope
          |                                                         against A's role, clearance, and intent
          |                                                         -> share / redact / deny
          |                                                         -> or escalate: ask a human (awaiting)
          |  receives B's blocks (text / result / done)  <--------
   the loop in A continues with X (or its redaction or denial)
```

That single round trip — A's engine calls the bridge tool, looks up B, posts to B's `/execute`, B streams its
answer back, and A's tool result carries that answer — is the entire mechanism. Group coordination is the same
call sent to several teammates' engines.

A lighter alternative, not chosen: model the agents as sub-agents inside a single engine (September's built-in
multi-agent style). This is cheaper (one engine, not a hundred) and needs no bridge, but it is one engine with
helpers rather than engines communicating, and it loses the separate per-agent memory and credentials that make
the confidentiality demonstration meaningful. Use it only for an early proof of concept.

## 2. What stays in Atlas versus what the Engine now provides

This split is the work: it says exactly what to build where.

| Concern | Stays in Atlas (the product and org layer) | Now provided by the Engine (per agent) |
|---|---|---|
| Organisation structure | the 100-agent tree, teams, projects, clearance, and seeded secrets | — |
| Agent identity | the agent card and org-profile | the engine's catalogue (its system prompt) plus profile facts in memory |
| Owned information | the context items (sensitivity, scope, required clearance) | facts stored in that engine's own memory |
| Per-turn reasoning | (previously a single model provider) | the engine's loop, one `/execute` turn |
| Message wording | (previously a phrasing call) | the engine's text blocks |
| The thinking step | (previously a thinking call) | the engine's reasoning blocks |
| Need-to-know rules | the sensitivity, scope, and intent model, and the policy | applied by the owner engine (system prompt plus a decide-share step) |
| Routing | the model picks an owner from the 100 cards | a coordinator engine reading the fleet directory |
| Group coordination | the grouping decision and group sessions | the initiator engine sends the bridge call to teammates' engines |
| Human approval | the approval queue and operator console | the engine's awaiting primitive; the Atlas console consumes it |
| Scheduled goals | the scheduler and the goal list | each goal becomes a `POST /execute` to an agent's engine |
| Metrics | the router's counters | derived from the engine's block or event stream |
| Transport | the in-process router | HTTPS plus a streaming response between engines (`/execute`) |
| Discovery | the card endpoint | `bap-engine` lookup plus a card registry |
| The user-interface event contract | the existing event schema | a thin adapter that maps engine blocks to Atlas events |

## Section 1 — Engine side: what to change, do, and implement

The Engine is a product we use, so most of the work is configuration, catalogue content, and one bridge tool —
not changing the Engine itself.

1. **Provision the fleet (one engine per agent).** Stand up `bap-engine` and provision one engine per agent.
   Keep a mapping from each agent id to its engine address and key. This replaces the in-process registry with a
   real fleet. (The September guidance is to scale by running more engines, not more work per engine, so 100
   engines is the intended shape.)

2. **Encode each agent's identity in its catalogue.** For each agent, generate a catalogue entry whose system
   prompt is written from that agent's profile (role, department, level, goal, clearance, teams, projects), plus
   the A2A request format (so the engine knows how to read an incoming bridge call) and the need-to-know policy
   (how to decide what to do with requests for its own data). The agent's skills become engine tools.

3. **Load each agent's owned information into its memory.** Each agent's secrets — with their sensitivity,
   scope, required clearance, and safe summary — become facts in that engine's own memory. Because each engine
   is a separate container, the isolation becomes real: a secret physically lives only in its owner's engine,
   not just behind a policy check.

4. **Add the outbound bridge tool.** Give every agent's engine a tool, `a2a.ask(target, intent, item)` (and a
   group variant). It looks up the target engine's address, posts the A2A request to it, reads the streamed
   answer, and returns that answer (the decision plus any delivered content) to the calling loop. This tool is
   the thing that makes engines communicate.

5. **Define the inbound convention.** No engine code change is needed. An incoming A2A call is simply a
   `POST /execute` whose input carries the A2A request envelope (section 2). The owner engine's system prompt
   teaches it to recognise that envelope and respond with a share decision. The thread id equals the shared
   conversation id, so a multi-engine conversation stays correlated.

6. **Make the share decision the owner engine's job.** The owner's need-to-know decision becomes the owner
   engine's own judgement — either inline in the loop or as a dedicated, repeatable step. The output is share,
   redact, deny, or escalate.

7. **Run the compliance review.** After the owner decides, the deterministic compliance Policy Engine reviews
   the decision and may tighten it. Because the Policy Engine is plain, deterministic code, the simplest design
   is to run it as a local step inside the owner engine (packaged as a shared library or a small policy service
   that every engine calls), rather than as a separate engine. It needs no model call.

8. **Match human approval.** When a decision is "escalate", the owner engine pauses and asks a human (it ends
   its turn in the "awaiting" state, or raises a human-approval event on the shipping API). The Atlas operator
   console watches each engine's approval surface, the operator answers, and the bridge passes the answer back.
   There is one global operator and many owner engines, so the console aggregates the pending approvals across
   the fleet.

9. **Add the coordinator and the scheduler.** Routing (choosing the owner from the 100 cards) becomes a
   coordinator engine that reads the fleet directory and makes the bridge call to the chosen owner. Scheduled
   goals become a scheduler that posts a goal into an agent's engine. The activity trace (routing, the share
   decision, the compliance review) is read from the engine's trace output.

## Section 2 — A2A side: what to do

September has no built-in A2A, so Atlas defines the A2A-over-Engine binding. Three parts: a mapping, the request
format, and the concrete edits.

### 2.1 Mapping from A2A concepts to the Engine

| A2A concept (Atlas today) | v2 binding (primary) | Shipping 2.3 binding (baseline) |
|---|---|---|
| Agent card plus org-profile | one engine per agent; the card becomes the catalogue plus memory facts; the address is the engine's `/execute` url | the same; look up via `bap-engine` |
| Message (the turn) | the `/execute` input field carrying the A2A envelope | the `/execute` body's `message` plus `task_id` |
| Part (text / data / file) | blocks: text, generated-UI, image, or media | content blocks: text, tool, media |
| Task | the engine thread (`thread_id`) | the engine thread (`task_id`) |
| Task state: submitted / working | turn start, then streaming blocks | the start event, then content events |
| Task state: completed | `done` status completed | the completed event |
| Task state: input-required | `done` status awaiting, plus a waiting prompt | a human-approval event |
| Task state: failed | `done` status failed, plus an error block | the error event |
| Task state: canceled | `done` status cancelled | the shutdown drain |
| Send message | `POST /execute`, engine to engine via the bridge tool | the same |
| Stream a task | native: the `/execute` block stream | native: the `/execute` event stream |
| Human approve / deny | reply with a `block_input` | post to `/hitl/respond` |
| Reconnect / resume | the replay endpoint | the replay endpoint |
| Need-to-know extension | fields in the A2A envelope plus the owner engine's prompt | the same |
| Coordination extension | the group bridge call plus the waiting prompt | sub-agent or fan-out plus a human-approval event |
| Need-to-know decision | the owner engine's reasoning or a repeatable step | the same |
| Discovery | `bap-engine` lookup plus a card registry | the same |
| Atlas event schema | a thin adapter from engine blocks to Atlas events | an adapter from engine events to Atlas events |

The channel system is deliberately absent from this table: it carries live external data, not agent messages.
A2A rides only on `/execute`.

### 2.2 The A2A request format

The A2A details that used to live in a message's metadata now travel inside the engine input. Define one small
structured envelope (carried in the v2 input field, or written into the shipping `message` text with a short
natural-language preamble so the model reads it cleanly):

```json
{
  "a2a": "context-request",
  "context_id": "ctx-...",
  "requester": { "agent_id": "AGT-005", "role": "Engineering Manager",
                 "clearance": 3, "teams": ["engineering-team-3"], "projects": ["billing"] },
  "intent":    { "motivation": "need the billing architecture record to ramp up",
                 "purpose_tag": "task-context", "declared_scope": "project" },
  "item":      { "title": "Atlas Core architecture decision record" },
  "respond_with": ["share", "redact", "deny", "escalate"]
}
```

The owner engine, taught by its system prompt, returns its decision as a text block plus any delivered content,
and the requester's bridge tool surfaces that as the tool result. The need-to-know policy is never the Engine's
own concern; it is encoded per owner engine, and the envelope just carries the inputs to that judgement.

### 2.3 Concrete A2A edits (in `atlas/a2a/`)

1. **Add a transport binding.** Atlas A2A is in-process today. Define a "september-engine" transport and put the
   engine's `/execute` address on the card. Send-message becomes a `POST /execute`; streaming becomes the engine
   stream. This finally gives Atlas a real network transport.
2. **Extend the security schemes to engine-to-engine calls.** Atlas already declares the five A2A scheme types
   on every card and enforces an opt-in API key at its edge (the A2A compliance document's §7); the engine
   integration adds a per-engine API key on the card so authentication spans engine-to-engine `/execute` calls,
   not just the operator edge.
3. **Map identity.** The A2A agent id maps to the engine's user or engine id; the card's address maps to the
   engine's address from the fleet lookup.
4. **Map task to thread, and every task state to the engine's done-status,** per the mapping above. The shared
   conversation id becomes the shared engine thread id, so a multi-engine conversation stays correlated.
5. **Bind human approval.** Input-required maps to the engine's awaiting state or human-approval event; approve
   and deny map to the engine's reply. The operator console aggregates approvals across engines.
6. **Carry the extensions in the envelope** (section 2.2) instead of in message metadata; document the envelope
   as the need-to-know and coordination binding.
7. **Keep a card registry** (agent id to card and engine address), fed by the fleet, and optionally let each
   engine serve its own card on request.
8. **Gain real task streaming for free** — the engine's `/execute` stream is, in effect, A2A streaming. This
   closes a second gap from the compliance document (the missing `message/stream`). The adapter maps the block
   lifecycle to A2A status and artifact updates.

The net effect on the A2A compliance picture: a remaining gap (task streaming) becomes implemented, the edge
authentication Atlas already has extends across the fleet, and the in-process transport non-goals become a real
"september-engine" transport.

## 3. Phased plan

| Phase | What it delivers | Topology and API |
|---|---|---|
| 0. Proof of concept | three to five agents as sub-agents inside one engine; prove the share decision, the human approval, and the message format end to end | one engine, sub-agents |
| 1. Fleet and bridge | `bap-engine` provisions the engines; the bridge tool and the request format; a real A-to-B request works engine to engine | one engine per agent, v2 `/execute` |
| 2. Full need-to-know | the per-owner share decision, the deterministic compliance review, and human approval aggregated to one operator console | v2, fleet |
| 3. Coordination and UI | coordinator-engine routing over the directory, group coordination, the scheduler, and the adapter that lets the existing mission-control interface render engine streams | v2, fleet |

Keep the shipping 2.3 bindings (the second column of the mapping) as a fallback until the v2 API ships. The
request format and the split are identical across both, so only the wire adapter changes.

## Companion documents

`a2a.md` records what A2A Atlas implements today, and this design closes its security-schemes and
streaming gaps. `CLAUDE.md` describes the current in-process architecture being refit. The Engine source
material is `engine-api-shape-v2.html` (the v2 internal design), `engine-api.html` (the v2 public reference),
and the September documentation site (the shipping 2.3 platform and the `bap-engine` fleet).
