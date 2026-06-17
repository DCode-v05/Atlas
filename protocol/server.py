"""
protocol/server.py — turn an agent's logic into a real A2A HTTP server.

An agent author writes ONE async function and this module makes it a compliant
A2A server:

    async def logic(user_text) -> str                  # simplest
    async def logic(user_text, ctx) -> str             # wants the request context
    async def logic(user_text, ctx):                   # streaming: narrate, then answer
        yield Progress("thinking…")
        yield "the final answer"

The server exposes exactly what A2A needs:

    GET  /.well-known/agent-card.json   -> the Agent Card (discovery)
    POST /                              -> the JSON-RPC endpoint (the work)

Methods: message/send, message/stream (SSE), tasks/get, tasks/cancel.
A handler may pause by yielding/returning NeedInput(question): the task then
ends in the `input-required` state carrying that question, and the caller
resumes by sending another message on the same contextId.
"""
from __future__ import annotations

import inspect
import json
from typing import AsyncIterator, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from protocol.models import (AGENT_CARD_PATH, AgentCard, Task,
                             TaskArtifactUpdateEvent, TaskStatus,
                             TaskStatusUpdateEvent, agent_text_message,
                             artifact_from, dump, new_id, now_iso, text_of)
from protocol.states import TaskState


class Progress:
    """Yield from a streaming handler to emit a `working` status note."""
    def __init__(self, note: str):
        self.note = note


class NeedInput:
    """Yield/return from a handler to pause the task in `input-required`,
    asking the caller a question."""
    def __init__(self, question: str):
        self.question = question


class RequestContext:
    """Everything the server knows about an incoming call. A handler that wants
    it declares a 2nd parameter: ``async def logic(text, ctx): ...``."""
    def __init__(self, *, context_id: str, task_id: str, message: dict):
        self.context_id = context_id
        self.task_id = task_id
        self.message = message
        self.metadata: dict = message.get("metadata") or {}
        self.reference_task_ids: list = message.get("referenceTaskIds") or []
        self.user_text: str = text_of(message)


AgentLogic = Callable[..., object]
_TASKS: dict[str, Task] = {}          # per-process task store, for tasks/get


def _invoke(logic, ctx):
    wants_ctx = len(inspect.signature(logic).parameters) >= 2
    return logic(ctx.user_text, ctx) if wants_ctx else logic(ctx.user_text)


async def _run(logic, ctx, working_note) -> AsyncIterator[tuple]:
    """Normalise either handler style into a stream of tagged items:
    ('working', note) | ('input-required', question) | ('final', value)."""
    if inspect.isasyncgenfunction(logic):
        final = None
        async for item in _invoke(logic, ctx):
            if isinstance(item, Progress):
                yield ("working", item.note)
            elif isinstance(item, NeedInput):
                yield ("input-required", item.question)
                return
            else:
                final = item                       # a plain value = the answer
        yield ("final", final if final is not None else "")
    else:
        yield ("working", working_note)
        result = await _invoke(logic, ctx)
        if isinstance(result, NeedInput):
            yield ("input-required", result.question)
        else:
            yield ("final", result)


def _ok(rpc_id, result):
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _err(rpc_id, code, message):
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _sse(payload):
    return f"data: {json.dumps(payload)}\n\n"


def build_agent_app(card: AgentCard, logic: AgentLogic, *,
                    working_note: str = "Working…") -> FastAPI:
    app = FastAPI(title=card.name)

    @app.get(AGENT_CARD_PATH)
    async def get_agent_card():
        return JSONResponse(dump(card))

    @app.post("/")
    async def jsonrpc_endpoint(request: Request):
        body = await request.json()
        rpc_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        incoming = params.get("message") or {}
        ctx = RequestContext(
            context_id=incoming.get("contextId") or new_id("ctx"),
            task_id=new_id("task"),
            message=incoming,
        )

        if method == "message/send":
            return await _handle_send(rpc_id, ctx, logic, working_note, card)
        if method == "message/stream":
            return _handle_stream(rpc_id, ctx, logic, working_note, card)
        if method == "tasks/get":
            task = _TASKS.get(params.get("id"))
            return (JSONResponse(_ok(rpc_id, dump(task))) if task
                    else JSONResponse(_err(rpc_id, -32001, "Task not found")))
        if method == "tasks/cancel":
            task = _TASKS.get(params.get("id"))
            if task is None:
                return JSONResponse(_err(rpc_id, -32001, "Task not found"))
            task.status = TaskStatus(state=TaskState.canceled, timestamp=now_iso())
            return JSONResponse(_ok(rpc_id, dump(task)))
        return JSONResponse(_err(rpc_id, -32601, f"Method not found: {method}"))

    return app


