# A2A Features Explained

This is a plain-language companion to `a2a.md`. That document audits, feature by feature, how much of
the A2A protocol Atlas implements; it assumes you already know what each feature is. This document
fills that gap: it walks through every section and explains, in detail, **what each A2A feature
actually is and why it exists**, then **how Atlas handles it and why**.

Read one fact first, because it explains almost everything below. A2A (Agent-to-Agent) is an open
protocol that lets independent AI agents describe themselves, message each other, and track work as
tasks — normally as separate network services calling each other over HTTP. Atlas instead runs all 100
agents inside one program and has them talk through a central in-process router. So Atlas reproduces
A2A's **objects and behaviour** faithfully, but it does not put A2A "on the wire": there is no network
protocol between agents. Wherever a feature is about the *network* rather than the *behaviour*, you will
see it marked absent or "by design" — and that is the reason.

Each feature carries its audit status: **Implemented** (present and working), **Partial** (present but
incomplete or shaped differently from the spec), **Not implemented** (absent), or **By design**
(deliberately left out because a single process makes it meaningless).

---

## 1. Agent Card and discovery

The agent card is A2A's machine-readable "business card." It is usually the very first thing one agent
fetches about another, and it answers several questions at once: who is this agent, what can it do,
where do I reach it, what protocol features does it support, and how do I authenticate? "Discovery" is
the separate act of *finding* that card in the first place. This section is where Atlas diverges most
from the spec, because discovery and reachability are inherently network ideas, and Atlas has no
network between agents.

**AgentCard object** *(Implemented, in-process).* The card is the single structured document that
represents an agent to everyone else. In real A2A each agent serves its own card so a stranger can
decide whether and how to talk to it. Atlas builds a faithful card object for each of its 100 agents at
startup; the only difference is that the cards live in memory and are read in-process, rather than
served from 100 separate web servers.

**Card built per agent** *(Implemented).* A2A expects every agent to have its own distinct card, not a
shared template, because each agent has different skills, seniority, and position. Atlas's org generator
produces one card per agent deterministically from the seed, each carrying that agent's own skills,
interfaces, capabilities, and extension declarations — so all 100 are individually and correctly
described.

**name, description, version, provider** *(Implemented).* These are the basic identity fields: a
human-readable name, a sentence describing the agent, a version string for the card itself, and a
"provider" block naming the organisation that operates the agent. Atlas populates all of them; the
version defaults to `1.0.0`, and the provider carries the organisation name and a url.

**skills (AgentSkill)** *(Implemented).* Skills are the heart of discovery: a list of things the agent
can actually do, each with an id, a name, a description, searchable tags, and usage examples. Other
agents match against these tags to decide who is the right person for a job. Atlas gives every agent a
realistic set of skills with controlled-vocabulary tags (this is exactly what the router scores against
when routing a prompt). It omits three finer per-skill fields the spec allows — `inputModes`,
`outputModes`, and a per-skill `security` block — which describe the media types and auth a single skill
needs.

**capabilities.streaming** *(Partial).* This is a yes/no flag advertising that the agent can stream
partial results back as they are produced, rather than making the caller wait for a complete answer.
Atlas sets it to `true` on every card, but there is no real A2A streaming behind it — the only live
stream in the system goes to the browser in Atlas's own format (see section 5). The flag is therefore
honest about intent but overstates what is actually backed, which is why it is only Partial.

**capabilities.pushNotifications** *(Partial).* A yes/no flag advertising that the agent can call a
client back at a webhook URL when something happens, instead of holding a connection open. Atlas leaves
it `false` on every card — an honest "I don't do push" — because no webhook machinery exists (see
section 6).

**capabilities.extensions** *(Implemented).* This is the list, inside the capabilities block, where an
agent declares which optional, non-standard protocol extensions it understands, each named by a URI.
It is A2A's official way to advertise custom behaviour. Atlas uses it to declare its need-to-know and
coordination extensions, so a reader of the card knows the agent speaks those "dialects."

**capabilities.stateTransitionHistory** *(Not implemented).* A flag saying the agent can replay the full
history of a task's state changes to a client that asks. Atlas does not model this field at all; tasks
keep a message history, but there is no separate replayable state-transition log exposed through the
card.

**Top-level extensions array** *(Implemented, in-process).* Separate from `capabilities.extensions`,
Atlas's card also has an `extensions` list at the very top level. This is an Atlas addition (the spec's
canonical home for extensions is inside capabilities). Atlas uses it to carry the org-profile extension
— the dept/role/clearance/reports-to data — and provides an accessor to read it back.

