"""HTTP edge: REST endpoints + the SSE stream.

The Router/orchestrator do the work; these handlers are thin. Anything that
touches asyncio primitives (spawning scenarios, resolving HITL futures) is an
``async def`` so it runs on the event loop, not a threadpool.
"""

from __future__ import annotations

import asyncio
import base64

from fastapi import APIRouter, Body, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from atlas.a2a.ids import new_id
from atlas.a2a.models import (
    TERMINAL_STATES,
    Message,
    PushNotificationAuthentication,
    PushNotificationConfig,
    StreamResponse,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskStatusUpdateEvent,
    TextPart,
)
from atlas.a2a.cards import agent_catalog, extended_agent_card, public_agent_card, service_agent_card
from atlas.api.projects import build_project_view, list_projects
from atlas.api.viewmodels import agent_card_view, build_org_view, thread_view
from atlas.config import get_settings
from atlas.events import EventType
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


@router.get("/agents/{agent_id}/card/extended")
def agent_card_extended(agent_id: str, request: Request):
    """A2A ``GetExtendedAgentCard`` — the richer card served to AUTHENTICATED
    callers (the org-profile extension: dept / level / clearance / reportsTo / goal).

    This route lives under ``/api`` so the edge-auth middleware gates it whenever
    ``ATLAS_API_KEY`` is configured; the public card (well-known) never requires auth."""
    rt = _rt(request)
    ag = rt.registry.agents.get(agent_id)
    if ag is None:
        raise HTTPException(404, "unknown agent")
    if not ag.card.capabilities.extendedAgentCard:
        raise HTTPException(404, "this agent does not offer an extended card")
    return extended_agent_card(ag.card)


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


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request):
    """A2A ``tasks/cancel`` — abort an in-flight task (user goal or cron goal),
    driving it to the terminal ``canceled`` state and stopping its agents."""
    rt = _rt(request)
    task = await rt.orchestrator.cancel_task(task_id)
    if task is None:
        raise HTTPException(404, "unknown task")
    return task.model_dump(mode="json")


@router.get("/tasks/{task_id}/subscribe")
async def subscribe_task(task_id: str, request: Request):
    """A2A ``SubscribeToTask`` — stream ONE task's lifecycle as spec-shaped
    ``StreamResponse`` frames (a Task snapshot on attach, then status-update /
    message / artifact-update events), closing on a terminal state with
    ``final: true`` — the A2A ordered-event + terminal-close contract.

    Any A2A client can consume this without bespoke mapping; it's the
    agent-to-agent counterpart of the browser's global ``/events`` SSE."""
    rt = _rt(request)
    if rt.tasks.get(task_id) is None:
        raise HTTPException(404, "unknown task")
    context_id = rt.tasks[task_id].contextId
    broker = rt.broker
    queue = broker.subscribe()

    def frame(sr: StreamResponse, event: str) -> dict:
        return {"event": event, "data": sr.model_dump_json(exclude_none=True)}

    def status_frame(t) -> dict:
        final = t.status.state in TERMINAL_STATES
        sr = StreamResponse(statusUpdate=TaskStatusUpdateEvent(
            taskId=task_id, contextId=context_id, status=t.status, final=final))
        return frame(sr, "status-update")

    async def generator():
        try:
            snap = rt.tasks.get(task_id)
            if snap is not None:
                yield frame(StreamResponse(task=snap), "task")  # A2A: current state on attach
                if snap.status.state in TERMINAL_STATES:
                    yield status_frame(snap)  # already finished → final frame, then close
                    return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if evt.context_id != context_id:
                    continue
                if evt.event == EventType.TASK_STATE.value:
                    t = rt.tasks.get(task_id)
                    if t is None:
                        continue
                    yield status_frame(t)
                    if t.status.state in TERMINAL_STATES:
                        for art in (t.artifacts or []):  # surface artifacts, then close
                            yield frame(StreamResponse(artifactUpdate=TaskArtifactUpdateEvent(
                                taskId=task_id, contextId=context_id, artifact=art)), "artifact-update")
                        break
                elif evt.event == EventType.MESSAGE_SENT.value:
                    d = evt.data or {}
                    msg = Message(
                        messageId=d.get("message_id") or new_id("msg-"),
                        role=d.get("role", "agent"),
                        parts=[TextPart(text=d.get("text", ""))],
                        contextId=context_id, taskId=task_id,
                    )
                    yield frame(StreamResponse(message=msg), "message")
        finally:
            broker.unsubscribe(queue)

    return EventSourceResponse(generator())


