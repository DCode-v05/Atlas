# A2A Core vs. ATLAS Org Extensions

> **The one question this doc answers:** *"Is this REALLY A2A?"*
> **Yes.** ATLAS speaks compliant A2A using a small, honest slice of the protocol.
> Everything organisation-specific (roles, hiring, meetings, metrics) is layered
> *on top* via one namespaced metadata field — and a plain A2A client ignores all
> of it.

If you remember one picture, remember this:

```
   ┌─────────────────────────────────────────────────────────┐
   │  ATLAS org layer   (org/)                                │
   │  performatives · roles · hiring · meetings · ledgers     │
   │            …all carried inside message.metadata          │
   ├─────────────────────────────────────────────────────────┤
   │  CORE A2A          (protocol/)                            │
   │  Agent Card · JSON-RPC · Task lifecycle · Message/Part   │
   └─────────────────────────────────────────────────────────┘
        the bottom layer is standard A2A. the top layer rides
        along in metadata and is invisible to a plain client.
```

The whole codebase keeps this split physically: **everything in `protocol/` is
pure A2A and knows nothing about the organisation.** Everything in `org/` is the
extension. They never bleed into each other.

---

## Part 1 — What is CORE A2A (the `protocol/` package)

This is real Agent-to-Agent protocol, the kind any A2A client can talk to. Point
a standard A2A client at one of our agents and it just works — discovery, sending
a message, streaming, polling a task, cancelling. Nothing here is invented.

### The Agent Card (discovery)

Every agent serves a card at the well-known path so others can discover it:

```
GET /.well-known/agent-card.json
```

Defined in `protocol/models.py` (`AGENT_CARD_PATH`, `AgentCard`). A trimmed card:

```json
{
  "protocolVersion": "0.3.0",
  "name": "E1 · Generalist",
  "description": "A general-knowledge employee, awaiting a role assignment.",
  "url": "http://127.0.0.1:9001/",
  "preferredTransport": "JSONRPC",
  "capabilities": { "streaming": true, "extensions": ["https://atlas.org/ext/org/v1"] },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [{ "id": "general", "name": "General Work", "description": "..." }]
}
```

Note `capabilities.extensions` — that is the *A2A-blessed* way to advertise "I
also understand this extension." It is a list of URIs; honouring it is optional.

### The JSON-RPC endpoint and its four methods

The work happens over JSON-RPC 2.0 at the agent's root URL (`POST /`). The server
(`protocol/server.py`) implements exactly four methods — the minimal useful slice:

| Method           | What it does                                          |
| ---------------- | ----------------------------------------------------- |
| `message/send`   | Send a message; get back a `Task` (the result).       |
| `message/stream` | Same, but streamed as **SSE** events as work happens. |
| `tasks/get`      | Fetch a stored task by id.                            |
| `tasks/cancel`   | Cancel a task; it moves to the `canceled` state.      |

A `message/send` request looks like this:

```json
{
  "jsonrpc": "2.0",
  "id": "rpc-1a2b",
  "method": "message/send",
  "params": { "message": {
    "role": "user",
    "parts": [{ "kind": "text", "text": "Design a privacy-first doorbell" }]
  }}
}
```

### The Task lifecycle (the states)

A2A models a unit of work as a `Task` that moves through lifecycle **states**.
ATLAS uses the exact strings from the spec — **lowercase and hyphenated**
(`protocol/states.py`):

```
submitted ─▶ working ─┬─▶ completed   (terminal, success)
                      ├─▶ input-required  ─▶ (caller replies) ─▶ working …
                      ├─▶ failed      (terminal)
                      ├─▶ canceled    (terminal)
                      └─▶ rejected    (terminal)
```

The full set: `submitted`, `working`, `input-required`, `auth-required`,
`completed`, `canceled`, `failed`, `rejected`. Terminal states end the task;
`input-required` / `auth-required` *pause* it until the caller sends more on the
same `contextId`.

> Careful: the `SCREAMING_CASE` form you may have seen elsewhere
> (`INPUT_REQUIRED`) is the **gRPC/protobuf** binding of the same spec — a
> different wire surface. The JSON-RPC binding we use is lowercase-hyphenated.

### Message, Part, Artifact

The content model (`protocol/models.py`) is small and standard:

- **`Message`** — what a client sends and what an agent replies inside a status
  update. Has a `role` (`"user"` or `"agent"`) and a list of `parts`.
- **`Part`** — the content union, discriminated by `kind`:
  - `text` → a `TextPart` (`{ "kind": "text", "text": "…" }`)
  - `data` → a `DataPart` (structured JSON, e.g. a Contract-Net bid `{cost, eta}`)
  - `file` → a `FilePart` (`{name, mimeType, uri | bytes}`)
- **`Artifact`** — a produced output attached to a finished `Task` (also made of
  `parts`).

### Threading fields

These tie a conversation together (all standard A2A):

- **`contextId`** — the conversation thread. Many tasks can share one context.
- **`taskId`** — the id of a single task.
- **`referenceTaskIds`** — link a new message to prior tasks in the same context.

### Wire conventions

- **`protocolVersion` is `"0.3.0"`** (`A2A_PROTOCOL_VERSION` in `protocol/models.py`).
- **Field names are camelCase on purpose** — `contextId`, `taskId`,
  `referenceTaskIds`, `messageId`, `artifactId`. What you read in the model *is*
  what travels on the wire.
- Unset/`None` fields are dropped on serialise (`dump()`), so the protocol log
  stays clean.

