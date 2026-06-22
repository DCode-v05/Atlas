# A2A Compliance

## What this document covers

A2A (Agent-to-Agent) is an open protocol that defines how independent AI agents describe themselves, send each
other messages, and track work as tasks. This document records, feature by feature, how much of that protocol
Atlas actually implements.

The key thing to understand up front: Atlas is a **faithful in-process implementation**. All 100 agents run
inside one program and talk to each other through a central in-process router, rather than as separate network
services calling each other over HTTP. Atlas reproduces the A2A **object model and behaviour** (agent cards,
messages, parts, tasks, the task lifecycle, extensions) very closely, but it does **not** put A2A "on the wire"
— there is no network protocol between agents. The only real network connection is between the browser and the
backend (a REST API plus a live event stream for the user interface), and that stream carries Atlas's own event
format, not the A2A streaming format.

## How to read the status column

| Status | Meaning |
|---|---|
| Implemented | Present and working. For agent-to-agent items this means the behaviour is reproduced in-process, noted as "(in-process)". |
| Partial | Present but incomplete, shaped differently from the spec, or defined in the code but never used. |
| Not implemented | Absent. |
| By design | Deliberately not built, because the single-process architecture makes it unnecessary. |

The "Evidence" column points developers at the relevant source file (and, where stable, a line range). Line
numbers are from the time of the audit and may have drifted slightly; the file and symbol name are the reliable
reference.

## 1. Agent Card and discovery

| Feature | Status | Evidence | Note |
|---|---|---|---|
| `AgentCard` object exists | Implemented (in-process) | `atlas/a2a/models.py:95-106` | Faithful core type; built for each of the 100 agents. |
| Card built per agent | Implemented | `atlas/org/generator.py` | Each card carries skills, interfaces, capabilities, and extensions. |
| `name`, `description`, `version`, `provider` | Implemented | `atlas/a2a/models.py:96-100` | `version` defaults to `1.0.0`; `provider` carries organisation and url. |
| `skills` (`AgentSkill`) | Implemented | `atlas/a2a/models.py:64-69` | Has id, name, description, tags, examples. Missing the spec fields `inputModes`, `outputModes`, `security`. |
| `capabilities.streaming` | Partial | `atlas/a2a/models.py:79-82` | Advertised as true on every card, but no A2A streaming actually backs it (see section 5). |
| `capabilities.pushNotifications` | Partial | `atlas/a2a/models.py:81` | Field exists, always false; no push machinery (see section 6). |
| `capabilities.extensions` | Implemented | `atlas/a2a/models.py:82` | Declares the need-to-know and coordination extensions. |
| `capabilities.stateTransitionHistory` | Not implemented | — | Spec field absent. |
| Top-level `extensions` array | Implemented (in-process) | `atlas/a2a/models.py:105` | Carries the org-profile extension; an accessor is provided. |
| `AgentExtension` object | Partial | `atlas/a2a/models.py:72-76` | Uses `uri` + `version` + `metadata`; the spec uses `uri` + `description` + `params` + `required`. |
| `interfaces` (`AgentInterface`) | Partial | `atlas/a2a/models.py:90-93` | Named `interfaces` (spec: `additionalInterfaces`); transport is `in-process`, url `atlas://agent/{id}`. |
| `securitySchemes` | Partial | `atlas/a2a/models.py:103` | Field exists but is always empty. |
| `security` (required schemes) | Not implemented | — | Field absent from the card. |
| Card signing (`signature` / `signatures`) | Partial | `atlas/a2a/models.py:106` | A single optional `signature` (spec uses a list); also always empty. |
| `protocolVersion` | Not implemented | — | Not present on the card. |
| `url` / `preferredTransport` | Not implemented | — | No service url (in-process, so there is no address to publish). |
| `iconUrl`, `documentationUrl` | Not implemented | — | Not present. |
| `defaultInputModes` / `defaultOutputModes` | Not implemented | — | Not present. |
| `supportsAuthenticatedExtendedCard` | Not implemented | — | No extended-card concept. |
| Discovery at `/.well-known/agent-card.json` | Not implemented | — | No such route. Cards are served at the non-standard `GET /api/agents/{id}/card`. |
| Card served over HTTP | Partial | `atlas/api/routes.py` | Reachable through the UI edge as a view-model, not as the raw A2A card at the standard location. |
| `agent/getAuthenticatedExtendedCard` | Not implemented | — | No authentication, no extended card. |

## 2. Core data objects

