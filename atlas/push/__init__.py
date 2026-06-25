"""Outbound A2A push notifications (webhooks) — the external-edge delivery layer.

A2A clients register a webhook per task; Atlas POSTs a spec-shaped task-status
update to that URL whenever the task changes state. Delivery rides on the
in-process :class:`~atlas.events.EventBroker` (the same fan-out that feeds the
browser SSE), so push reads *downstream* of the Router chokepoint and never
bypasses it.
"""

from atlas.push.service import PushNotificationService

__all__ = ["PushNotificationService"]
