# 
    A2A Compliance — Not implemented

Features that are **absent**, plus the handful that are **deliberately not built** (`By design` in the Status
column — intentional non-goals of running 100 agents in one process). Audited against **A2A v1.0.0**; see
[`a2a.md`](./a2a.md) for the version-basis convention and the Implemented / Partial splits.

Each row is broken into **what's missing** and **what it would unlock if built** — the capability Atlas would
gain, framed against its actual architecture (in-process bus, single worker, SSE edge, need-to-know + policy
engine). For `By design` rows the third column explains why it's a non-goal and the only scenario that would
justify building it.

## 1. Agent Card and discovery

| Feature                                        | Status          | What's missing                                                                    | What it would unlock if built                                                                                                                              |
| ---------------------------------------------- | --------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `capabilities.extendedAgentCard`             | Not implemented | The v1.0.0 capability flag and the authenticated extended-card flow.              | An authenticated client could fetch a richer card (e.g. more skills or detail) than the public one — tiered disclosure once cards are exposed externally. |
| `capabilities.stateTransitionHistory`        | Not implemented | Nothing — this 0.x flag was**removed** in v1.0.0.                          | Nothing to build: it is no longer a spec feature. Listed only so the removal is on record.                                                                 |
| `protocolVersion`                            | Not implemented | No protocol version on interfaces.                                                | Per-interface version declaration enables version negotiation — serving 0.3 and 1.0 clients side by side.                                                 |
| `url` / `preferredTransport`               | Not implemented | No service URL or transport preference (in-process, no address).                  | A real address + preference ordering is what an external client needs to actually connect — a prerequisite for any on-the-wire transport.                 |
| `iconUrl`, `documentationUrl`              | Not implemented | The two optional presentation fields.                                             | Richer cards in catalogs/registries (icon + docs link) — cosmetic, but it helps human discovery.                                                          |
| `defaultInputModes` / `defaultOutputModes` | Not implemented | No declared media types (messages are text-only).                                 | Declaring modes lets clients negotiate content types (e.g. accept`image/png`) — the basis for multimodal exchange.                                      |
| Discovery at`/.well-known/agent-card.json`   | Not implemented | No well-known route; cards live at the non-standard`GET /api/agents/{id}/card`. | Standard discoverability — any A2A client could find an Atlas agent by domain, the entry point to the whole ecosystem.                                    |
| `GetExtendedAgentCard` (method)              | Not implemented | No authentication and no extended-card operation.                                 | The operation that serves an authenticated, tiered card (pairs with`capabilities.extendedAgentCard`).                                                    |

## 2. Core data objects

| Feature                        | Status          | What's missing                                 | What it would unlock if built                                                                                       |
| ------------------------------ | --------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `historyLength` on task read | Not implemented | Task reads return the whole task, untruncated. | Bounded reads (last N messages) for long conversations — cheaper payloads and the ability to page through history. |

## 3. RPC methods

| Feature                                                            | Status          | What's missing                                                    | What it would unlock if built                                                                                                                          |
| ------------------------------------------------------------------ | --------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Send Streaming Message (`SendStreamingMessage`)                  | Not implemented | No streamed task/status events to a client.                       | Real-time A2A streaming so an external client watches a task unfold — the agent-to-agent analogue of the browser SSE.                                 |
| Cancel Task (`CancelTask`)                                       | Not implemented | No cancel path (the`canceled` state is never reached).          | Aborting in-flight work — a long exchange or a runaway cron goal — giving operators real control.                                                    |
| Subscribe to Task (`SubscribeToTask`)                            | Not implemented | No task-subscription stream; a client can't (re)attach to a task. | Multiple/reconnecting subscribers to one task (several operators watching the same incident), each getting a current-state snapshot at subscribe time. |
| Get Extended Agent Card (`GetExtendedAgentCard`)                 | Not implemented | The method (and the auth it needs).                               | Serving an authenticated, richer card to trusted callers (the method behind the §1 capability).                                                       |

## 4. Transports

