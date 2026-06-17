"""
mini-a2a — a tiny, readable implementation of the A2A (Agent-to-Agent) protocol.
===============================================================================

WHY THIS FILE EXISTS
--------------------
A2A is an open protocol that lets independent AI agents talk to each other over
plain HTTP. Google published it in 2025 and it is now a Linux Foundation project.

There is an official `a2a-sdk` on PyPI, but its current 1.x types are generated
from Protocol Buffers, which makes the actual messages on the wire hard to see.
Because this project is a *learning* prototype, we instead implement the A2A
"JSON-RPC binding" ourselves, in this one small file, so you can read every byte.

Everything here matches the real A2A wire format (protocolVersion "0.3.0"):
the field names, the `kind` discriminators, the lowercase task states, the
method names and the Server-Sent-Events streaming shape were all validated
against the official SDK's own data models. An agent built with this file can
therefore talk to a "real" A2A client and vice-versa.

THE 4 IDEAS YOU NEED
--------------------
1. AGENT CARD  - a public JSON file at `/.well-known/agent-card.json` that
                 advertises who an agent is and what it can do (its "skills").
2. MESSAGE     - what a client sends an agent. It has a role ("user") and a
                 list of `parts` (here, text parts).
3. TASK        - the unit of work the agent creates in response. It has a
                 status whose `state` moves submitted -> working -> completed.
4. ARTIFACT    - the output the agent attaches to the task (the answer text).

TWO WAYS TO CALL AN AGENT (JSON-RPC 2.0 over HTTP POST to `/`)
-------------------------------------------------------------
- "message/send"   : ask once, get the finished Task back in one response.
- "message/stream" : ask once, then receive a live stream of Server-Sent Events
                     (submitted -> working -> artifact -> completed) so a UI can
                     show progress as it happens.
"""
from __future__ import annotations

import inspect
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Awaitable, Callable, Literal, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

A2A_PROTOCOL_VERSION = "0.3.0"
# Standardised location of an agent's "business card".
AGENT_CARD_PATH = "/.well-known/agent-card.json"


def _now() -> str:
    """An ISO-8601 UTC timestamp, e.g. 2026-06-17T10:30:00Z."""
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ===========================================================================
# 1. THE DATA MODELS  (these mirror the A2A JSON exactly — camelCase on purpose)
# ===========================================================================
# We keep the Python field names identical to the JSON field names so that what
# you read in this file is exactly what travels over the network.


class AgentSkill(BaseModel):
    """One capability an agent advertises on its Agent Card."""
    id: str
    name: str
    description: str
    tags: list[str] = []
    examples: list[str] = []


class AgentCapabilities(BaseModel):
    """Optional protocol features this agent supports."""
    streaming: bool = True
    pushNotifications: bool = False


class AgentProvider(BaseModel):
    """Who runs/owns the agent (optional)."""
    organization: str
    url: str


class AgentCard(BaseModel):
    """The public description served at /.well-known/agent-card.json."""
    protocolVersion: str = A2A_PROTOCOL_VERSION
    name: str
    description: str
    url: str                       # base URL; the JSON-RPC endpoint is this URL
    version: str = "1.0.0"         # the AGENT's version (not the protocol's)
    preferredTransport: str = "JSONRPC"
    capabilities: AgentCapabilities = AgentCapabilities()
    defaultInputModes: list[str] = ["text/plain"]
    defaultOutputModes: list[str] = ["text/plain"]
    skills: list[AgentSkill] = []
    provider: Optional[AgentProvider] = None


class TextPart(BaseModel):
    """A chunk of text inside a Message or Artifact.
    `kind` is the discriminator A2A uses to tell text/file/data parts apart."""
    kind: Literal["text"] = "text"
    text: str


class Message(BaseModel):
    """What a client sends to an agent (role='user') and what an agent can
    send back inside a status update (role='agent').

    `metadata` is a free-form dict the A2A spec allows on a message. We use it to
    carry a FIPA-ACL-style `performative` ("request"/"inform") and the `intent`
    behind the message — i.e. *why* it's being sent."""
    kind: Literal["message"] = "message"
    role: Literal["user", "agent"]
    parts: list[TextPart]
    messageId: str = Field(default_factory=lambda: _new_id("msg"))
    taskId: Optional[str] = None
    contextId: Optional[str] = None
    metadata: Optional[dict] = None


