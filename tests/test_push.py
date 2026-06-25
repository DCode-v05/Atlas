"""Push-notification (webhook) delivery tests — offline, no real network.

The webhook receiver is an in-process FastAPI app reached over httpx's ASGI
transport, injected into the service, so delivery is exercised end-to-end without
opening a socket. The service consumes the same EventBroker the browser SSE uses.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI, Request

from atlas.a2a.models import PushNotificationAuthentication, PushNotificationConfig
from atlas.events import EventBroker, EventType, TaskStatePayload
from atlas.org.generator import generate_org
from atlas.push import PushNotificationService


def _receiver() -> tuple[FastAPI, list]:
    app = FastAPI()
    received: list = []

    @app.post("/hook")
    async def hook(request: Request):  # pragma: no cover - exercised via ASGI transport
        received.append({"headers": dict(request.headers), "body": await request.json()})
        return {"ok": True}

    return app, received


def _service_to(app: FastAPI, broker: EventBroker) -> PushNotificationService:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://webhook.test")
    return PushNotificationService(broker, client=client)


async def _wait_for(pred, tries: int = 80) -> None:
    for _ in range(tries):
        await asyncio.sleep(0.01)
        if pred():
            return


async def test_push_delivers_on_task_state():
    broker = EventBroker()
    app, received = _receiver()
    svc = _service_to(app, broker)
    await svc.start()
    try:
        cfg = PushNotificationConfig(
            url="http://webhook.test/hook",
            token="tok-123",
            authentication=PushNotificationAuthentication(schemes=["Bearer"], credentials="secret"),
        )
        svc.set_config("task-abc", cfg)
        broker.emit(EventType.TASK_STATE, TaskStatePayload(task_id="task-abc", context_id="ctx-1", state="completed"))
        await _wait_for(lambda: bool(received))

        assert received, "the registered webhook should have received a delivery"
        body = received[0]["body"]
        assert body["taskId"] == "task-abc"
        assert body["contextId"] == "ctx-1"
        assert body["status"]["state"] == "completed"
        assert body["final"] is True  # completed is terminal
        # the client's token is echoed and its credentials become a bearer auth header
        assert received[0]["headers"].get("x-a2a-notification-token") == "tok-123"
        assert received[0]["headers"].get("authorization") == "Bearer secret"
        assert svc.delivered == 1
        # the delivery is surfaced as a push.delivered SSE event for the dashboard
        evs = [e for e in broker.recent(50) if e.event == "push.delivered"]
        assert evs and evs[-1].data["ok"] is True and evs[-1].data["task_id"] == "task-abc"
        assert evs[-1].data["state"] == "completed" and evs[-1].data["final"] is True
    finally:
        await svc.stop()


async def test_push_no_config_means_no_delivery():
    broker = EventBroker()
    app, received = _receiver()
    svc = _service_to(app, broker)
    await svc.start()
    try:
        broker.emit(EventType.TASK_STATE, TaskStatePayload(task_id="unregistered", context_id="c", state="working"))
        await _wait_for(lambda: False, tries=15)  # give the worker time; nothing should arrive
        assert received == []
    finally:
        await svc.stop()


async def test_deleted_config_stops_delivery():
    broker = EventBroker()
    app, received = _receiver()
    svc = _service_to(app, broker)
    await svc.start()
    try:
        cfg = svc.set_config("t1", PushNotificationConfig(url="http://webhook.test/hook"))
        assert svc.delete_config("t1", cfg.id) is True
        broker.emit(EventType.TASK_STATE, TaskStatePayload(task_id="t1", context_id="c", state="completed"))
        await _wait_for(lambda: False, tries=15)
        assert received == []
        assert svc.delete_config("t1", "nope") is False  # idempotent miss
    finally:
        await svc.stop()


def test_cards_advertise_push_now_that_it_is_backed():
    org = generate_org(42)
    assert all(a.card.capabilities.pushNotifications for a in org.agents.values())
