# A2A explained (for beginners)

This is a plain‑language tour of the **Agent‑to‑Agent (A2A)** protocol, using the
Smart Trip Planner in this repo as a running example. No prior knowledge needed.

---

## 1. The problem A2A solves

AI “agents” are programs that can reason and take actions. Increasingly, the
agent that talks to *you* isn't the best one to do *every* part of a job. You'd
like it to **call other specialist agents** — maybe built by other teams or
companies, in other programming languages — and combine their work.

But how does agent A *call* agent B if they share no code? They need:
1. a way for B to **describe itself** (“I'm a budget expert, here's how to reach me”),
2. a shared **message format** (“here's a task; here's the answer”),
3. a shared **notion of a task and its progress** (“working… done”).

**A2A is exactly that shared contract.** It's an open standard (Google, 2025; now
a Linux Foundation project) so any A2A‑speaking agent can call any other over
ordinary HTTP.

> 🧠 **Analogy.** A2A is like a *standardised job order between companies*. You
> don't need to know how the other company works inside — you read their
> brochure (the **Agent Card**), send a purchase order (a **Message**), and they
> open a **Task**, work it, and hand back the **deliverable** (an **Artifact**).

---

## 2. A2A vs MCP — the question everyone asks

These two are **complementary**, not competitors:

| | **MCP** (Model Context Protocol) | **A2A** (Agent‑to‑Agent) |
|---|---|---|
| Connects | an agent → **tools / data** | an agent → **another agent** |
| Mental model | “give my model a new *tool*” | “let my agent *hire* another agent” |
| The other side is… | a function/resource (a calculator, a database) | an autonomous peer that reasons on its own |
| Example here | the **Weather Advisor** calling a `get_weather` tool (live Open‑Meteo data) | the orchestrator delegating to the **Itinerary agent** |

Rule of thumb: **MCP gives one agent more abilities; A2A lets many agents
collaborate.** A real system often uses both — and this prototype does:
see **[MCP_AND_COMPOSITION.md](MCP_AND_COMPOSITION.md)**.

---

## 3. The four building blocks

### a) The **Agent Card** — an agent's public “business card”
Every A2A agent serves a small JSON file at a well‑known URL:

```
GET http://127.0.0.1:8101/.well-known/agent-card.json
```

It advertises *who the agent is* and *what it can do*. From this prototype:

```json
{
  "protocolVersion": "0.3.0",
  "name": "Destination Expert",
  "description": "Describes a destination: overview, best time to visit, and local tips.",
  "url": "http://127.0.0.1:8101/",
  "version": "1.0.0",
  "preferredTransport": "JSONRPC",
  "capabilities": { "streaming": true, "pushNotifications": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    {
      "id": "destination_overview",
      "name": "Destination Overview",
      "description": "Give an overview of a place, when to go, and etiquette tips.",
      "tags": ["travel", "destination", "culture"],
      "examples": ["Tell me about Kyoto"]
    }
  ]
}
```

**Discovery** = a client fetching this card to learn how to use the agent. In our
app, the orchestrator fetches all four cards before delegating (you can watch it
in the Protocol Log).

### b) The **Message** — what you send an agent
A message has a `role` (`user` or `agent`) and a list of `parts`. A text part is
just `{"kind": "text", "text": "..."}`:

```json
{
  "kind": "message",
  "role": "user",
  "messageId": "m-1",
  "parts": [{ "kind": "text", "text": "Tell me about Kyoto." }]
}
```

> The `kind` fields are **discriminators** — they tell a parser whether something
> is a text part, a file part, a message, a task, etc.

### c) The **Task** — the unit of work
When an agent receives a message it creates a **Task** and moves it through a
**lifecycle**:

```
submitted ──► working ──► completed        (the happy path)
                  │
                  ├─► input-required   (agent needs more info from you)
                  ├─► failed           (something went wrong)
                  └─► canceled / rejected
```

A finished task carries its result as an **Artifact**:

```json
{
  "kind": "task",
  "id": "task-29d94a27",
  "contextId": "ctx-6931f3e0",
  "status": { "state": "completed" },
  "artifacts": [
    { "artifactId": "art-0d213b1c", "name": "result",
      "parts": [{ "kind": "text", "text": "Kyoto is ..." }] }
  ]
}
```

### d) The **Artifact** — the deliverable
The tangible output (here, the answer text). Tasks can have several artifacts;
ours each return one.

---

## 4. How agents actually talk: JSON‑RPC + SSE

A2A messages travel as **JSON‑RPC 2.0** over an HTTP `POST` to the agent's URL.
A request names a `method` and carries `params`:

```json
{ "jsonrpc": "2.0", "id": "req-1", "method": "message/send",
  "params": { "message": { "...": "..." } } }
```

There are two ways to ask:

| Method | Behaviour | Used by |
|---|---|---|
| **`message/send`** | Ask once, get the **finished Task** back in one response. | `show_protocol.py`, the CLI |
| **`message/stream`** | Ask once, then receive a **live stream** of events as the work happens. | the orchestrator / UI |

**Streaming** uses **Server‑Sent Events (SSE)**: the HTTP response stays open and
the agent sends a sequence of `data:` lines. Each line is a JSON‑RPC response
whose `result` is one event. A typical stream for one task:

```
data: {"jsonrpc":"2.0","id":"req-2","result":{"kind":"task","status":{"state":"submitted"}, ...}}

data: {"jsonrpc":"2.0","id":"req-2","result":{"kind":"status-update","status":{"state":"working", ...}}}

data: {"jsonrpc":"2.0","id":"req-2","result":{"kind":"artifact-update","artifact":{...the answer...}}}

data: {"jsonrpc":"2.0","id":"req-2","result":{"kind":"status-update","status":{"state":"completed"},"final":true}}
```

Two things to notice:
- The events go **`submitted → working → artifact-update → completed`** — that's
  the task lifecycle, streamed.
- The last event has **`"final": true`**. That's how the client knows the stream
  is over and it can stop listening. *(Forget this and clients hang forever — a
  classic A2A bug.)*

You can see every one of these frames in the **A2A Protocol Log** in the UI, or by
running `python show_protocol.py`.

---

## 5. How real is this?

This prototype is a **teaching model**. It is faithful where it counts and
simplified where the details would distract a beginner.

**What's real / spec‑accurate**
- The **Agent Card** shape and the `/.well-known/agent-card.json` location.
- The **JSON‑RPC** envelope and the method names `message/send`, `message/stream`,
  `tasks/get`.
- The **Task / Message / Part / Artifact** JSON, the `kind` discriminators, the
  lowercase task **states**, and the **SSE** streaming events (`status-update`,
  `artifact-update`, with the `final` flag).
- These were validated field‑by‑field against the official `a2a-sdk`, so an agent
  here speaks the same JSON a “real” A2A client expects (protocol `0.3.0`).

**What's simplified (on purpose)**
- **No authentication.** The spec supports API keys, OAuth, etc. via the Agent
  Card's `securitySchemes`. We run on localhost and skip it. *Never expose an
  unauthenticated agent to the internet.*
- **No multi‑turn `input-required`.** Real agents can pause a task to ask you a
  question; ours answer in one shot.
- **No push notifications / webhooks** (the spec's way to be told about long jobs).
- **One text part per message.** A2A also supports file and structured‑data parts.
- We **implement the protocol by hand** in [`common/a2a.py`](../common/a2a.py)
  instead of using the official SDK, so the wire format is visible. The official
  `a2a-sdk` (PyPI) is what you'd reach for in production; its current 1.x core
  types are generated from Protocol Buffers.

---

## 6. Learn more
- Official site, spec, and SDKs: <https://a2a-protocol.org>
- The whole protocol, readable, in this repo: [`common/a2a.py`](../common/a2a.py)
- See it on the wire: `python show_protocol.py`
- How this app is built: [ARCHITECTURE.md](ARCHITECTURE.md)