**AgentExtension object** *(Partial).* This is the little object that describes one extension entry. The
A2A spec shape is `uri` + `description` + `params` + `required` (the last flag letting an agent demand
that callers honour the extension). Atlas's version uses `uri` + `version` + `metadata` instead — it
carries the same idea but with different field names and no "required" flag, so it is shaped
differently from the spec.

**interfaces (AgentInterface)** *(Partial).* In A2A this lists the endpoints and transports at which an
agent can be reached — the addresses you actually dial. Atlas declares an interface, but the transport
is `in-process` and the "address" is a symbolic `atlas://agent/{id}` rather than a real network URL; it
also names the field `interfaces` where the spec calls it `additionalInterfaces`. So the concept is
present but it points inward, not at the network.

**securitySchemes** *(Partial).* This is where an agent lists the authentication methods it accepts
(API keys, OAuth2, and so on), so a caller knows how to present credentials. Atlas keeps the field on
the card but always leaves it empty, because in-process agents do not authenticate each other.

**security (required schemes)** *(Not implemented).* A companion to the above: it states which of the
declared schemes a caller *must* satisfy to be allowed in. Atlas omits it entirely — there is nothing to
require when there is no authentication.

**Card signing (signature / signatures)** *(Partial).* A cryptographic signature over the card lets a
reader verify it is genuine and has not been tampered with — important when cards travel across an
untrusted network. Atlas has a single optional `signature` field (the spec allows a list of signatures)
and always leaves it empty, since cards never leave the process.

**protocolVersion** *(Not implemented).* A string stating which version of the A2A protocol the card
conforms to, so a client can check compatibility. Atlas does not put this on the card.

**url / preferredTransport** *(Not implemented).* The agent's primary service address and the transport
it prefers to be called over. Atlas omits both, because in-process there is simply no network address to
publish.

**iconUrl, documentationUrl** *(Not implemented).* Optional links to an icon for the agent and to
human-readable documentation about it — presentation niceties for catalogues and UIs. Atlas does not
include them.

**defaultInputModes / defaultOutputModes** *(Not implemented).* The default media types (for example
plain text or JSON) the agent accepts as input and returns as output, when a skill does not say
otherwise. Atlas does not declare these; in practice everything it exchanges is text.

**supportsAuthenticatedExtendedCard** *(Not implemented).* A flag saying that, after a caller
authenticates, a fuller version of the card becomes available (perhaps revealing more skills or
endpoints). Atlas has no authentication and no extended card, so the concept does not apply.

**Discovery at /.well-known/agent-card.json** *(Not implemented).* A2A's convention is that an agent
publishes its card at a standard well-known URL so others can find it automatically just from the
agent's domain. Atlas has no such route; cards are reachable only through the non-standard
`GET /api/agents/{id}/card` used by the UI.

**Card served over HTTP** *(Partial).* Whether the card is reachable over the network at all. In Atlas
it is — but as a UI-shaped view-model at that non-standard path, not as the raw A2A card document at the
standard location, so it counts as partial.

**agent/getAuthenticatedExtendedCard** *(Not implemented).* The protocol method a client would call,
after authenticating, to retrieve that extended card. With no auth and no extended card in Atlas, the
method does not exist.

## 2. Core data objects

These are the nouns of the protocol: the messages agents send, the parts each message is built from,
and the tasks that track a unit of work from creation to completion. This is the layer Atlas reproduces
most faithfully, because it is about *behaviour and structure*, not the network — and it is where the
genuinely interesting agent-to-agent communication lives.

**Message object** *(Implemented, in-process).* A message is one turn of communication between two
parties. It carries a message id, a role (who is speaking), one or more content parts, links back to the
conversation and task it belongs to, any extension data, and a free-form metadata bag. Atlas models all
of this faithfully and routes every agent-to-agent message through it.

**role (user / agent)** *(Implemented).* Each message is tagged as coming from the user side or from an
agent, so the receiver can tell who is speaking. Atlas matches the A2A form exactly.

**Part discriminated union** *(Implemented).* Rather than being a blob of text, a message's content is a
list of typed "parts," and each part is tagged with a `kind` field so the receiver knows how to
interpret it (text vs structured data vs file). Atlas implements this tagged-union structure.

**TextPart** *(Implemented).* The simplest part type: a chunk of plain text. This is what Atlas agents
use for everything they say to one another.