class Artifact(BaseModel):
    """A tangible output the agent produces (the answer)."""
    artifactId: str = Field(default_factory=lambda: _new_id("art"))
    name: Optional[str] = None
    parts: list[TextPart]


class TaskStatus(BaseModel):
    """The current state of a task, optionally with a human-readable message."""
    state: str                      # see TaskState below for the allowed values
    message: Optional[Message] = None
    timestamp: Optional[str] = None


class Task(BaseModel):
    """The unit of work an agent runs for a client."""
    kind: Literal["task"] = "task"
    id: str
    contextId: str
    status: TaskStatus
    artifacts: list[Artifact] = []
    history: list[Message] = []


class TaskStatusUpdateEvent(BaseModel):
    """A streaming event: 'the task's state changed'. `final=True` marks the
    very last event of the stream (so the client knows it can stop listening)."""
    kind: Literal["status-update"] = "status-update"
    taskId: str
    contextId: str
    status: TaskStatus
    final: bool = False


class TaskArtifactUpdateEvent(BaseModel):
    """A streaming event: 'here is (a piece of) an output artifact'."""
    kind: Literal["artifact-update"] = "artifact-update"
    taskId: str
    contextId: str
    artifact: Artifact
    lastChunk: bool = True


# The official set of task states (lowercase, hyphenated — exactly on the wire).
class TaskState:
    submitted = "submitted"        # received, not started yet
    working = "working"            # in progress
    input_required = "input-required"
    completed = "completed"        # finished successfully
    canceled = "canceled"
    failed = "failed"
    rejected = "rejected"
    unknown = "unknown"


# ---- small helpers to build common objects -------------------------------

def user_text_message(text: str, *, task_id: str | None = None,
                      context_id: str | None = None,
                      metadata: dict | None = None) -> Message:
    """Build a Message a *client* sends to an agent."""
    return Message(role="user", parts=[TextPart(text=text)],
                   taskId=task_id, contextId=context_id, metadata=metadata)


def agent_text_message(text: str, *, task_id: str, context_id: str) -> Message:
    """Build a Message an *agent* attaches to a status update (progress note)."""
    return Message(role="agent", parts=[TextPart(text=text)],
                   taskId=task_id, contextId=context_id)


def text_of(message: dict | None) -> str:
    """Pull the plain text out of an incoming A2A message dict
    (concatenates every text part)."""
    if not message:
        return ""
    parts = message.get("parts", [])
    return "\n".join(p.get("text", "") for p in parts if p.get("kind") == "text").strip()


def _dump(model: BaseModel) -> dict:
    """Serialise a model to plain JSON-able dict, dropping unset fields."""
    return model.model_dump(exclude_none=True)


# ===========================================================================
# 2. THE SERVER SIDE  (turn agent "logic" into a real A2A HTTP server)
# ===========================================================================
# An agent author only writes a single async function:
#       async def logic(user_text: str) -> str
# and this module turns it into a fully compliant A2A server.

class Progress:
    """Yield this from a *streaming* agent handler to emit a 'working' status
    note (e.g. "Calling weather tool…"). Yield the final answer as a plain
    string, last. See `build_agent_app` for the two supported handler styles."""

    def __init__(self, note: str):
        self.note = note


class RequestContext:
    """What the server knows about an incoming A2A call. Handlers that want it
    (like the orchestrator agent, to thread a conversation) declare a 2nd
    parameter: `async def logic(user_text, ctx): ...`. Simple agents ignore it."""

    def __init__(self, *, context_id: str, task_id: str,
                 metadata: dict | None, user_text: str):
        self.context_id = context_id      # the A2A contextId (conversation id)
        self.task_id = task_id
        self.metadata = metadata or {}     # FIPA performative + intent, etc.
        self.user_text = user_text


# A handler ("logic") is EITHER:
#   • simple   : async def logic(text) -> str            (one answer, no notes)
#   • streaming: async def logic(text):                  (narrate progress, then
#                    yield Progress("step 1…"); ...        yield the final text)
#                    yield "the final answer"
#   Either form may take an optional 2nd parameter (ctx: RequestContext).
AgentLogic = Callable[..., object]

# A simple in-memory record of tasks we have produced, so `tasks/get` works.
_TASKS: dict[str, Task] = {}