# ── push-notification configs (A2A pushNotificationConfig/Set·Get·List·Delete) ──
# A client registers a webhook for a task; Atlas POSTs a status update to it on
# every task.state change (delivery in atlas/push). The task must exist first.
@router.post("/tasks/{task_id}/push-notification-configs")
def push_config_set(task_id: str, request: Request, payload: dict = Body(...)):
    rt = _rt(request)
    if task_id not in rt.tasks:
        raise HTTPException(404, "unknown task")
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")
    auth = payload.get("authentication")
    cfg = PushNotificationConfig(
        url=url,
        token=payload.get("token"),
        authentication=PushNotificationAuthentication(**auth) if isinstance(auth, dict) else None,
    )
    rt.push.set_config(task_id, cfg)
    return TaskPushNotificationConfig(taskId=task_id, pushNotificationConfig=cfg).model_dump(mode="json")


@router.get("/tasks/{task_id}/push-notification-configs")
def push_config_list(task_id: str, request: Request):
    rt = _rt(request)
    if task_id not in rt.tasks:
        raise HTTPException(404, "unknown task")
    return {
        "taskId": task_id,
        "configs": [c.model_dump(mode="json") for c in rt.push.list_configs(task_id)],
    }


@router.get("/tasks/{task_id}/push-notification-configs/{config_id}")
def push_config_get(task_id: str, config_id: str, request: Request):
    rt = _rt(request)
    cfg = rt.push.get_config(task_id, config_id)
    if cfg is None:
        raise HTTPException(404, "unknown push-notification config")
    return TaskPushNotificationConfig(taskId=task_id, pushNotificationConfig=cfg).model_dump(mode="json")


@router.delete("/tasks/{task_id}/push-notification-configs/{config_id}")
def push_config_delete(task_id: str, config_id: str, request: Request):
    rt = _rt(request)
    if not rt.push.delete_config(task_id, config_id):
        raise HTTPException(404, "unknown push-notification config")
    return {"ok": True, "deleted": config_id}


# ── authenticated network (Ed25519 challenge/response → scoped JWT; requires the DB) ──
def _net(request: Request):
    rt = _rt(request)
    if rt.network is None:
        raise HTTPException(503, "the authenticated network requires the database (set ATLAS_DATABASE_URL)")
    return rt.network


@router.get("/network")
def network_status(request: Request):
    members = _net(request).members()
    return {"count": len(members), "members": members}


@router.get("/network/challenge")
async def network_challenge(agent_id: str, request: Request):
    ch = await _net(request).create_challenge(agent_id)
    if ch is None:
        raise HTTPException(404, "unknown agent")
    return ch


@router.post("/network/authenticate")
async def network_authenticate(request: Request, payload: dict = Body(...)):
    net = _net(request)
    agent_id, nonce, sig = payload.get("agent_id"), payload.get("nonce"), payload.get("signature")
    if not (agent_id and nonce and sig):
        raise HTTPException(400, "agent_id, nonce and signature (base64) are required")
    try:
        signature = base64.b64decode(sig)
    except Exception:
        raise HTTPException(400, "signature must be base64-encoded")
    res = await net.authenticate(agent_id, nonce, signature)
    if res is None:
        raise HTTPException(401, "authentication failed")
    return res


@router.post("/network/agents/{agent_id}/join")
async def network_join(agent_id: str, request: Request):
    """Operator one-click join: runs the real challenge/response server-side with the agent's key."""
    res = await _net(request).authenticate_oneclick(agent_id)
    if res is None:
        raise HTTPException(404, "unknown agent")
    return res


@router.post("/network/agents/{agent_id}/disconnect")
async def network_disconnect(agent_id: str, request: Request):
    net = _net(request)
    ok = await net.disconnect(agent_id)
    return {"ok": ok, "agent_id": agent_id, "count": len(net.members())}


@router.post("/network/verify")
def network_verify(request: Request, payload: dict = Body(...)):
    claims = _net(request).verify_token(payload.get("token") or "")
    if claims is None:
        raise HTTPException(401, "invalid, expired, or revoked token")
    return {"valid": True, "claims": claims}


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