**DataPart** *(Partial).* A part that carries structured JSON data instead of prose — useful for passing
machine-readable payloads between agents. Atlas defines the type, but nothing in the running system
actually produces one; in practice all messages are text, with any shared values appended as text.

**FilePart** *(Partial).* A part that carries a file, either as inline bytes or as a URI pointing to the
file. The spec gives this a precise structure; Atlas defines it only loosely and never produces one,
since the demonstrator does not exchange files.

**Task object** *(Implemented, in-process).* A task is the record of a unit of work: its id, the
conversation (context) it belongs to, its current status, any artifacts it produced, and its message
history. Tasks are how A2A tracks long-running or multi-step work. Atlas models tasks faithfully and
drives every prompt and cron goal through one.

**TaskStatus** *(Implemented, in-process).* The status sub-object captures a task's current state plus
an optional explanatory message and a timestamp. Atlas includes all of it.

**TaskState enum values** *(Implemented).* A2A defines a fixed vocabulary of states a task can be in;
using a closed set keeps every implementation consistent about what "done" or "waiting" means. Atlas
defines all eight values (the next entries explain each), which is why this scores as fully implemented.

**State: submitted** *(Implemented).* The task has been created and accepted, but work has not started
yet. In Atlas this is the default initial state the router assigns.

**State: working** *(Implemented).* The task is actively being processed. Atlas sets this while the
agent is reasoning, asking others, and assembling its answer.

**State: completed** *(Implemented).* A terminal success state: the work finished and produced a result.
Atlas marks tasks completed when the conversation resolves.

**State: failed** *(Implemented).* A terminal error state: the task ended without succeeding. Atlas uses
it for the error path.

**State: input-required** *(Implemented).* A pause state meaning the task cannot continue until someone
provides input. This is the linchpin of Atlas's human-in-the-loop flow: when a sensitive share needs
the operator's approval, the task parks at input-required until the operator answers, then resumes.

**State: canceled** *(Partial).* The state a task lands in when someone cancels it mid-flight. Atlas
defines the value but never reaches it, because there is no cancel path (see `tasks/cancel` in section
3).

**State: rejected** *(Partial).* The state for a request that was refused outright rather than worked.
Atlas defines it but never transitions a task into it.

**State: auth-required** *(Partial).* A pause state meaning the task needs authentication before it can
continue. Atlas defines the value but never uses it, since there is no authentication layer.

**Artifact object** *(Implemented, in-process).* An artifact is a concrete output a task produces — a
named bundle of parts, with its own id and metadata — as opposed to the conversational messages. Atlas
models artifacts, though it omits the spec's `taskId` back-reference that links an artifact to its task.

**metadata maps** *(Implemented).* Most A2A objects carry a free-form key/value `metadata` bag for
data that does not fit a defined field. Atlas uses this deliberately: the **intent** an agent attaches to
a request (its motivation, purpose, and declared scope) rides in the message metadata.

**contextId / taskId linkage** *(Implemented, in-process).* Every message points back to the context
(the overall conversation) and the task it belongs to, so related messages can be grouped and followed.
Atlas sets both links, which is what lets the UI reconstruct whole threads.

**referenceTaskIds** *(Partial).* A field letting a message point at *other* related tasks — useful for
expressing that one piece of work follows from another. Atlas has the field but never sets it.

**historyLength on task read** *(Not implemented).* When reading a task, a client can ask for only the
last N history entries instead of the whole thing, to keep responses small. Atlas always returns the
complete task with no truncation option.

## 3. Remote procedure call (RPC) methods

These are the named operations one agent invokes on another — send a message, read a task, cancel a
task, and so on. In real A2A they are dispatched as JSON-RPC calls over the network. Atlas lists the
method *names* as documentation of the behaviours its router honours, but it never sends them as
JSON-RPC strings; instead the router exposes equivalent Python methods in-process, and a few read
operations are surfaced over the REST edge for the UI.

**message/send** *(Implemented, in-process).* The core operation of the whole protocol: deliver a
message to another agent. Atlas's single in-process message path reproduces its behaviour exactly — it
records metrics, emits events, and appends to history — so the *semantics* are faithful even though it
is a Python call, not a JSON-RPC request over a socket.

**message/stream** *(Not implemented).* A variant of send where, instead of one reply, the caller
receives a live stream of updates as the task progresses. Only the name is documented in Atlas; nothing
streams task progress to a client.

**tasks/get** *(Partial).* Read a single task by its id. Atlas offers an equivalent read over its REST
edge, but it is not the standard A2A method and not carried over JSON-RPC.

