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
| `capabilities.stateTransitionHistory`        | Not implemented | Nothing — this 0.x flag was**removed** in v1.0.0.                          | Nothing to build: it is no longer a spec feature. Listed only so the removal is on record.                                                                 |

> Now implemented (moved to [Implemented](./a2a-implemented.md) §1): `capabilities.extendedAgentCard`, `GetExtendedAgentCard`, `protocolVersion`, `url` / `preferredTransport`, discovery at `/.well-known/agent-card.json`, and `iconUrl` / `documentationUrl` / `defaultInputModes` / `defaultOutputModes`.

## 2. Core data objects

`historyLength` on task read is now **implemented** (moved to [Implemented](./a2a-implemented.md) §3) — `GetTask`
truncates `history` to the last N messages. Nothing in this section remains absent.

## 3. RPC methods

| Feature                                                            | Status          | What's missing                                                    | What it would unlock if built                                                                                                                          |
| ------------------------------------------------------------------ | --------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Send Streaming Message (`SendStreamingMessage`)                  | Not implemented | No streamed task/status events to a client (Atlas streams an *existing* task via `SubscribeToTask`, but not a brand-new send). | Real-time A2A streaming on the initial send so an external client watches a task unfold from the first message — the agent-to-agent analogue of the browser SSE. |

> Now implemented (moved to [Implemented](./a2a-implemented.md) §3): Cancel Task (`tasks/cancel`), Subscribe to Task (`SubscribeToTask`), Get Extended Agent Card (`GetExtendedAgentCard`).

## 4. Transports

| Feature                                                 | Status          | What's missing                                                        | What it would unlock if built                                                                                                                                    |
| ------------------------------------------------------- | --------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| gRPC binding                                            | Not implemented | No gRPC service (v1.0.0 defines a full`A2AService`).                | A high-performance binary transport for agents that prefer gRPC — one of the three spec bindings.                                                               |
| Transport negotiation                                   | Not implemented | Interfaces only declare`in-process`; no negotiation.                | Clients picking among multiple transports an agent offers — a prerequisite is having more than one real transport.                                              |
| `tenant` routing identifier                           | Not implemented | No`tenant` field on requests or interfaces.                         | Serving many agents behind one endpoint and routing by tenant — relevant only if Atlas ever fronts agents over a shared external endpoint.                      |
| JSON-RPC 2.0 envelope between agents                    | By design       | Agents dispatch via Python in one process, not JSON-RPC over sockets. | Putting agents on real sockets. Deliberately avoided to keep 100 agents coherent in one process — only worth it if Atlas ever federates across processes/hosts. |
| Multi-transport equivalence                             | By design       | Only the in-process transport exists.                                 | Guaranteeing identical behaviour across transports — moot until there is more than one transport; a non-goal by construction.                                   |

> Now implemented (moved to [Implemented](./a2a-implemented.md) §4/§8/§9): the `A2A-Version` / `A2A-Extensions` **service parameters** — per-request version + extension negotiation on the `/v1` binding.

## 5. Streaming

| Feature                                                        | Status          | What's missing                                                                                                | What it would unlock if built                                                                                       |
| -------------------------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Send Streaming Message (`SendStreamingMessage` / `message/stream`) | Not implemented | The *initial-send* streaming method — Atlas streams an **existing** task via `SubscribeToTask` (now implemented), but a brand-new send does not stream. | A client streaming a task from its very first message, not only re-attaching to one already running. |

> Now implemented (moved to [Implemented](./a2a-implemented.md) §5): `SubscribeToTask` (per-task streaming that honours `capabilities.streaming`), the `StreamResponse` wrapper, `TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent`, and the ordered-event / final-flag (terminal-close) guarantee.

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

Both extension items are now **implemented** (moved to [Implemented](./a2a-implemented.md) §8): request-time
extension negotiation via the `A2A-Extensions` header (activated extensions echoed back), and required-extension
enforcement (`ExtensionSupportRequiredError` when a client lacks the required need-to-know extension). Nothing in
this section remains absent.

## 9. Error handling

| Feature                   | Status          | What's missing                                                                                | What it would unlock if built                                                                                                                  |
| ------------------------- | --------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| JSON-RPC error codes      | By design       | No JSON-RPC envelope, so no JSON-RPC error objects; in-process calls raise Python exceptions. | JSON-RPC`-32xxx` error objects — only relevant if a JSON-RPC binding is added; raising Python exceptions in-process is the intended design. |

> Now implemented (moved to [Implemented](./a2a-implemented.md) §9): the **named A2A error types** (JSON-RPC codes, mapped to an HTTP status + a spec-shaped error body) and the **version-negotiation error** (`VersionNotSupportedError`).