@router.get("/history")
async def history(request: Request, limit: int = 30):
    """Replay the persisted conversation record (header + messages + share-decisions + task
    state) so the timeline and History survive a refresh/restart. Requires the DB; in-memory
    mode returns nothing (the live SSE stream is the only source then)."""
    rt = _rt(request)
    if rt.db is None:
        return {"conversations": []}
    from sqlalchemy import select

    from atlas.db.models import ConversationRow, MessageRow, ShareDecisionRow, TaskRow

    limit = max(1, min(int(limit), 100))
    async with rt.db.session() as s:
        convos = (await s.execute(
            select(ConversationRow)
            .order_by(ConversationRow.created_at.desc(), ConversationRow.context_id.desc())
            .limit(limit)
        )).scalars().all()
        cids = [c.context_id for c in convos]
        if not cids:
            return {"conversations": []}
        msgs = (await s.execute(
            select(MessageRow).where(MessageRow.context_id.in_(cids)).order_by(MessageRow.seq.asc())
        )).scalars().all()
        decs = (await s.execute(
            select(ShareDecisionRow).where(ShareDecisionRow.context_id.in_(cids)).order_by(ShareDecisionRow.id.asc())
        )).scalars().all()
        tasks = (await s.execute(select(TaskRow).where(TaskRow.context_id.in_(cids)))).scalars().all()

    def ms(epoch) -> int:  # persisted ts is epoch SECONDS; the UI timeline sorts in milliseconds
        return int(epoch or 0) * 1000

    msgs_by: dict = {}
    for m in msgs:
        msgs_by.setdefault(m.context_id, []).append({
            "message_id": m.id, "sender": m.sender, "recipients": m.recipients or [], "mode": m.mode,
            "role": m.role, "text": m.text, "thinking": m.thinking, "intent": m.intent,
            "thread_id": m.thread_id, "group_id": m.group_id, "ts": ms(m.ts),
        })
    decs_by: dict = {}
    for d in decs:
        decs_by.setdefault(d.context_id, []).append({
            "context_id": d.context_id, "item_id": d.item_id, "title": d.title, "sender": d.sender,
            "recipient": d.recipient, "sensitivity": d.sensitivity, "rule_id": d.rule_id,
            "reason": d.reason, "summary": d.summary, "kind": d.kind, "ts": ms(d.ts),
        })
    state_by = {t.context_id: t.state for t in tasks}
    conversations = [{
        "context_id": c.context_id, "prompt": c.prompt, "kind": c.kind, "routed_to": c.routed_to,
        "routed_to_name": c.routed_to_name, "task_id": c.task_id,
        "state": state_by.get(c.context_id, "completed"), "ts": ms(c.created_at),
        "messages": msgs_by.get(c.context_id, []), "decisions": decs_by.get(c.context_id, []),
    } for c in convos]
    return {"conversations": conversations}


@router.post("/history/clear")
async def history_clear(request: Request):
    """Wipe the conversation/history record — the DB rows AND the in-memory task registry +
    event history — while leaving the org and the network membership untouched."""
    rt = _rt(request)
    cleared: dict = {}
    if rt.db is not None:
        from atlas.db import clear_history

        cleared = await clear_history(rt.db)
    rt.tasks.clear()           # in-memory task registry
    rt.broker.history.clear()  # so a reconnecting SSE client can't replay the old events
    return {"ok": True, "cleared": cleared}


# ── A2A discovery: public Agent Cards at the well-known URI (root, no auth) ──────
# These live OUTSIDE the /api prefix so they are NOT gated by the edge-auth
# middleware — discovery is public by design (the entry point to the ecosystem).
wellknown_router = APIRouter()


@wellknown_router.get("/.well-known/agent-card.json")
def well_known_agent_card(request: Request):
    """A2A discovery entry point — the Atlas service's primary PUBLIC Agent Card."""
    return service_agent_card(_rt(request).snapshot)


@wellknown_router.get("/.well-known/agents.json")
def well_known_agent_catalog(request: Request):
    """Discovery index — every agent and the URL of its public card."""
    return agent_catalog(_rt(request).snapshot)


@wellknown_router.get("/.well-known/agents/{agent_id}/agent-card.json")
def well_known_agent_card_for(agent_id: str, request: Request):
    """A specific agent's PUBLIC Agent Card (no internal org profile)."""
    ag = _rt(request).registry.agents.get(agent_id)
    if ag is None:
        raise HTTPException(404, "unknown agent")
    return public_agent_card(ag.card)