**Bottom line for Part 1:** a generic A2A client that has never heard of ATLAS
can discover one of these agents, send it a message, stream its progress, and
read its result. That is the definition of "really A2A."

---

## Part 2 — What is the ATLAS ORG EXTENSION (the `org/` package)

Core A2A has **no notion** of a *performative* ("is this a request or an
answer?"), a sender *role* ("VP Engineering"), or the *intent* and *motivation*
behind a message. Those are precisely what this project studies — so we carry
them as an extension.

### The one hook: `message.metadata[ORG_EXT_URI]`

`Message.metadata` is a free-form dict that A2A already allows. We place a single
namespaced object under one key:

```
ORG_EXT_URI = "https://atlas.org/ext/org/v1"     # config.py
```

A real envelope on the wire (built by `org/envelope.py`) looks like this:

```json
{
  "metadata": {
    "https://atlas.org/ext/org/v1": {
      "performative": "request",
      "role": "Board",
      "intent": "execute the mission",
      "motivation": "Design and spec a privacy-first smart doorbell",
      "delegationDepth": 0,
      "runId": "run-9f3c1a20",
      "contextId": "run-9f3c1a20",
      "senderId": "Board",
      "mission": "Design and spec a privacy-first smart doorbell",
      "topology": "hierarchical"
    }
  }
}
```

This is the **A2A-blessed way to extend messages**: a plain client that doesn't
understand the URI simply ignores it, and the message is still a perfectly valid
A2A message. So the org behaviour is *visibly* layered on top of the protocol —
never baked into it.

### What rides in that envelope

- **Performatives (FIPA ACL)** — the *speech act*: `request`, `inform`,
  `propose`, `cfp`, `accept-proposal`, `refuse`, `agree`, `query-ref`, `failure`.
  See `Performative` in `org/envelope.py`.
- **Role / intent / motivation (BDI)** — *who* is speaking and *why*: their role,
  the goal of this message, the deeper motivation. Plus `delegationDepth`.
- **Contract-Net hiring** (`org/contract_net.py`) — a manager runs a real
  auction: `cfp` → candidates `propose` bids → winner gets `accept-proposal`,
  losers get `refuse`. The *role* is decided by negotiation on the wire.
- **Group meetings** (`org/meeting.py`) — A2A is natively **1:1** (one client,
  one agent). A meeting is therefore an extension: a coordinator owns **one
  shared `contextId`** (the meeting room) and gives each participant the floor in
  turn. Multi-party conversation emerges out of plain 1:1 A2A calls.
- **Task + Progress ledgers** (`org/ledger.py`) — a shared "brain": the mission +
  facts + plan, and a row per delegated step.
- **Telemetry** (`org/telemetry.py` + `gateway/app.py`) — agents `POST` small
  events to the gateway (`/api/ingest`); the gateway timestamps, persists to
  SQLite, derives the org chart / metrics / ledgers, and broadcasts to the
  browser over SSE (`/api/stream`). This is observability, not protocol.

> None of this changes A2A. Strip the `metadata` and you still have valid A2A
> messages flowing between compliant A2A servers — you just lose the *legibility*
> (you can't see that a message was a `cfp`, or who the sender's role was).

---

## Part 3 — Core vs. extension, side by side

| Core A2A (standard, in `protocol/`)                         | ATLAS extension (ours, in `org/`)                                  |
| ----------------------------------------------------------- | ------------------------------------------------------------------ |
| Agent Card at `/.well-known/agent-card.json`                | `capabilities.extensions` advertises `https://atlas.org/ext/org/v1`|
| JSON-RPC methods `message/send`, `message/stream`           | The **performative** of each message (`request`, `inform`, …)      |
| `tasks/get`, `tasks/cancel`                                 | Sender **role / intent / motivation** (BDI) in the envelope        |
| Task states (`submitted` … `completed`/`failed`/`canceled`) | **Contract-Net** hiring (`cfp`→`propose`→`accept-proposal`/`refuse`)|
| `Message`, `Part` (`text`/`data`/`file`), `Artifact`        | **Group meetings**: one shared `contextId`, round-robin speakers   |
| `contextId`, `taskId`, `referenceTaskIds`                   | **Task + Progress ledgers** (the org's shared memory)              |
| `protocolVersion` `"0.3.0"`, camelCase wire fields          | **Telemetry** events → gateway → SSE (org chart, metrics)          |
| Carried *by the protocol itself*                            | Carried *inside* `message.metadata[ORG_EXT_URI]`                   |

---

## So… is this really A2A?

**Yes — compliant A2A using a minimal slice of the protocol, with org behaviour
layered cleanly on top.**

Three things make that claim concrete and checkable:

1. **The agents are standard A2A servers.** They serve a real Agent Card and
   implement real JSON-RPC `message/send` / `message/stream` / `tasks/get` /
   `tasks/cancel` with the real lowercase-hyphenated Task states. Run
   `python scripts/smoke_protocol.py` — it validates exactly this surface with no
   org code involved.
2. **The extension uses the mechanism A2A provides for extensions:** a namespaced
   object in `message.metadata`, advertised via `capabilities.extensions`. A
   plain client ignores it and still gets valid A2A.
3. **The split is enforced by the code layout.** `protocol/models.py` literally
   says it "knows nothing about roles, performatives or the organisation." Those
   ride along in `metadata` (`org/envelope.py`). Nothing in `protocol/` imports
   from `org/`.

When someone asks "but is it *really* A2A?", point them here: the protocol is
genuine and minimal; the organisation is an honest extension on top.
