"""A2A v1.0.0 HTTP+JSON transport binding — the spec-shaped external surface.

Colon-verb paths (``POST /v1/message:send``, ``POST /v1/tasks/{id}:cancel`` …) so any A2A HTTP
client can talk to Atlas directly, not only the bundled UI's ``/api`` edge. Each handler:

* negotiates the protocol version (``A2A-Version`` header) → ``VersionNotSupportedError``;
* enforces required extensions on a send (``A2A-Extensions`` header) → ``ExtensionSupportRequiredError``,
  echoing the activated extensions back in the response header;
* maps failures to A2A **named errors** (``atlas/a2a/errors.py``) — an HTTP status + a spec-shaped
  error body, with no JSON-RPC envelope introduced.

Edge auth covers ``/v1`` (extended in ``atlas/main.py``); ``/.well-known`` discovery stays public.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Request, Response

from atlas.a2a.cards import public_agent_card, service_agent_card
from atlas.a2a.ids import new_id
from atlas.a2a.errors import (
    ExtensionSupportRequiredError,
    InvalidParamsError,
    InternalError,
    TaskNotCancelableError,
    TaskNotFoundError,
    VersionNotSupportedError,
)
from atlas.a2a.extensions import NEED_TO_KNOW_EXT
from atlas.a2a.models import TERMINAL_STATES, TaskState

SUPPORTED_VERSIONS = {"1.0.0", "1.0"}
REQUIRED_EXTENSIONS = {NEED_TO_KNOW_EXT}  # a client must support need-to-know to send a message

v1_router = APIRouter(prefix="/v1")


def _rt(request: Request):
    rt = getattr(request.app.state, "runtime", None)
    if rt is None:  # pragma: no cover
        raise InternalError("runtime not ready")
    return rt


def _negotiate_version(request: Request) -> None:
    v = request.headers.get("a2a-version")
    if v and v not in SUPPORTED_VERSIONS:
        raise VersionNotSupportedError(data={"requested": v, "supported": sorted(SUPPORTED_VERSIONS)})


def _client_extensions(request: Request) -> set[str]:
    raw = request.headers.get("a2a-extensions", "")
    return {u.strip() for u in raw.split(",") if u.strip()}


def _truncate_history(out: dict, history_length: Optional[int]) -> dict:
    if history_length is not None and history_length >= 0:
        out["history"] = out["history"][-history_length:] if history_length else []
    return out


@v1_router.get("/card")
def v1_service_card(request: Request):
    """The public service Agent Card — the A2A discovery entry point (also at /.well-known)."""
    _negotiate_version(request)
    return service_agent_card(_rt(request).snapshot)


@v1_router.get("/agents/{agent_id}/card")
def v1_agent_card(agent_id: str, request: Request):
    _negotiate_version(request)
    rt = _rt(request)
    if agent_id not in rt.registry.agents:
        raise InvalidParamsError("unknown agent", data={"agentId": agent_id})
    return public_agent_card(rt.registry.get(agent_id).card)


@v1_router.post("/message:send")
async def v1_message_send(request: Request, response: Response, payload: dict = Body(...)):
    """A2A **SendMessage** — accept a Message, route it through the need-to-know pipeline, and
    return the opened Task."""
    _negotiate_version(request)
    client_exts = _client_extensions(request)
    missing = REQUIRED_EXTENSIONS - client_exts
    if missing:  # required-extension enforcement
        raise ExtensionSupportRequiredError(data={"required": sorted(missing)})

    rt = _rt(request)
    msg = payload.get("message") or payload
    parts = msg.get("parts") or []
    text = " ".join(p.get("text", "") for p in parts if (p.get("kind") or "text") == "text").strip()
    if not text:
        raise InvalidParamsError("message must contain a non-empty text part")
    refs = msg.get("referenceTaskIds") or []
    result = await rt.orchestrator.run_user_prompt(text, "A2A client", reference_task_ids=refs)
    response.headers["A2A-Extensions"] = ", ".join(sorted(REQUIRED_EXTENSIONS & client_exts))  # echo activated
    if result.get("rejected"):
        # A2A: a server may REJECT a SendMessage — return a Task in the terminal `rejected` state
        # (rather than an error), so the lifecycle is expressed in pure A2A terms.
        ctx = result.get("context_id") or new_id("ctx-")
        task = rt.router.new_task(ctx, message=text, reference_task_ids=refs)
        rt.router.set_task_state(task, TaskState.REJECTED, message=result.get("reason") or "rejected")
        return task.model_dump(mode="json")
    task = rt.tasks.get(result["task_id"])
    return task.model_dump(mode="json")


@v1_router.get("/tasks")
def v1_list_tasks(
    request: Request,
    contextId: Optional[str] = None,
    status: Optional[str] = None,
    includeArtifacts: bool = False,
    limit: int = 50,
    cursor: int = 0,
):
    """A2A **ListTasks** — reuses the shared list logic (newest-first, filters, pagination)."""
    _negotiate_version(request)
    from atlas.api.routes import tasks as _list_tasks

    return _list_tasks(
        request, contextId=contextId, status=status, includeArtifacts=includeArtifacts, limit=limit, cursor=cursor
    )


@v1_router.get("/tasks/{task_id}")
def v1_get_task(task_id: str, request: Request, historyLength: Optional[int] = None):
    """A2A **GetTask** — the full task, optionally truncating history to the last N messages."""
    _negotiate_version(request)
    rt = _rt(request)
    t = rt.tasks.get(task_id)
    if t is None:
        raise TaskNotFoundError(data={"taskId": task_id})
    return _truncate_history(t.model_dump(mode="json"), historyLength)


@v1_router.post("/tasks/{task_id}:cancel")
async def v1_cancel_task(task_id: str, request: Request):
    """A2A **CancelTask** — abort an in-flight task; terminal tasks are not cancelable."""
    _negotiate_version(request)
    rt = _rt(request)
    t = rt.tasks.get(task_id)
    if t is None:
        raise TaskNotFoundError(data={"taskId": task_id})
    if t.status.state in TERMINAL_STATES:
        raise TaskNotCancelableError(data={"taskId": task_id, "state": t.status.state.value})
    task = await rt.orchestrator.cancel_task(task_id)
    return task.model_dump(mode="json")


@v1_router.get("/tasks/{task_id}:subscribe")
async def v1_subscribe_task(task_id: str, request: Request):
    """A2A **SubscribeToTask** — reuses the per-task ``StreamResponse`` stream."""
    _negotiate_version(request)
    rt = _rt(request)
    if rt.tasks.get(task_id) is None:
        raise TaskNotFoundError(data={"taskId": task_id})
    from atlas.api.routes import subscribe_task

    return await subscribe_task(task_id, request)