| Feature | Status | Evidence | Note |
|---|---|---|---|
| `Message` object | Implemented (in-process) | `atlas/a2a/models.py:126-144` | Has messageId, role, parts, contextId, taskId, extensions, referenceTaskIds, metadata. |
| `role` (user / agent) | Implemented | `atlas/a2a/models.py:128` | Matches the A2A wire form. |
| `Part` discriminated union | Implemented | `atlas/a2a/models.py:40-58` | Discriminated on a `kind` field. |
| `TextPart` | Implemented | `atlas/a2a/models.py:40-43` | Used throughout. |
| `DataPart` | Partial | `atlas/a2a/models.py:46-49` | Type defined, but no live path produces one; messages are text-only. |
| `FilePart` | Partial | `atlas/a2a/models.py:52-55` | A loose dictionary, not the spec's structured file-with-bytes / file-with-uri; never produced. |
| `Task` object | Implemented (in-process) | `atlas/a2a/models.py:163-173` | Has id, contextId, status, artifacts, history, metadata. |
| `TaskStatus` | Implemented (in-process) | `atlas/a2a/models.py:150-153` | Has state, message, timestamp. |
| `TaskState` enum values | Implemented | `atlas/a2a/models.py:21-29` | All eight values present: submitted, working, completed, failed, canceled, input-required, auth-required, rejected. |
| State: submitted | Implemented | `atlas/bus/router.py` | Default initial state. |
| State: working | Implemented | `atlas/conversation/orchestrator.py` | Set during processing. |
| State: completed | Implemented | `atlas/conversation/orchestrator.py` | Terminal success. |
| State: failed | Implemented | `atlas/conversation/orchestrator.py` | Terminal error. |
| State: input-required | Implemented | `atlas/conversation/orchestrator.py` | Used by the human-approval flow. |
| State: canceled | Partial | `atlas/a2a/models.py:33` | Defined but never reached (no cancel path; see section 3). |
| State: rejected | Partial | `atlas/a2a/models.py:33` | Defined but never reached. |
| State: auth-required | Partial | `atlas/a2a/models.py:28` | Defined but never used (no auth path). |
| `Artifact` object | Implemented (in-process) | `atlas/a2a/models.py:156-160` | Has id, name, parts, metadata. Missing the spec's `taskId`. |
| `metadata` maps | Implemented | `atlas/a2a/models.py` | Present on all objects; the intent rides in message metadata. |
| `contextId` / `taskId` linkage | Implemented (in-process) | `atlas/a2a/models.py:130-131` | Messages reference their context and task. |
| `referenceTaskIds` | Partial | `atlas/a2a/models.py:133` | Field exists but is never set. |
| `historyLength` on task read | Not implemented | `atlas/api/routes.py` | Task read returns the whole task; no truncation parameter. |

## 3. Remote procedure call (RPC) methods

The A2A method names are listed in `atlas/a2a/methods.py` as documentation of the behaviours the router honours.
They are never dispatched as actual JSON-RPC strings. The router exposes equivalent Python methods, and a few
read operations are reachable over the REST edge.

| Method | Status | Evidence | Note |
|---|---|---|---|
| `message/send` | Implemented (in-process) | `atlas/bus/router.py:173-228` | The single in-process message path (records metrics, emits events, appends to history). Not a JSON-RPC call. |
| `message/stream` | Not implemented | `methods.py` (name only) | No streamed task or status events to a client. |
| `tasks/get` | Partial | `atlas/api/routes.py` | An equivalent REST read exists; not the A2A method and not over JSON-RPC. |
| `tasks/list` | Partial | `atlas/api/routes.py` | An equivalent REST list exists; no filtering or pagination. |
| `tasks/cancel` | Not implemented | `methods.py` (name only) | No cancel path. |
| `tasks/resubscribe` | Not implemented | — | Not present. |
| `tasks/pushNotificationConfig/*` | Not implemented | — | Not present (see section 6). |
| `agent/getAuthenticatedExtendedCard` | Not implemented | — | No authentication or extended card. |
| `agent/card` (non-spec helper) | Partial | `methods.py` | Atlas-specific; surfaced as a REST read, not a standard A2A method. |

## 4. Transports

| Feature | Status | Evidence | Note |
|---|---|---|---|
| JSON-RPC 2.0 envelope between agents | By design | `atlas/a2a/methods.py` | Agents dispatch via Python in one process, not as JSON-RPC over a socket. |
| gRPC binding | Not implemented | — | No gRPC service. |
| HTTP+JSON `/v1/...` binding | Partial | `atlas/api/routes.py` | A REST surface exists under `/api/...`, shaped for the UI, not the spec's `/v1/...` binding. |
| Transport negotiation | Not implemented | `atlas/org/generator.py` | Interfaces declare `in-process`; no negotiation or alternate transports. |
| `A2A-Version` / `A2A-Extensions` headers | Not implemented | — | No version or extension headers. |
| Multi-transport equivalence | By design | — | Only the in-process transport exists, so there is nothing to make equivalent. |

## 5. Streaming