**tasks/list** *(Partial).* List the tasks that exist. Atlas exposes a REST list, but without the
filtering or pagination a full implementation would provide.

**tasks/cancel** *(Not implemented).* Ask the agent to stop a running task. Atlas has no cancel path,
which is also why the `canceled` task state is never reached.

**tasks/resubscribe** *(Not implemented).* Re-attach to a task's update stream after a client
disconnected and reconnected, so it can catch up. Atlas does not implement it (there is no task stream
to resubscribe to).

**tasks/pushNotificationConfig/\*** *(Not implemented).* A family of methods to register and manage
where a task should send webhook callbacks. Atlas implements none of them (see section 6).

**agent/getAuthenticatedExtendedCard** *(Not implemented).* Fetch the fuller card that becomes available
after authentication. Absent, because Atlas has neither authentication nor an extended card.

**agent/card (non-spec helper)** *(Partial).* This is not a standard A2A method; it is an Atlas-specific
convenience for reading a card, surfaced as a REST read for the UI. It is listed so the divergence is
documented honestly.

## 4. Transports

A "transport" is the concrete wire format and channel the protocol travels over. A2A supports several
(JSON-RPC, gRPC, plain HTTP+JSON) and, importantly, requires that they all behave equivalently so a
client can pick any of them. Because Atlas runs in one process, most of this section is intentionally
not applicable — there is no wire to choose.

**JSON-RPC 2.0 envelope between agents** *(By design).* The standard request/response wrapper that
carries an A2A call over the network. Atlas's agents invoke each other as Python methods within one
process, so there is no envelope at all — a deliberate non-goal of the single-process design, not a
gap.

**gRPC binding** *(Not implemented).* An alternative high-performance, binary transport some A2A
deployments use. Atlas runs no gRPC service.

**HTTP+JSON /v1/... binding** *(Partial).* The spec's REST-style transport, with a defined `/v1/...`
URL layout. Atlas does have an HTTP+JSON surface, but it lives under `/api/...` and is shaped for the
user interface, not to match the spec's binding — so the idea is present but not conformant.

**Transport negotiation** *(Not implemented).* The mechanism by which a caller and an agent agree on
which transport to use when several are available. Atlas declares only an in-process interface, so there
is nothing to negotiate.

**A2A-Version / A2A-Extensions headers** *(Not implemented).* HTTP headers that announce, on each
request, which protocol version is in use and which extensions are active. Atlas sends no such headers.

**Multi-transport equivalence** *(By design).* A2A's guarantee that the very same call produces the same
result no matter which transport carries it. With only one (in-process) transport in Atlas, there is
nothing to make equivalent — a deliberate non-goal.

## 5. Streaming

Streaming is how A2A delivers progress incrementally — partial results and status changes as they
happen — so a client does not have to poll and wait. Atlas genuinely does stream in real time, but the
stream runs from the backend to the browser in Atlas's own event format; it is not A2A streaming
between agents. Keeping that distinction clear is the point of this section.

**Server-Sent Events to the browser** *(Implemented).* A real, live event stream (with periodic
keep-alives) from the Atlas backend to the user interface, so the mission-control UI updates the instant
something happens. This is genuine streaming — but it is the UI edge, not A2A.

**Atlas event contract** *(Implemented).* The defined schema of those real-time events, which the
frontend mirrors exactly so the two never drift. It is Atlas's own canonical contract, deliberately not
the same shape as A2A's streaming events.

**A2A streaming (message/stream)** *(Not implemented).* The actual A2A method that streams a task's
updates to a client. Only the name is documented; an outside client cannot stream a task from Atlas.

**TaskStatusUpdateEvent** *(Not implemented).* A2A's standard event meaning "this task changed state."
Atlas emits its own `task.state` event instead, which carries the same idea in a different shape, so the
A2A event type itself is absent.

**TaskArtifactUpdateEvent** *(Not implemented).* A2A's standard event meaning "this task produced a new
artifact." Atlas has no equivalent streaming event for artifacts.

**Ordered-event / final-flag guarantee** *(Not implemented).* A2A promises that streamed events arrive
in order and that a `final` flag marks the last event of a stream, so a client knows when it is done.
Atlas's stream has no such `final` semantics.

**capabilities.streaming = true honoured** *(Partial).* This is the consistency check between the card
and reality: does the streaming flag actually correspond to streaming behaviour? In Atlas it is
advertised `true` on every card with no A2A streaming behind it, so the flag and the behaviour do not
match.

## 6. Push notifications (webhooks)

