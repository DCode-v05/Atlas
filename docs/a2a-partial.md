# A2A Compliance — Partial

Features that are **present but incomplete** — shaped differently from the spec, or defined in the code but never
exercised. Audited against **A2A v1.0.0**; see [`a2a.md`](./a2a.md) for the version-basis convention and the
Implemented / Not-implemented splits.

Each row is broken into three parts: **what's implemented (and why)**, **what's missing**, and **what completing
it would unlock** — the capability Atlas would gain by finishing the feature, framed against its actual
architecture (in-process bus, single worker, SSE edge, need-to-know + policy engine).

## 1. Agent Card and discovery

| Feature                             | Evidence                      | What's implemented (and why)                                                                                                                                                | What's missing                                                                                                                                      | What completing it would unlock                                                                                                                              |
| ----------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `interfaces` (`AgentInterface`) | `atlas/a2a/models.py:91-93` | Each agent declares an interface with `transport=in-process`, `url=atlas://agent/{id}` — the honest description of the in-process bus.                                 | Spec naming (`supportedInterfaces`) and the per-interface `protocolBinding`, `protocolVersion`, `tenant` fields.                            | Declaring real bindings/versions would let Atlas expose agents over actual transports (HTTP+JSON / gRPC) and negotiate protocol versions.                    |
| Card signing (`signatures`)       | `atlas/a2a/models.py:118`   | An optional `signature` slot exists on the card.                                                                                                                          | The spec uses a**list** `signatures` of `AgentCardSignature` (a JWS over the JCS-canonicalised card); Atlas's is single and always empty. | Real JWS signing lets consumers verify a card is authentic and untampered — essential once cards leave the process.                                         |

> Now implemented (moved to [Implemented](./a2a-implemented.md) §1): the **top-level `extensions` array** is gone — all extensions live under `capabilities.extensions` (spec-valid placement); the **`AgentExtension` shape** now carries `description` + `params`; `capabilities.streaming` is backed by `SubscribeToTask`; and the raw card is served at `/.well-known/agent-card.json` (public/extended tiering).

## 2. Core data objects

All previously-partial core-data items are now **implemented** (moved to [Implemented](./a2a-implemented.md) §2):
`DataPart` and `FilePart` (URL-only `FileWithUri`) are produced in a finalised task's artifact; `referenceTaskIds`
is set from `/api/prompt` (and the binding); the `rejected` state is reached via the binding's `message:send`; and
`auth-required` parks-and-resumes a task on network join. Nothing in this section remains partial.

## 3. RPC methods

| Feature                          | Evidence                        | What's implemented (and why)                                                                                 | What's missing                                                                                                                                                  | What completing it would unlock                                                                                                       |
| -------------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `agent/card` (non-spec helper) | `atlas/a2a/methods.py`        | An Atlas-specific card read `GET /api/agents/{id}/card` exists for the UI.                                  | v1.0.0 has no such method — the standard routes (well-known discovery + `GetExtendedAgentCard`) now exist, so the helper is redundant but still present.       | Retiring the helper in favour of the standard routes (now implemented) removes the non-spec surface.                                  |

> Now implemented (moved to [Implemented](./a2a-implemented.md) §3): **Get Task** (`historyLength` truncation) and **List Tasks** (cursor pagination, `contextId`/`status` filters, `includeArtifacts`, timestamp-desc order).

## 4. Transports

The spec **HTTP+JSON binding** is now **implemented** — a `/v1` colon-verb surface (`POST /v1/message:send`,
`GET /v1/tasks/{id}`, `POST /v1/tasks/{id}:cancel`, `:subscribe`, `GET /v1/card`) any A2A HTTP client can use
directly (see [Implemented](./a2a-implemented.md) §4). The remaining transport gaps (gRPC, multi-transport
negotiation, `tenant` routing) are in [Not-implemented](./a2a-not-implemented.md) §4.

## 5. Streaming

Per-task A2A streaming is now **implemented** — `SubscribeToTask` (`GET /api/tasks/{id}/subscribe`) streams a
task's lifecycle as spec-shaped `StreamResponse` frames (status / message / artifact updates) and closes on a
terminal state with `final: true`, backing the advertised `capabilities.streaming` flag (see
[Implemented](./a2a-implemented.md) §5). The only streaming feature still absent is the *initial-send* method
`SendStreamingMessage` (`message/stream`) — see [Not-implemented](./a2a-not-implemented.md) §5.

## 7. Authentication and security schemes

| Feature | Evidence | What's implemented (and why) | What's missing | What completing it would unlock |
| --- | --- | --- | --- | --- |
| OAuth2 / OIDC / mTLS schemes (declared, not enforced) | `atlas/org/taxonomy.py` | All five A2A scheme types are now declared spec-shaped on every card, and the apiKey/http-bearer schemes are **enforced** at the edge (see [Implemented](./a2a-implemented.md) §7). | OAuth2, OpenID Connect, and mutual-TLS are declared only — there is no IdP or TLS-terminating transport in-process to enforce them against. | Real OAuth2/OIDC/mTLS enforcement once Atlas fronts agents over an actual transport (e.g. the September-Engine binding), authenticating external A2A callers rather than only the operator console. |

## 8. Extensions mechanism

Both previously-partial extension items are now **implemented** (moved to [Implemented](./a2a-implemented.md) §8):
**all** extensions are declared under `capabilities.extensions` (org-profile included, public-stripped), and the
`AgentExtension` field shape carries the spec's `description` + `params` — plus request-time extension negotiation
(`A2A-Extensions`) and required-extension enforcement. Nothing in this section remains partial.

## 9. Error handling

The REST edge's error handling is now **implemented** as the A2A error model (moved to
[Implemented](./a2a-implemented.md) §9): the `/v1` binding maps failures to **named A2A errors** with JSON-RPC
codes and a spec-shaped error body, so external clients can distinguish `TaskNotFound` from `UnsupportedOperation`
programmatically. Nothing in this section remains partial.