| Feature | Status | Evidence | Note |
|---|---|---|---|
| Server-Sent Events to the browser | Implemented | `atlas/api/routes.py:182-208` | A real event stream with keep-alives. This is the UI edge, not A2A. |
| Atlas event contract | Implemented | `atlas/events/schema.py` | The canonical real-time schema the frontend mirrors. |
| A2A streaming (`message/stream`) | Not implemented | `methods.py` (name only) | No A2A streaming method; a client cannot stream a task. |
| `TaskStatusUpdateEvent` | Not implemented | — | Atlas emits its own `task.state` event, not the A2A shape. |
| `TaskArtifactUpdateEvent` | Not implemented | — | No artifact-update streaming event. |
| Ordered-event / final-flag guarantee | Not implemented | — | No A2A `final` semantics. |
| `capabilities.streaming = true` honoured | Partial | `atlas/org/generator.py` | Advertised on every card with no A2A streaming behind it. |

## 6. Push notifications (webhooks)

| Feature | Status | Evidence | Note |
|---|---|---|---|
| `PushNotificationConfig` object | Not implemented | — | Not defined. |
| Webhook registration and delivery | Not implemented | — | No outbound webhook machinery. |
| `pushNotificationConfig/*` methods | Not implemented | — | None implemented (see section 3). |
| `capabilities.pushNotifications` | Partial | `atlas/a2a/models.py:81` | The flag exists, always false; it honestly advertises "no push". |
| `PushNotificationNotSupportedError` | Not implemented | — | No error surfaced. |

## 7. Authentication and security schemes

| Feature | Status | Evidence | Note |
|---|---|---|---|
| `securitySchemes` on the card | Partial | `atlas/a2a/models.py:103` | The field exists but is always empty. |
| API-key / HTTP / OAuth2 / OIDC / mTLS schemes | Not implemented | — | No scheme types modelled. |
| `security` (required schemes) | Not implemented | — | Field absent (see section 1). |
| Authenticated requests, 401 / 403 handling | Not implemented | `atlas/api/routes.py` | The UI edge has no auth; in-process agents need none. |
| Webhook authentication | Not implemented | — | No webhooks (see section 6). |

A clarification: Atlas's need-to-know system (the owner's share/redact/deny/escalate decision, followed by the
deterministic Policy Engine review) is an application-level **authorisation** layer carried inside messages. It
is not the same thing as A2A transport-level **authentication**, and is not counted as such here.

## 8. Extensions mechanism

| Feature | Status | Evidence | Note |
|---|---|---|---|
| Extension URIs declared | Implemented (in-process) | `atlas/a2a/extensions.py` | Three URIs: org-profile, need-to-know, coordination. |
| Extensions declared on the card | Implemented | `atlas/org/generator.py` | Org-profile at top level; the other two in capabilities. |
| Extension data attached to messages | Implemented (in-process) | `atlas/bus/router.py:189-203` | The need-to-know URI is added to the message; the intent goes in metadata. |
| Org concepts kept out of core types | Implemented | `atlas/org/ext_models.py` | Core protocol types carry no org fields; everything attaches via extensions, matching the spec's intent. |
| Extension negotiation header | Not implemented | — | No request-time negotiation (in-process, the router always knows the extensions). |
| Required-extension enforcement error | Not implemented | — | Not present. |
| `AgentExtension` field shape | Partial | `atlas/a2a/models.py:72-76` | Diverges from the spec shape (see section 1). |

## 9. Error handling

| Feature | Status | Evidence | Note |
|---|---|---|---|
| JSON-RPC error codes | By design | — | No JSON-RPC envelope, so no JSON-RPC error objects; in-process calls raise Python exceptions. |
| A2A standard error types | Not implemented | — | None of the named A2A error types exist. |
| HTTP status mapping on the REST edge | Partial | `atlas/api/routes.py` | The UI edge uses standard HTTP errors (400 / 404 / 503), not the A2A error model. |
| Version-negotiation error | Not implemented | — | No version handling (see section 4). |

## Summary

| Section | Implemented | Partial | Not implemented | By design |
|---|--:|--:|--:|--:|
| 1. Agent Card and discovery | 6 | 7 | 9 | 0 |
| 2. Core data objects | 16 | 6 | 1 | 0 |
| 3. RPC methods | 1 | 3 | 8 | 0 |
| 4. Transports | 0 | 1 | 3 | 2 |
| 5. Streaming | 2 | 1 | 4 | 0 |
| 6. Push notifications | 0 | 1 | 4 | 0 |
| 7. Authentication and security | 0 | 1 | 4 | 0 |
| 8. Extensions mechanism | 4 | 1 | 2 | 0 |
| 9. Error handling | 0 | 1 | 2 | 1 |
| Total | 29 | 22 | 37 | 3 |

In one sentence: Atlas faithfully reproduces the A2A object model and core behaviour in-process — agent cards,
messages, parts, tasks, the full set of task states, the task lifecycle, the send-message path, and the
extensions mechanism — but it does not put A2A on a network wire. The absent pieces are the network-level
features (JSON-RPC, gRPC, the standard REST binding, well-known-URL discovery, A2A streaming, push
notifications, and security schemes); three of these (a JSON-RPC envelope between agents, multi-transport
equivalence, and JSON-RPC error objects) are intentional non-goals of running everything in one process.
