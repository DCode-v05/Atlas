# A2A Compliance — Implemented

The features Atlas implements and that work. For agent-to-agent items, "implemented" means the
behaviour is reproduced **in-process** (no network wire between agents). Audited against **A2A v1.0.0**;
see [`a2a.md`](./a2a.md) for the full version-basis convention and the Partial / Not-implemented splits.

The **Why it's implemented** column explains the role each feature plays in Atlas's actual goal — the
**quality and efficiency of agent communication** (routing, discovery, need-to-know, determinism, the live UI) —
not just that the field exists.

## 1. Agent Card and discovery

| Feature | Evidence | Why it's implemented |
|---|---|---|
| `AgentCard` object exists | `atlas/a2a/models.py:95-106` | Discovery and routing are the whole point of Atlas, and an agent must be self-describing to be found. A faithful card per agent gives the LLM router a directory of all 100 agents (id / name / role / dept / skills) to pick owners from, and is the anchor every other A2A object hangs off. |
| Card built per agent | `atlas/org/generator.py` | The generator materialises one card for every agent deterministically (same `ATLAS_SEED` ⇒ identical company), so discovery is byte-reproducible and each of the 100 agents is independently addressable. |
| `name`, `description`, `version`, `provider` | `atlas/a2a/models.py:96-100` | The minimum identity the routing LLM reads and the mission-control UI renders; without it an agent cannot be described, displayed, or chosen. |
| `skills` (`AgentSkill`) | `atlas/a2a/models.py:64-69` | Skills answer "who can do this": they feed both the LLM router and the deterministic skill-scorer fallback, and their tags seed the org lexicon the scope-gate uses. Senior vs IC skill loadouts are what make execution prompts route down and strategy prompts route up. |
| `capabilities.extensions` | `atlas/a2a/models.py:82` | Atlas's org concepts (need-to-know, coordination) attach via the A2A extensions mechanism; declaring them in `capabilities.extensions` is how an agent advertises that it speaks those extensions — the spec-faithful way to extend without polluting core types. |
| `capabilities.pushNotifications` | `atlas/org/generator.py` | Now advertised **true** and backed by the webhook delivery subsystem (`atlas/push`), so the card honestly says it can push task updates to a registered webhook (see §6). |
| `securitySchemes` | `atlas/org/taxonomy.py`, `atlas/org/generator.py` | Every card now declares the five A2A scheme objects (apiKey / http-bearer / oauth2 / oidc / mtls); the apiKey scheme is the one enforced at the edge, so the field describes real behaviour rather than sitting empty (see §7). |
| `securityRequirements` | `atlas/a2a/models.py:103-104`, `atlas/org/generator.py` | The card declares `[{apiKey: []}]` — the scheme a caller must satisfy — making the agent's auth expectation explicit and enforceable (honoured when `ATLAS_API_KEY` is set). |

## 2. Core data objects

| Feature | Evidence | Why it's implemented |
|---|---|---|
| `Message` object | `atlas/a2a/models.py:126-144` | The unit of every agent↔agent turn. Each router send produces a faithful `Message` whose `extensions` + `metadata` carry the need-to-know intent, so "why I'm asking" travels with the words — central to the communication layer. All eight v1.0.0 fields are present. |
| `role` (user / agent) | `atlas/a2a/models.py:128` | Distinguishes a human/operator-origin turn from an agent-authored turn — needed for task history, attribution, and how the UI renders each side of a conversation. |
| `Part` discriminated union | `atlas/a2a/models.py:40-58` | The content container of a message. Text parts carry every authored message; modelling Part as a union keeps the protocol shape honest and leaves the door open for data/file parts. |
| `TextPart` | `atlas/a2a/models.py:40-43` | Every agent message is natural-language text authored by real Mistral (there are no templates), so `TextPart` is the workhorse that actually moves communication. |
| `Task` object | `atlas/a2a/models.py:163-173` | The stateful unit of work each prompt opens; it carries status, history, and artifacts and is the anchor for the lifecycle, the SSE task events, and the per-context metrics. |
| `TaskStatus` | `atlas/a2a/models.py:150-153` | Bundles `state` + `message` + `timestamp` so the orchestrator can advance a task and the UI can show where it is and why. |
| `TaskState` enum values | `atlas/a2a/models.py:21-29` | The lifecycle vocabulary the orchestrator drives tasks through; the eight functional states make the task machine legible and let terminal vs interrupted states be reasoned about. |
| State: `submitted` | `atlas/bus/router.py` | Reached as the default initial state when the router opens a task — the entry point of every lifecycle. |
| State: `working` | `atlas/conversation/orchestrator.py` | Set while the orchestrator runs discovery and the need-to-know exchange — the "in progress" signal the UI shows live. |
| State: `completed` | `atlas/conversation/orchestrator.py` | The terminal success state, set once the task is finalised — closes the lifecycle and freezes the metrics for that context. |
| State: `failed` | `atlas/conversation/orchestrator.py` | The terminal error state, set when a scenario or greeting raises — makes failures explicit rather than silent. |
| State: `input-required` | `atlas/conversation/orchestrator.py` | The pause used by the human-in-the-loop flow: a sensitive share escalates, the task waits `input-required`, the operator approves/denies, then it resumes. This is how HITL is expressed in pure A2A terms. |
| `Artifact` object | `atlas/a2a/models.py:156-160` | Task outputs (the finalised summary) are stored as artifacts, keeping data output cleanly separate from the conversational `Message` history — exactly the separation the spec intends. |
| `metadata` maps | `atlas/a2a/models.py` | The flexible key-value channel the intent and extension payloads ride in; ubiquitous on every object so org context can attach anywhere without new core fields. |
| `contextId` / `taskId` linkage | `atlas/a2a/models.py:130-131` | Groups all the messages and tasks of one prompt into a single conversation; the SSE stream, threads, groups, and metrics all key off `contextId`, so it is what makes a multi-agent exchange one coherent unit. |

