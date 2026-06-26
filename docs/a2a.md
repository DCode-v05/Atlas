# A2A Compliance — Index

This audit records, feature by feature, how much of the [A2A protocol](https://a2a-protocol.org) Atlas actually
implements. It is **split by status into three files**:

- **[a2a-implemented.md](./a2a-implemented.md)** — features that work, each with **why it's implemented** (the role it plays in Atlas).
- **[a2a-partial.md](./a2a-partial.md)** — features present but incomplete, each broken into **what's implemented (and why)**, **what's missing**, and **what completing it would unlock**.
- **[a2a-not-implemented.md](./a2a-not-implemented.md)** — absent features (and the `By design` non-goals), each broken into **what's missing** and **what it would unlock if built**.

This index keeps the shared context — what Atlas is, the version basis, the status legend, and the summary
counts. The `By design` rows live in the Not-implemented file, tagged in its Status column.

## What this document covers

A2A (Agent-to-Agent) is an open protocol that defines how independent AI agents describe themselves, send each
other messages, and track work as tasks.

The key thing to understand up front: Atlas is a **faithful in-process implementation**. All 100 agents run
inside one program and talk to each other through a central in-process router, rather than as separate network
services calling each other over HTTP. Atlas reproduces the A2A **object model and behaviour** (agent cards,
messages, parts, tasks, the task lifecycle, extensions) very closely, but it does **not** put A2A "on the wire"
— there is no network protocol between agents. The only real network connection is between the browser and the
backend (a REST API plus a live event stream for the user interface), and that stream carries Atlas's own event
format, not the A2A streaming format.

## Version basis (read this before the status splits)

This audit is taken against **A2A v1.0.0** — the current `latest` release — using its **normative
`specification/a2a.proto`** as the authority for every field name and shape. Atlas's data models, by contrast,
were built to the **0.2.x JSON representation** of A2A (camelCase fields like `messageId`/`contextId`, a
`kind`-discriminated `Part`, a top-level card `extensions` array). Between 0.2.x and 1.0.0 the spec was
**re-grounded on a Protocol-Buffers data model** and several names and structures changed: the `Part` union was
flattened, the JSON-RPC methods were renamed to PascalCase, `additionalInterfaces` became `supportedInterfaces`,
`security` became `securityRequirements`, `supportsAuthenticatedExtendedCard` became
`capabilities.extendedAgentCard`, `stateTransitionHistory` was dropped, and a `tenant` routing field plus
"service parameters" were added.

So a single convention runs through all three files:

> **A status or note tagged `(v1.0.0 drift)` means the spec moved underneath a feature Atlas implements
> faithfully to its 0.2.x target — it is *not* an Atlas capability gap or a regression.** Plain
> `Partial` / `Not implemented` is reserved for genuine gaps (a type that is defined but never produced, a path
> that does not exist). Serialization-only differences (lowercase `user` vs ProtoJSON `ROLE_USER`) are noted, not
> downgraded.

## How to read the status column

| Status | Meaning |
|---|---|
| Implemented | Present and working. For agent-to-agent items this means the behaviour is reproduced in-process, noted as "(in-process)". |
| Partial | Present but incomplete, shaped differently from the spec, or defined in the code but never used. |
| Not implemented | Absent. |
| By design | Deliberately not built, because the single-process architecture makes it unnecessary. |

The "Evidence" column in each file points developers at the relevant source file (and, where stable, a line
range). Line numbers are from the time of the audit and may have drifted slightly; the file and symbol name are
the reliable reference.

## Summary

| Section | Implemented | Partial | Not implemented | By design |
|---|--:|--:|--:|--:|
| 1. Agent Card and discovery | 14 | 2 | 1 | 0 |
| 2. Core data objects | 21 | 0 | 0 | 0 |
| 3. RPC methods | 7 | 1 | 1 | 0 |
| 4. Transports | 1 | 0 | 3 | 2 |
| 5. Streaming | 6 | 0 | 1 | 0 |
| 6. Push notifications | 4 | 0 | 1 | 0 |
| 7. Authentication and security | 4 | 1 | 0 | 0 |
| 8. Extensions mechanism | 7 | 0 | 0 | 0 |
| 9. Error handling | 3 | 0 | 0 | 1 |
| Total | 67 | 4 | 7 | 3 |

In one sentence: audited against **A2A v1.0.0**, Atlas faithfully reproduces the A2A object model and core
behaviour in-process — agent cards, messages, parts, tasks, the full set of task states, the task lifecycle, the
send-message path, and the extensions mechanism (versioned through the URI) — and now also implements
**push notifications** (webhook config objects + `pushNotificationConfig/*` CRUD + live delivery), **edge
authentication** (opt-in API-key with 401/403, plus `securitySchemes`/`securityRequirements` on the card),
**A2A discovery** (the public card at `/.well-known/agent-card.json` + an agent catalog + authenticated
**extended** cards), **task cancellation** (`tasks/cancel` → `canceled`), **per-task streaming** (`SubscribeToTask`
with ordered `StreamResponse` frames and a final-flag terminal close), a spec-shaped **HTTP+JSON binding** (`/v1`
colon-verb paths with version + extension negotiation), the full **task lifecycle** (incl. `rejected` and a
park-and-resume `auth-required`), **GetTask** / **ListTasks** (history truncation, filters, pagination),
**DataPart** / **FilePart** / `referenceTaskIds` in task artifacts, and the **named A2A error model** at its
external edge; but it does not put A2A on a network wire. The remaining absent pieces are the on-the-wire
transport features (gRPC, transport negotiation, `tenant` routing) and the *initial-send* streaming method
`SendStreamingMessage`; three further items (a JSON-RPC envelope between agents, multi-transport equivalence,
and JSON-RPC error objects) are intentional non-goals of running everything in one process.
