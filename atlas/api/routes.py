"""HTTP edge: REST endpoints + the SSE stream.

The Router/orchestrator do the work; these handlers are thin. Anything that
touches asyncio primitives (spawning scenarios, resolving HITL futures) is an
``async def`` so it runs on the event loop, not a threadpool.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from atlas.api.projects import build_project_view, list_projects
from atlas.api.viewmodels import agent_card_view, build_org_view, thread_view
from atlas.config import get_settings
from atlas.org.ext_models import ShareOutcome
from atlas.runtime import build_runtime
from atlas.store import export_snapshot

router = APIRouter(prefix="/api")


def _rt(request: Request):
    rt = getattr(request.app.state, "runtime", None)
    if rt is None:  # pragma: no cover
        raise HTTPException(503, "runtime not ready")
    return rt


# ── read endpoints ────────────────────────────────────────────────────────────
@router.get("/healthz")
def healthz(request: Request):
    rt = _rt(request)
    return {"ok": True, "agents": len(rt.snapshot), "llm": rt.llm.name, "seed": rt.settings.seed,
            "cron": rt.cron.status()}


@router.get("/org")
def org(request: Request):
    return build_org_view(_rt(request))


@router.get("/agents/{agent_id}/card")
def agent_card(agent_id: str, request: Request):
    rt = _rt(request)
    if agent_id not in rt.registry.agents:
        raise HTTPException(404, "unknown agent")
    return agent_card_view(rt, agent_id)


@router.get("/users")
def users(request: Request):
    """The human users of Atlas, each associated 1:1 with the agent they operate."""
    rt = _rt(request)
    return {
        "count": len(rt.snapshot.users),
        "users": [u.model_dump(mode="json") for u in rt.snapshot.users.values()],
    }
@router.get("/projects")
def projects(request: Request):
    """All projects with a compact summary (members / departments / secrets)."""
    return list_projects(_rt(request))


@router.get("/projects/{project_id}")
def project_detail(project_id: str, request: Request):
    """A project as a unit: cross-department members, scoped secrets, live coordination."""
    view = build_project_view(_rt(request), project_id)
    if view is None:
        raise HTTPException(404, "unknown project")
    return view


@router.get("/metrics")
def metrics(request: Request):
    return _rt(request).metrics.snapshot()


@router.get("/hitl")
def hitl_list(request: Request):
    return {"pending": [r.model_dump(mode="json") for r in _rt(request).hitl.list_pending()],
            "resolved_count": len(_rt(request).hitl.resolved)}


@router.get("/tasks")
def tasks(request: Request):
    rt = _rt(request)
    return {
        "tasks": [
            {
                "id": t.id,
                "context_id": t.contextId,
                "state": t.status.state.value,
                "summary": (t.artifacts[0].parts[0].text if t.artifacts and t.artifacts[0].parts else None),
            }
            for t in rt.tasks.values()
        ]
    }


@router.get("/tasks/{task_id}")
def task_detail(task_id: str, request: Request):
    rt = _rt(request)
    t = rt.tasks.get(task_id)
    if t is None:
        raise HTTPException(404, "unknown task")
    return t.model_dump(mode="json")


@router.get("/threads/{context_id}")
def threads(context_id: str, request: Request):
    return thread_view(_rt(request), context_id)


@router.get("/snapshot")
def snapshot(request: Request):
    return export_snapshot(_rt(request))


# ── action endpoints (async: touch the event loop) ─────────────────────────────
@router.post("/prompt")
async def prompt(request: Request, payload: dict = Body(...)):
    rt = _rt(request)
    text = (payload.get("prompt") or "").strip()
    if not text:
        raise HTTPException(400, "prompt is required")
    human = payload.get("human") or "Operator"
    # Optional: attribute the prompt to a specific human user (1:1 with an agent).
    submitted_by = None
    user_id = payload.get("user_id")
    if user_id:
        u = rt.snapshot.users.get(user_id)
        if u is None:
            raise HTTPException(404, "unknown user")
        human = u.name
        submitted_by = {"user_id": u.user_id, "name": u.name, "agent_id": u.agent_id}
    result = await rt.orchestrator.run_user_prompt(text, human)
    if submitted_by:
        result["submitted_by"] = submitted_by
    return result


@router.post("/cron")
async def cron(request: Request, payload: dict = Body(...)):
    on = bool(payload.get("on", False))
    return await _rt(request).cron.toggle(on)


@router.post("/hitl/{request_id}/approve")
async def hitl_approve(request_id: str, request: Request, outcome: str = Query("share")):
    rt = _rt(request)
    oc = ShareOutcome.REDACT if outcome == "redact" else ShareOutcome.SHARE
    res = rt.hitl.resolve(request_id, approved=True, outcome=oc)
    if res is None:
        raise HTTPException(404, "unknown or already-resolved request")
    return {"ok": True, "decision": "approved", "outcome": oc.value}


@router.post("/hitl/{request_id}/deny")
async def hitl_deny(request_id: str, request: Request):
    res = _rt(request).hitl.resolve(request_id, approved=False, outcome=ShareOutcome.DENY)
    if res is None:
        raise HTTPException(404, "unknown or already-resolved request")
    return {"ok": True, "decision": "denied"}


@router.post("/reset")
async def reset(request: Request):
    app = request.app
    old = getattr(app.state, "runtime", None)
    if old is not None:
        await old.registry.stop_heartbeat()
        await old.cron.stop()
    new = build_runtime(get_settings())
    app.state.runtime = new
    await new.registry.start_heartbeat()
    return {"ok": True, "agents": len(new.snapshot)}


# ── SSE stream ──────────────────────────────────────────────────────────────────
def _format(evt) -> dict:
    return {"event": evt.event, "id": str(evt.id), "data": evt.model_dump_json()}


@router.get("/events")
async def events(request: Request):
    rt = _rt(request)
    broker = rt.broker
    queue = broker.subscribe()

    async def generator():
        try:
            # tell the client the stream is live
            yield {"event": "ready", "data": "{}"}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _format(evt)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}  # keep-alive
        finally:
            broker.unsubscribe(queue)

    return EventSourceResponse(generator())