def _invoke(logic: AgentLogic, ctx: "RequestContext"):
    """Call the handler with 1 or 2 args depending on its signature."""
    wants_ctx = len(inspect.signature(logic).parameters) >= 2
    return logic(ctx.user_text, ctx) if wants_ctx else logic(ctx.user_text)


async def _iter_handler(logic: AgentLogic, ctx: "RequestContext", working_note: str):
    """Run a handler of either style and normalise it into a stream of
    ('working', note) items followed by exactly one ('final', text) item."""
    if inspect.isasyncgenfunction(logic):
        final_text = ""
        async for item in _invoke(logic, ctx):
            if isinstance(item, Progress):
                yield ("working", item.note)
            else:                       # a plain string = the final answer
                final_text = str(item)
        yield ("final", final_text)
    else:
        # simple coroutine: emit one generic 'working' note, then the answer
        yield ("working", working_note)
        answer = await _invoke(logic, ctx)
        yield ("final", str(answer))


def _jsonrpc_result(rpc_id, result: dict) -> dict:
    """Wrap a result in the JSON-RPC 2.0 success envelope."""
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _jsonrpc_error(rpc_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def build_agent_app(card: AgentCard, logic: AgentLogic, *,
                    working_note: str = "Working on it...") -> FastAPI:
    """Create a complete A2A server (a FastAPI app) for one agent.

    It exposes exactly two endpoints, which is all A2A needs:
      GET  /.well-known/agent-card.json   -> the Agent Card (discovery)
      POST /                              -> the JSON-RPC endpoint (the work)
    """
    app = FastAPI(title=card.name)

    @app.get(AGENT_CARD_PATH)
    async def get_agent_card():
        # Discovery: any client can read this to learn the agent's skills.
        return JSONResponse(_dump(card))

    @app.post("/")
    async def jsonrpc_endpoint(request: Request):
        body = await request.json()
        rpc_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        incoming = params.get("message") or {}

        # Honour the contextId the caller sent — this is what threads a multi-turn
        # conversation across calls. Generate one only if absent. Carry metadata
        # (the FIPA performative + intent) through to the handler too.
        ctx = RequestContext(
            context_id=incoming.get("contextId") or _new_id("ctx"),
            task_id=_new_id("task"),
            metadata=incoming.get("metadata"),
            user_text=text_of(incoming),
        )
        task_id, context_id = ctx.task_id, ctx.context_id

        # ---- method 1: synchronous "ask once, get the finished Task" ----
        if method == "message/send":
            final_text, state = "", TaskState.completed
            try:
                async for kind, payload in _iter_handler(logic, ctx, working_note):
                    if kind == "final":
                        final_text = payload
            except Exception as exc:   # a handler error becomes a clean 'failed' task
                final_text = f"_({card.name} could not finish this request: {exc})_"
                state = TaskState.failed
            artifact = Artifact(name="result", parts=[TextPart(text=final_text)])
            task = Task(id=task_id, contextId=context_id,
                        status=TaskStatus(state=state, timestamp=_now()),
                        artifacts=[artifact])
            _TASKS[task_id] = task
            return JSONResponse(_jsonrpc_result(rpc_id, _dump(task)))

        # ---- method 2: streaming "ask once, watch it happen" ----
        if method == "message/stream":
            async def event_stream() -> AsyncIterator[str]:
                # Emit `submitted`, then forward every progress note as a
                # `working` status-update as it happens, then the artifact and
                # a final `completed`. A streaming handler can yield many notes.
                submitted = Task(id=task_id, contextId=context_id,
                                 status=TaskStatus(state=TaskState.submitted, timestamp=_now()))
                yield _sse(_jsonrpc_result(rpc_id, _dump(submitted)))

                try:
                    async for kind, payload in _iter_handler(logic, ctx, working_note):
                        if kind == "working":
                            working = TaskStatusUpdateEvent(
                                taskId=task_id, contextId=context_id,
                                status=TaskStatus(
                                    state=TaskState.working, timestamp=_now(),
                                    message=agent_text_message(payload, task_id=task_id,
                                                               context_id=context_id)),
                            )
                            yield _sse(_jsonrpc_result(rpc_id, _dump(working)))
                        else:  # 'final'
                            artifact = Artifact(name="result", parts=[TextPart(text=payload)])
                            _TASKS[task_id] = Task(
                                id=task_id, contextId=context_id,
                                status=TaskStatus(state=TaskState.completed, timestamp=_now()),
                                artifacts=[artifact])
                            yield _sse(_jsonrpc_result(rpc_id, _dump(
                                TaskArtifactUpdateEvent(taskId=task_id, contextId=context_id,
                                                        artifact=artifact))))
                            yield _sse(_jsonrpc_result(rpc_id, _dump(
                                TaskStatusUpdateEvent(
                                    taskId=task_id, contextId=context_id,
                                    status=TaskStatus(state=TaskState.completed, timestamp=_now()),
                                    final=True))))          # <-- final=True ends it
                except Exception as exc:
                    # A handler error (e.g. an LLM rate limit) becomes a clean
                    # 'failed' end-of-stream instead of crashing the connection.
                    note = f"_({card.name} could not finish this request: {exc})_"
                    art = Artifact(name="error", parts=[TextPart(text=note)])
                    yield _sse(_jsonrpc_result(rpc_id, _dump(
                        TaskArtifactUpdateEvent(taskId=task_id, contextId=context_id, artifact=art))))
                    yield _sse(_jsonrpc_result(rpc_id, _dump(
                        TaskStatusUpdateEvent(
                            taskId=task_id, contextId=context_id,
                            status=TaskStatus(state=TaskState.failed, timestamp=_now()),
                            final=True))))

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    # Stop reverse proxies (e.g. nginx) from buffering the stream:
                    "X-Accel-Buffering": "no",
                },
            )

        # ---- method 3: look up a task we ran earlier ----
        if method == "tasks/get":
            task = _TASKS.get((params or {}).get("id"))
            if task is None:
                return JSONResponse(_jsonrpc_error(rpc_id, -32001, "Task not found"))
            return JSONResponse(_jsonrpc_result(rpc_id, _dump(task)))

        return JSONResponse(_jsonrpc_error(rpc_id, -32601, f"Method not found: {method}"))

    return app