## 3. RPC methods

| Feature | Evidence | Why it's implemented |
|---|---|---|
| Send Message (`SendMessage`, 0.2.x `message/send`) | `atlas/bus/router.py:173-228` | This is the single in-process path **every** agent↔agent message flows through, so discovery, need-to-know extensions, metrics, and event emission cannot be bypassed. It is the heart of the bus, so it is the most faithfully reproduced operation — implemented as a Python call, not a JSON-RPC string. |
| Push-notification configs (`pushNotificationConfig/Set·Get·List·Delete`) | `atlas/api/routes.py` | CRUD over a task's webhook configs (`POST/GET/LIST/DELETE /api/tasks/{id}/push-notification-configs`) — the control plane a client uses to register where task-status updates are delivered (the methods behind §6). |

## 5. Streaming

| Feature | Evidence | Why it's implemented |
|---|---|---|
| Server-Sent Events to the browser | `atlas/api/routes.py:187-208` | The mission-control UI needs live updates as 100 agents talk; SSE is the one **real** socket Atlas opens, carrying Atlas's own event schema (with keep-alives) so the force-graph and panels animate in real time. |
| Atlas event contract | `atlas/events/schema.py` | `schema.py` is the single source of truth the frontend mirrors (`web/src/types.ts`), so backend events and the UI stay in lockstep and drift is caught — the contract that makes the live UI dependable. |

## 6. Push notifications (webhooks)

| Feature | Evidence | Why it's implemented |
|---|---|---|
| `PushNotificationConfig` / `TaskPushNotificationConfig` objects | `atlas/a2a/models.py` | Spec-shaped config types (id / url / token / authentication) modelling a client's webhook registration — the data the push control plane stores against a task. |
| Webhook registration + delivery | `atlas/push/service.py` | The service subscribes to the `EventBroker` and POSTs a spec-shaped task-status update to every webhook registered for a task on each `task.state` change — out-of-band delivery for a disconnected client, the server-to-server counterpart of the browser SSE. Best-effort, on the single event loop, never bypassing the Router (it reads downstream of the broker). |
| `pushNotificationConfig/*` methods | `atlas/api/routes.py` | Set / Get / List / Delete over the REST edge let a client manage its own webhooks per task — the control plane for the delivery above. |
| `capabilities.pushNotifications = true` honoured | `atlas/org/generator.py`, `atlas/push/` | The advertised capability is now backed by real delivery, so the card neither over- nor under-promises — the consistency the spec intends between a flag and behaviour. |

## 7. Authentication and security schemes

| Feature | Evidence | Why it's implemented |
|---|---|---|
| `securitySchemes` on the card | `atlas/org/taxonomy.py`, `atlas/org/generator.py` | Populated with the five A2A scheme objects rather than left empty; the apiKey scheme is enforced, so the field now describes a real authentication option an external caller can use. |
| `securityRequirements` (required schemes) | `atlas/a2a/models.py:103-104`, `atlas/org/generator.py` | The card declares the apiKey scheme as required — the enforcement side of `securitySchemes` — honoured at the edge when a key is configured. |
| Authenticated requests, 401 / 403 handling | `atlas/main.py` | An opt-in edge guard: when `ATLAS_API_KEY` is set, every `/api/*` request (except `/api/healthz`) must present the key — X-API-Key header, `Authorization: Bearer`, or `?key=` for the SSE stream — else **401** (missing) or **403** (wrong). Off by default, so the bundled UI is unaffected unless a key is set (and then it is served the key inline). |
| Webhook authentication | `atlas/push/service.py` | Outbound webhook calls carry the client's registered token (`X-A2A-Notification-Token`) and any bearer credentials, so the receiver can verify a push is genuine and not spoofed. |

## 8. Extensions mechanism

| Feature | Evidence | Why it's implemented |
|---|---|---|
| Extension URIs declared | `atlas/a2a/extensions.py` | Three stable URIs (org-profile, need-to-know, coordination) name Atlas's org extensions — the contract for attaching org data to A2A objects without inventing new core fields. |
| Extension data attached to messages | `atlas/bus/router.py:188-203` | The need-to-know URI is added to `message.extensions` and the intent rides in `metadata` — exactly the spec's extension-point pattern (URI in `extensions`, payload in `metadata` keyed by that URI). This is how a requester's "why" reaches the owner's share decision. |
| Org concepts kept out of core types | `atlas/org/ext_models.py` | Core protocol types carry no org fields; everything (department, clearance, sensitivity, intent) attaches via extensions. This keeps the A2A layer pure and the org layer swappable — the spec's central design intent, honoured. |
| Extension versioning via the URI | `atlas/a2a/extensions.py` | Atlas encodes the version in the URI (`urn:atlas:ext:...:v1`), matching v1.0.0 §4.6.3's guidance to version extensions through the URI (a new URI for a breaking change) — so future changes won't silently break consumers. |