async def _handle_send(rpc_id, ctx, logic, working_note, card):
    state, final_value, question = TaskState.completed, "", None
    try:
        async for kind, payload in _run(logic, ctx, working_note):
            if kind == "final":
                final_value = payload
            elif kind == "input-required":
                state, question = TaskState.input_required, payload
    except Exception as exc:                       # noqa: BLE001
        state, final_value = TaskState.failed, f"_({card.name} failed: {exc})_"

    status_msg = (agent_text_message(question, task_id=ctx.task_id, context_id=ctx.context_id)
                  if question is not None else None)
    artifacts = ([artifact_from(final_value)]
                 if state in (TaskState.completed, TaskState.failed) else [])
    task = Task(id=ctx.task_id, contextId=ctx.context_id,
                status=TaskStatus(state=state, message=status_msg, timestamp=now_iso()),
                artifacts=artifacts)
    _TASKS[ctx.task_id] = task
    return JSONResponse(_ok(rpc_id, dump(task)))


def _handle_stream(rpc_id, ctx, logic, working_note, card):
    async def gen():
        submitted = Task(id=ctx.task_id, contextId=ctx.context_id,
                         status=TaskStatus(state=TaskState.submitted, timestamp=now_iso()))
        yield _sse(_ok(rpc_id, dump(submitted)))
        try:
            async for kind, payload in _run(logic, ctx, working_note):
                if kind == "working":
                    ev = TaskStatusUpdateEvent(
                        taskId=ctx.task_id, contextId=ctx.context_id,
                        status=TaskStatus(state=TaskState.working, timestamp=now_iso(),
                                          message=agent_text_message(payload, task_id=ctx.task_id,
                                                                     context_id=ctx.context_id)))
                    yield _sse(_ok(rpc_id, dump(ev)))
                elif kind == "input-required":
                    status = TaskStatus(state=TaskState.input_required, timestamp=now_iso(),
                                        message=agent_text_message(payload, task_id=ctx.task_id,
                                                                   context_id=ctx.context_id))
                    _TASKS[ctx.task_id] = Task(id=ctx.task_id, contextId=ctx.context_id, status=status)
                    yield _sse(_ok(rpc_id, dump(TaskStatusUpdateEvent(
                        taskId=ctx.task_id, contextId=ctx.context_id, status=status, final=True))))
                    return
                else:  # final
                    art = artifact_from(payload)
                    _TASKS[ctx.task_id] = Task(
                        id=ctx.task_id, contextId=ctx.context_id, artifacts=[art],
                        status=TaskStatus(state=TaskState.completed, timestamp=now_iso()))
                    yield _sse(_ok(rpc_id, dump(TaskArtifactUpdateEvent(
                        taskId=ctx.task_id, contextId=ctx.context_id, artifact=art))))
                    yield _sse(_ok(rpc_id, dump(TaskStatusUpdateEvent(
                        taskId=ctx.task_id, contextId=ctx.context_id, final=True,
                        status=TaskStatus(state=TaskState.completed, timestamp=now_iso())))))
        except Exception as exc:                   # noqa: BLE001
            art = artifact_from(f"_({card.name} failed: {exc})_")
            yield _sse(_ok(rpc_id, dump(TaskArtifactUpdateEvent(
                taskId=ctx.task_id, contextId=ctx.context_id, artifact=art))))
            yield _sse(_ok(rpc_id, dump(TaskStatusUpdateEvent(
                taskId=ctx.task_id, contextId=ctx.context_id, final=True,
                status=TaskStatus(state=TaskState.failed, timestamp=now_iso())))))

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                                      "X-Accel-Buffering": "no"})


def run_agent(app: FastAPI, port: int, host: str = "127.0.0.1") -> None:
    """Start the agent's web server (blocking). Used by each employee process."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")