| Feature                                                 | Status          | What's missing                                                        | What it would unlock if built                                                                                                                                    |
| ------------------------------------------------------- | --------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| gRPC binding                                            | Not implemented | No gRPC service (v1.0.0 defines a full`A2AService`).                | A high-performance binary transport for agents that prefer gRPC — one of the three spec bindings.                                                               |
| Transport negotiation                                   | Not implemented | Interfaces only declare`in-process`; no negotiation.                | Clients picking among multiple transports an agent offers — a prerequisite is having more than one real transport.                                              |
| `tenant` routing identifier                           | Not implemented | No`tenant` field on requests or interfaces.                         | Serving many agents behind one endpoint and routing by tenant — relevant only if Atlas ever fronts agents over a shared external endpoint.                      |
| `A2A-Version` / `A2A-Extensions` service parameters | Not implemented | No per-request version or extension negotiation.                      | Clients declaring a protocol version and opting into extensions per request — needed for safe cross-version interop and required-extension handling.            |
| JSON-RPC 2.0 envelope between agents                    | By design       | Agents dispatch via Python in one process, not JSON-RPC over sockets. | Putting agents on real sockets. Deliberately avoided to keep 100 agents coherent in one process — only worth it if Atlas ever federates across processes/hosts. |
| Multi-transport equivalence                             | By design       | Only the in-process transport exists.                                 | Guaranteeing identical behaviour across transports — moot until there is more than one transport; a non-goal by construction.                                   |

## 5. Streaming

| Feature                                                        | Status          | What's missing                                                                                                | What it would unlock if built                                                                                       |
| -------------------------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| A2A streaming (`SendStreamingMessage` / `SubscribeToTask`) | Not implemented | No A2A streaming methods; a client cannot stream a task.                                                      | External clients streaming tasks — the agent-to-agent counterpart of the UI's SSE.                                 |
| `StreamResponse` wrapper                                     | Not implemented | Atlas emits its own event schema, not the`StreamResponse` oneof (task/message/statusUpdate/artifactUpdate). | A spec-shaped stream/webhook payload so A2A clients parse Atlas streams with standard tooling.                      |
| `TaskStatusUpdateEvent`                                      | Not implemented | Atlas emits its own`task.state` event, not the A2A shape.                                                   | Spec-shaped status events external clients understand without bespoke mapping.                                      |
| `TaskArtifactUpdateEvent`                                    | Not implemented | No artifact-update streaming event.                                                                           | Streaming partial/incremental artifacts (chunked outputs) to clients as they are produced.                          |
| Ordered-event / final-flag guarantee                           | Not implemented | No A2A ordering contract (v1.0.0 closes a stream on terminal state).                                          | Reliable, in-order delivery with terminal-close semantics — the correctness guarantee streaming clients depend on. |

## 6. Push notifications (webhooks)

Push notifications are now **implemented** — config objects, the `pushNotificationConfig/*` CRUD, and live
webhook delivery (see [Implemented](./a2a-implemented.md) §6). Only one spec row stays here, and only because it
is now moot.

| Feature | Status | What's missing | What it would unlock if built |
|---|---|---|---|
| `PushNotificationNotSupportedError` | Not implemented (moot) | The error is the refusal a server returns when it does **not** support push — and Atlas now does, so it never fires. | Nothing to build: with push supported, the "not supported" error is correctly absent. Listed only so the section stays complete. |

## 7. Authentication and security schemes

Edge authentication is now **implemented** (opt-in API-key with 401/403, `securitySchemes` + `securityRequirements`
declared on the card, and webhook authentication — see [Implemented](./a2a-implemented.md) §7). OAuth2 / OIDC /
mutual-TLS are declared spec-shaped but not enforced in-process — see [Partial](./a2a-partial.md) §7. Nothing in
this section remains absent.

## 8. Extensions mechanism

| Feature                              | Status          | What's missing                                                                    | What it would unlock if built                                                                                                             |
| ------------------------------------ | --------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Extension negotiation / opt-in       | Not implemented | No request-time negotiation (in-process, the router always knows the extensions). | Clients opting into specific extensions per request (via`A2A-Extensions`), so an agent tailors behaviour to what the client supports.   |
| Required-extension enforcement error | Not implemented | `AgentExtension.required` exists (default false) but is never enforced.         | Returning`ExtensionSupportRequiredError` when a client lacks a required extension — making `required: true` actually mean something. |

## 9. Error handling

| Feature                   | Status          | What's missing                                                                                | What it would unlock if built                                                                                                                  |
| ------------------------- | --------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| A2A standard error types  | Not implemented | None of the nine named errors (`TaskNotFoundError` … `VersionNotSupportedError`) exist.  | Programmatic error handling — clients branching on`TaskNotFound` vs `UnsupportedOperation`, etc.                                          |
| Version-negotiation error | Not implemented | No protocol-version handling.                                                                 | Rejecting an unsupported version cleanly (`VersionNotSupportedError`, `-32009`) instead of failing opaquely.                               |
| JSON-RPC error codes      | By design       | No JSON-RPC envelope, so no JSON-RPC error objects; in-process calls raise Python exceptions. | JSON-RPC`-32xxx` error objects — only relevant if a JSON-RPC binding is added; raising Python exceptions in-process is the intended design. |
