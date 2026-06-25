"""``PushNotificationService`` — register webhooks and deliver task updates.

The A2A push-notification flow, at Atlas's external edge:

* a client registers a :class:`~atlas.a2a.models.PushNotificationConfig` for a task
  (the ``pushNotificationConfig/*`` REST endpoints);
* the service subscribes to the :class:`~atlas.events.EventBroker` and, on every
  ``task.state`` event, POSTs a spec-shaped status update to the webhooks
  registered for that task — out-of-band, so a disconnected client still learns
  when its task progresses or completes.

Delivery is **best-effort**: it runs on the single event loop (no extra worker,
single-worker invariant intact), retries briefly, and never raises into the loop.
Like a slow SSE client, it consumes a bounded broker queue, so under heavy
backpressure the oldest events for a webhook can be dropped — acceptable for the
demonstrator. NOTE: client-supplied webhook URLs are an SSRF surface; a real
deployment must allowlist/validate them before delivering.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from atlas.a2a.ids import utcnow
from atlas.a2a.models import TERMINAL_STATES, PushNotificationConfig, TaskState
from atlas.events import EventBroker, EventType, PushDeliveredPayload


class PushNotificationService:
    def __init__(
        self,
        broker: EventBroker,
        *,
        client: Any = None,
        timeout: float = 5.0,
        max_retries: int = 1,
    ) -> None:
        self.broker = broker
        # task_id -> {config_id: PushNotificationConfig}
        self._configs: dict[str, dict[str, PushNotificationConfig]] = {}
        self._client = client            # injectable httpx.AsyncClient (tests pass an ASGI one)
        self._own_client = client is None
        self._timeout = timeout
        self._max_retries = max_retries
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self.delivered = 0
        self.failed = 0
        self.dbwriter = None  # set by build_runtime; durable write-through when persistence is on

    # ── config registry (CRUD) ──────────────────────────────────────────────
    def set_config(self, task_id: str, cfg: PushNotificationConfig) -> PushNotificationConfig:
        self._configs.setdefault(task_id, {})[cfg.id] = cfg
        if self.dbwriter is not None:
            self.dbwriter.record("push_config", {
                "id": cfg.id, "task_id": task_id, "url": cfg.url, "token": cfg.token,
                "authentication": (cfg.authentication.model_dump(mode="json") if cfg.authentication else None),
            })
        return cfg

    def get_config(self, task_id: str, config_id: str) -> Optional[PushNotificationConfig]:
        return self._configs.get(task_id, {}).get(config_id)

    def list_configs(self, task_id: str) -> list[PushNotificationConfig]:
        return list(self._configs.get(task_id, {}).values())

    def delete_config(self, task_id: str, config_id: str) -> bool:
        bucket = self._configs.get(task_id)
        if bucket and config_id in bucket:
            del bucket[config_id]
            if self.dbwriter is not None:
                self.dbwriter.record("push_config_delete", {"id": config_id})
            return True
        return False

    # ── delivery worker ─────────────────────────────────────────────────────
    async def start(self) -> None:
        if self._task is not None:
            return
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=self._timeout)
        self._queue = self.broker.subscribe()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._queue is not None:
            self.broker.unsubscribe(self._queue)
            self._queue = None
        if self._own_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            evt = await self._queue.get()
            if evt.event == EventType.TASK_STATE.value:
                await self._on_task_state(evt.data)

    async def _on_task_state(self, data: dict) -> None:
        task_id = data.get("task_id")
        if not task_id:
            return
        configs = self.list_configs(task_id)
        if not configs:
            return
        payload = self._status_update(data)
        for cfg in configs:
            await self._deliver(cfg, payload)

    @staticmethod
    def _status_update(data: dict) -> dict:
        state = data.get("state")
        final = state in {s.value for s in TERMINAL_STATES}
        return {
            "type": "task-status-update",
            "taskId": data.get("task_id"),
            "contextId": data.get("context_id"),
            "status": {"state": state, "timestamp": utcnow().isoformat()},
            "final": final,
        }

    async def _deliver(self, cfg: PushNotificationConfig, payload: dict) -> None:
        headers = {"Content-Type": "application/json"}
        if cfg.token:
            # echo the client's token so the receiver can verify the call is genuine
            headers["X-A2A-Notification-Token"] = cfg.token
        if cfg.authentication and cfg.authentication.credentials:
            headers["Authorization"] = f"Bearer {cfg.authentication.credentials}"
        ok = False
        status_code: Optional[int] = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(cfg.url, json=payload, headers=headers)
                status_code = resp.status_code
                if resp.status_code < 500:
                    ok = True
                    break
            except Exception:
                status_code = None  # network error → retry / give up (best-effort)
            if attempt < self._max_retries:
                await asyncio.sleep(0.2)
        if ok:
            self.delivered += 1
        else:
            self.failed += 1
        # surface the attempt to the UI (a slow client falling behind drops oldest, like SSE)
        self.broker.emit(
            EventType.PUSH_DELIVERED,
            PushDeliveredPayload(
                task_id=payload.get("taskId") or "",
                context_id=payload.get("contextId"),
                config_id=cfg.id,
                url=cfg.url,
                ok=ok,
                status_code=status_code,
                state=(payload.get("status") or {}).get("state") or "",
                final=bool(payload.get("final")),
            ),
            context_id=payload.get("contextId"),
        )