def _sse(payload: dict) -> str:
    """Format one Server-Sent-Events frame. Each frame carries a full JSON-RPC
    response whose `result` is one A2A event. The blank line terminates it."""
    return f"data: {json.dumps(payload)}\n\n"


def run_agent(app: FastAPI, port: int) -> None:
    """Start the agent's web server (blocking). Used by each agent's __main__."""
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


# ===========================================================================
# 3. THE CLIENT SIDE  (how the orchestrator talks TO an agent)
# ===========================================================================


class A2AClient:
    """A minimal A2A client for one remote agent.

    Usage:
        client = A2AClient("http://localhost:8101/")
        card = await client.get_card()              # discovery
        task = await client.send("Tell me about Kyoto")     # blocking
        async for event in client.stream("..."):    # streaming
            ...
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/") + "/"

    async def get_card(self) -> AgentCard:
        """Fetch the agent's Agent Card (the discovery step)."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self.base_url.rstrip("/") + AGENT_CARD_PATH)
            resp.raise_for_status()
            return AgentCard(**resp.json())

    def _request(self, method: str, text: str, *, context_id: str | None = None,
                 metadata: dict | None = None) -> dict:
        """Build the JSON-RPC request body for message/send or message/stream.
        Passing `context_id` threads a conversation; `metadata` carries the
        FIPA-style performative + intent of the message."""
        msg = user_text_message(text, context_id=context_id, metadata=metadata)
        return {
            "jsonrpc": "2.0",
            "id": _new_id("rpc"),
            "method": method,
            "params": {"message": _dump(msg)},
        }

    async def send(self, text: str, *, context_id: str | None = None,
                   metadata: dict | None = None) -> Task:
        """Call `message/send` and get the finished Task back in one response."""
        req = self._request("message/send", text, context_id=context_id, metadata=metadata)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(self.base_url, json=req)
            resp.raise_for_status()
            return Task(**resp.json()["result"])

    async def stream(self, text: str, *, context_id: str | None = None,
                     metadata: dict | None = None) -> AsyncIterator[dict]:
        """Call `message/stream` and yield each A2A event (as a dict) as it
        arrives. Stops after the event with final=True."""
        req = self._request("message/stream", text, context_id=context_id, metadata=metadata)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", self.base_url, json=req) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    frame = json.loads(line[len("data:"):].strip())
                    event = frame.get("result")
                    if event is not None:
                        yield event
