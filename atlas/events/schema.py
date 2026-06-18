"""The SSE event contract — the single source of truth for realtime.

⚠️  This is the canonical schema. The frontend's ``web/src/types/events.ts``
MIRRORS this file; if you change an event payload here, change it there too.
Every realtime thing the UI shows is one of the ``EventType`` values below.

The wire envelope is :class:`Event` — ``{event, id, ts, context_id?, data}``.
Payload models document the shape of ``data`` for each event type.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    AGENT_STATUS = "agent.status"
    PROMPT_ACCEPTED = "prompt.accepted"
    GATE_REJECTED = "gate.rejected"
    DISCOVERY_MATCHED = "discovery.matched"
    TASK_STATE = "task.state"
    THREAD_CREATED = "thread.created"
    GROUP_FORMED = "group.formed"
    MESSAGE_SENT = "message.sent"
    CONTEXT_SHARED = "context.shared"
    CONTEXT_REDACTED = "context.redacted"
    CONTEXT_DENIED = "context.denied"
    CONTEXT_REUSED = "context.reused"  # redundant contact avoided
    HITL_REQUESTED = "hitl.requested"
    HITL_RESOLVED = "hitl.resolved"
    METRICS_UPDATED = "metrics.updated"
    CRON_TICK = "cron.tick"
    CRON_STATE = "cron.state"
    LLM_STATUS = "llm.status"


#: Stable, ordered list of every event type — mirrored by the frontend.
ALL_EVENT_TYPES: tuple[str, ...] = tuple(e.value for e in EventType)


# ─── Wire envelope ────────────────────────────────────────────────────────────


class Event(BaseModel):
    event: str
    id: int
    ts: str
    context_id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


# ─── Shared sub-objects ───────────────────────────────────────────────────────


class CandidateView(BaseModel):
    agent_id: str
    score: float
    name: str = ""
    role: str = ""
    department: str = ""


class IntentView(BaseModel):
    motivation: str
    purpose_tag: str
    requested_topic: str
    declared_scope: str


# ─── Event payloads (the shape of Event.data per type) ────────────────────────


class AgentStatusPayload(BaseModel):
    agent_id: str
    status: str
    name: str = ""
    role: str = ""
    department: str = ""


class PromptAcceptedPayload(BaseModel):
    prompt: str
    task_id: str
    context_id: str
    routed_to: str
    routed_to_name: str = ""


class GateRejectedPayload(BaseModel):
    prompt: str
    reason: str


class DiscoveryMatchedPayload(BaseModel):
    level: int  # 1 = user→agent, 2 = agent→agents
    query: str
    candidates: list[CandidateView] = Field(default_factory=list)
    chosen: Optional[str] = None
    requester: Optional[str] = None


class TaskStatePayload(BaseModel):
    task_id: str
    context_id: str
    state: str
    message: Optional[str] = None


class ThreadCreatedPayload(BaseModel):
    thread_id: str
    context_id: str
    participants: list[str]
    topic: str = ""


class GroupFormedPayload(BaseModel):
    group_id: str
    context_id: str
    team_id: str
    members: list[str]
    topic: str
    initiator: str


class MessageSentPayload(BaseModel):
    message_id: str
    context_id: str
    sender: str
    recipients: list[str]
    mode: str  # individual | group
    role: str  # user | agent
    text: str
    intent: Optional[IntentView] = None
    thread_id: Optional[str] = None
    group_id: Optional[str] = None


class ContextSharePayload(BaseModel):
    """Used by context.shared / context.redacted / context.denied / context.reused."""

    context_id: str
    item_id: str
    title: str
    sender: str  # the owner of the data
    recipient: str  # who asked
    sensitivity: str
    rule_id: str
    reason: str
    summary: Optional[str] = None  # set on redact


class HitlRequestedPayload(BaseModel):
    request_id: str
    task_id: str
    context_id: str
    owner: str
    requester: str
    item_id: str
    item_title: str
    sensitivity: str
    intent: IntentView
    proposed_outcome: str
    reason: str


class HitlResolvedPayload(BaseModel):
    request_id: str
    decision: str  # approved | denied
    outcome: Optional[str] = None  # share | redact | deny
    decided_by: str = "control-tower"


class MetricsUpdatedPayload(BaseModel):
    context_id: Optional[str] = None
    metrics: dict[str, Any]
    derived: dict[str, float]
    totals: dict[str, Any]


class CronTickPayload(BaseModel):
    elapsed: float
    remaining: float
    running: bool
    planned: Optional[str] = None


class CronStatePayload(BaseModel):
    running: bool
    burst_seconds: float = 0.0
    mode: Literal["burst", "continuous"] = "burst"


class LlmStatusPayload(BaseModel):
    provider: str
    available: bool
    throttled: bool
    rpm: int
    calls_ok: int = 0
    calls_throttled: int = 0
    calls_429: int = 0
    reason: str = ""