Push notifications let an agent call a client back at a registered webhook URL when something of
interest happens — especially valuable for long-running tasks, where keeping a connection open the whole
time is impractical. Atlas now **implements** this at its external edge: a client registers a webhook for a
task, and Atlas POSTs a status update to it whenever the task changes state (alongside the browser event
stream it already had).

**PushNotificationConfig object** *(Implemented).* The configuration object recording where a callback
should be sent and how (the URL, an opaque validation token, any authentication). Atlas defines
`PushNotificationConfig` and `TaskPushNotificationConfig` as spec-shaped types.

**Webhook registration and delivery** *(Implemented).* A small subsystem (`atlas/push`) subscribes to the
same event broker that feeds the browser and, on every task-state change, POSTs a spec-shaped status update
to each webhook registered for that task — best-effort, on the single event loop. This is the
server-to-server delivery the spec is about, and it reuses the Router's event stream rather than bypassing it.

**pushNotificationConfig/\* methods** *(Implemented).* Create / read / list / delete the callback
configurations, exposed over the REST edge at `/api/tasks/{id}/push-notification-configs` — the control
plane a client uses to manage its own webhooks per task.

**capabilities.pushNotifications** *(Implemented).* The card flag advertising whether the agent supports
push. Now that delivery is real the flag is set `true` and is honest — the advertisement matches the
behaviour.

**PushNotificationNotSupportedError** *(Not implemented — moot).* The error an agent returns when it
*cannot* do push. Atlas now can, so this refusal never applies and is correctly absent.

## 7. Authentication and security schemes

This section is about transport-level security: proving *who a caller is* before letting them act, using
standard schemes such as API keys, OAuth2, OpenID Connect, or mutual TLS. Atlas's agents talk in-process
(nothing to authenticate between them), but its **one real socket — the browser/API edge — can now be
gated**, so this section is no longer "not applicable": Atlas declares the schemes on the card and enforces
an API key at the edge.

**securitySchemes on the card** *(Implemented).* The card's list of authentication methods the agent
accepts. Every card now declares the five A2A scheme objects (apiKey / http-bearer / oauth2 / oidc / mtls)
rather than an empty map, and the apiKey scheme is the one actually enforced.

**API-key / HTTP bearer schemes** *(Implemented)* — and **OAuth2 / OIDC / mTLS** *(Partial, declared only).*
All five scheme types are now modelled spec-shaped. API-key (and the equivalent HTTP bearer) are enforced
at the edge; OAuth2, OpenID Connect, and mutual TLS are declared for external A2A clients but not enforced
in-process — there is no IdP or TLS-terminating transport here to enforce them against.

**securityRequirements (required schemes)** *(Implemented).* The statement of which schemes a caller must
satisfy. The card declares the apiKey scheme as required (`[{apiKey: []}]`), and the edge honours it when a
key is configured.

**Authenticated requests, 401 / 403 handling** *(Implemented).* An opt-in edge guard: set `ATLAS_API_KEY`
and every `/api/*` request (except `/api/healthz`) must present the key — via the X-API-Key header, an
Authorization: Bearer token, or `?key=` for the SSE stream — returning **401** when it is missing and
**403** when it is wrong. Off by default, so the bundled console is unaffected unless a key is set (and then
it is served the key inline).

**Webhook authentication** *(Implemented).* Outbound webhook calls carry the client's registered token and
any bearer credentials, so a receiver can verify a push is genuine.

A clarification worth stating plainly, because it is easy to conflate the two: Atlas's need-to-know
system — the owner agent's share / redact / deny / escalate decision, followed by the deterministic
Policy Engine review — is an application-level **authorisation** layer. It decides *who may see what*, and
it travels inside messages. That is a different concern from transport-level **authentication**, which
proves *who you are*. Atlas now has both: rich in-message authorisation, and opt-in authentication at its
one real edge (the browser/API socket).

## 8. Extensions mechanism

Extensions are A2A's official escape hatch: a sanctioned way to add behaviour the core spec does not
define, each capability named by a URI and declared on the card, without ever polluting the core
`Message`, `Task`, or `AgentCard` types. This matters because it lets a protocol stay small and stable
while still allowing rich domain-specific additions — which is exactly how Atlas layers an entire
organisation (clearance, need-to-know, intent, coordination) on top of plain A2A. This is the section
Atlas scores best on.

**Extension URIs declared** *(Implemented, in-process).* Each extension is identified by a stable URI,
so a reader can recognise it unambiguously. Atlas declares three — `org-profile`, `need-to-know`, and
`coordination` — which together carry all of its organisation-specific behaviour.

**Extensions declared on the card** *(Implemented).* An agent announces which extensions it supports on
its card, so others know what dialects it speaks before interacting. Atlas does this, placing
`org-profile` at the card's top level and `need-to-know` and `coordination` under `capabilities`.

**Extension data attached to messages** *(Implemented, in-process).* Extensions are not only a card
declaration; the extra data they define can ride along with individual messages. Atlas does exactly
this — it stamps the need-to-know extension URI onto a message and puts the request's intent in the
message metadata — which is what makes the need-to-know layer a real part of each exchange rather than
just an advertisement.

**Org concepts kept out of core types** *(Implemented).* The whole point of the extension mechanism is
that custom fields live in extensions, leaving the core protocol types clean. Atlas honours this: the
core A2A objects carry no organisational fields; every org concept attaches through an extension. This
keeps Atlas faithful to A2A's design intent.

**Extension negotiation header** *(Not implemented).* A request-time header through which a caller and
agent can agree which extensions are active for a given exchange. Atlas does not need it in-process —
the router always knows which extensions are in play — so it is absent.

**Required-extension enforcement error** *(Not implemented).* The error an agent should raise when a
caller fails to honour an extension the agent marked as required. Atlas does not model required
extensions, so it never raises this.

**AgentExtension field shape** *(Partial).* The exact fields of an extension descriptor. As covered in
section 1, Atlas's descriptor uses `uri` + `version` + `metadata`, whereas the spec uses `uri` +
`description` + `params` + `required`; the mechanism works, but the object shape diverges.

## 9. Error handling

A2A defines a standard family of error codes and error objects so that failures are reported the same
way everywhere, and a client can react to them programmatically. Atlas, having no JSON-RPC layer, raises
ordinary Python exceptions internally and maps a few of them to HTTP status codes at the UI edge.

**JSON-RPC error codes** *(By design).* The numeric error codes carried inside a JSON-RPC reply. With no
JSON-RPC envelope in Atlas, there are none — internal failures are plain Python exceptions instead. This
is a deliberate consequence of the single-process design, not a missing feature.

**A2A standard error types** *(Not implemented).* The named errors the spec defines (for example
task-not-found or unsupported-operation), so clients can branch on a known type. None of these named
types exist in Atlas.

**HTTP status mapping on the REST edge** *(Partial).* Turning internal failures into HTTP status codes
on the one real network surface — the UI edge. Atlas does this with standard codes (400 for bad input,
404 for not found, 503 when the model is unavailable), but it is ordinary HTTP error handling, not the
A2A error model.

**Version-negotiation error** *(Not implemented).* The error raised when two parties cannot agree on a
protocol version to speak. Atlas does no version handling at all (see section 4), so this never arises.

## Summary: what the totals mean

The audit totals **90 features — 39 Implemented, 21 Partial, 27 Not implemented, and 3 By design** —
matching the summary table in [`a2a.md`](./a2a.md) and the three status-split files
([implemented](./a2a-implemented.md) / [partial](./a2a-partial.md) / [not-implemented](./a2a-not-implemented.md)),
which are the authoritative per-section and per-row source. (This plain-language companion walks the
same features in prose and groups a handful of borderline rows slightly differently — for example the
non-spec top-level `extensions` array, counted here as in-process-implemented but as Partial in the
split — so a manual count of the prose can land a few off; defer to the split files for the exact tally.)

The shape of those numbers is the whole story, and it follows directly from the one fact at the top.
The Implemented entries cluster where A2A describes *objects and behaviour* — agent cards, messages,
parts, tasks, the full set of task states, the message-send path, and the extensions mechanism — all of
which Atlas reproduces faithfully in-process. The Not-implemented entries cluster where A2A describes
the on-the-wire *network* — JSON-RPC, gRPC, the standard REST binding, well-known-URL discovery, A2A
streaming, and the named error types — none of which a single-process system needs; the external-edge
features a single process *can* honour — push notifications (real webhook delivery) and edge
authentication (an opt-in API key) — are now implemented. Partial mostly marks fields that exist but go
unused, or are shaped slightly differently from the spec, and By design marks the three things one
process makes meaningless on purpose: a JSON-RPC envelope between agents, multi-transport equivalence,
and JSON-RPC error objects.

In one sentence: Atlas is a faithful in-process model of A2A's data and behaviour, not a networked A2A
service — and that single design choice explains almost every status in this document.
