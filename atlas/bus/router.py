"""The Router/Gateway — the single chokepoint every interaction passes through.

It does not *decide* scenarios (that's the orchestrator); it provides the
primitives that keep the org honest: the org-scope gate, skill-routing, the task
lifecycle, and the one ``send_message`` path through which every agent→agent
message is recorded, metered, and emitted to the UI. Because everything funnels
here, policy and metrics cannot be bypassed.
"""

from __future__ import annotations

from typing import Optional

from atlas.a2a.extensions import NEED_TO_KNOW_EXT
from atlas.a2a.models import TERMINAL_STATES, Message, Task, TaskState, TaskStatus
from atlas.bus.discovery import Discovery, tokenize
from atlas.bus.registry import AgentRegistry
from atlas.events import (
    CandidateView,
    DiscoveryMatchedPayload,
    EventBroker,
    EventType,
    GateRejectedPayload,
    GroupFormedPayload,
    IntentView,
    MessageSentPayload,
    TaskStatePayload,
    ThreadCreatedPayload,
)
from atlas.metrics.collector import MetricsCollector
from atlas.org.agent import AgentStatus
from atlas.org.ext_models import CoordinationMode, GroupSession, Intent, Thread

GATE_REASON = (
    "This request doesn't relate to anything inside the Atlas organisation — its "
    "people, projects, products, or operations — so it was stopped at the gateway. "
    "Atlas agents only hold and discuss company context."
)


class Router:
    def __init__(
        self,
        registry: AgentRegistry,
        discovery: Discovery,
        broker: EventBroker,
        metrics: MetricsCollector,
        tasks: dict[str, Task],
        *,
        gate_floor: float = 2.0,
    ) -> None:
        self.registry = registry
        self.discovery = discovery
        self.broker = broker
        self.metrics = metrics
        self.tasks = tasks
        self.gate_floor = gate_floor
        self.network = None  # set by build_runtime; enables the membership backstop when live
        self.dbwriter = None  # set by build_runtime; durable write-through when persistence is on

    # ── org-scope gate ────────────────────────────────────────────────────
    def org_scope_gate(self, text: str) -> tuple[bool, str]:
        tokens = set(tokenize(text))
        if tokens & self.registry.snapshot.org_lexicon:
            return True, ""
        _, _, best = self.discovery.route_prompt(text)
        if best >= self.gate_floor:
            return True, ""
        return False, GATE_REASON

    def reject(self, text: str, reason: str) -> None:
        self.broker.emit(EventType.GATE_REJECTED, GateRejectedPayload(prompt=text, reason=reason))

    # ── status ────────────────────────────────────────────────────────────
    def set_status(self, agent_id: str, status: AgentStatus) -> None:
        self.registry.set_status(agent_id, status)

    # ── discovery ─────────────────────────────────────────────────────────
    def _cand_view(self, agent_id: str, score: float) -> CandidateView:
        ag = self.registry.get(agent_id)
        return CandidateView(
            agent_id=agent_id,
            score=round(float(score), 2),
            name=ag.name,
            role=ag.profile.role_title,
            department=ag.profile.department.value,
        )

    def route_prompt(self, text: str, pool_ids=None) -> tuple[Optional[str], list[tuple[str, float]]]:
        chosen, scored, _ = self.discovery.route_prompt(text, pool_ids=pool_ids)
        return chosen, scored

    def emit_discovery(
        self,
        *,
        level: int,
        query: str,
        scored: list[tuple[str, float]],
        chosen: Optional[str],
        requester: Optional[str] = None,
        context_id: Optional[str] = None,
    ) -> None:
        self.broker.emit(
            EventType.DISCOVERY_MATCHED,
            DiscoveryMatchedPayload(
                level=level,
                query=query,
                candidates=[self._cand_view(a, s) for a, s in scored],
                chosen=chosen,
                requester=requester,
            ),
            context_id=context_id,
        )

    # ── task lifecycle ────────────────────────────────────────────────────
    def new_task(
        self,
        context_id: str,
        *,
        state: TaskState = TaskState.SUBMITTED,
        message: Optional[str] = None,
        role: str = "user",
    ) -> Task:
        m = Message.text_message(role, message, contextId=context_id) if message else None  # type: ignore[arg-type]
        task = Task(contextId=context_id, status=TaskStatus(state=state, message=m))
        self.tasks[task.id] = task
        self._emit_task(task)
        if self.dbwriter is not None:
            self.dbwriter.record("task", {"id": task.id, "context_id": context_id, "state": state.value})
        return task

    def set_task_state(self, task: Task, state: TaskState, message: Optional[str] = None) -> None:
        # A2A terminal states are final: once completed/failed/canceled, no further
        # transition is allowed. This is what makes Cancel safe against a racing
        # scenario coroutine that would otherwise flip a canceled task to completed.
        if task.status.state in TERMINAL_STATES:
            return
        m = task.status.message
        if message is not None:
            m = Message.text_message("agent", message, contextId=task.contextId, taskId=task.id)
        task.status = TaskStatus(state=state, message=m)
        self._emit_task(task)
        if self.dbwriter is not None:
            self.dbwriter.record("task", {
                "id": task.id, "context_id": task.contextId, "state": state.value,
                "summary": message if state == TaskState.COMPLETED else None,
            })

    def _emit_task(self, task: Task) -> None:
        msg = task.status.message.text_content if task.status.message else None
        self.broker.emit(
            EventType.TASK_STATE,
            TaskStatePayload(
                task_id=task.id, context_id=task.contextId, state=task.status.state.value, message=msg
            ),
            context_id=task.contextId,
        )

    # ── conversation announcements ────────────────────────────────────────
    def announce_thread(self, thread: Thread) -> None:
        self.broker.emit(
            EventType.THREAD_CREATED,
            ThreadCreatedPayload(
                thread_id=thread.thread_id,
                context_id=thread.context_id,
                participants=list(thread.participants),
                topic=thread.topic,
            ),
            context_id=thread.context_id,
        )

    def announce_group(self, group: GroupSession) -> None:
        self.broker.emit(
            EventType.GROUP_FORMED,
            GroupFormedPayload(
                group_id=group.group_id,
                context_id=group.context_id,
                team_id=group.team_id,
                members=list(group.members),
                topic=group.topic,
                initiator=group.initiator,
            ),
            context_id=group.context_id,
        )

    # ── the one message path ──────────────────────────────────────────────
    def send_message(
        self,
        *,
        context_id: str,
        sender: str,
        recipients: list[str],
        text: str,
        role: str = "agent",
        mode: CoordinationMode = CoordinationMode.INDIVIDUAL,
        intent: Optional[Intent] = None,
        thread_id: Optional[str] = None,
        group_id: Optional[str] = None,
        task: Optional[Task] = None,
        thinking: Optional[str] = None,
    ) -> Optional[Message]:
        # Network membership backstop: only joined agents (or the operator edge) use the bus.
        # The orchestrator already routes within the network; this enforces the invariant.
        if self.network is not None and getattr(self.network, "active", False):
            if sender != "operator" and not self.network.is_member(sender):
                return None
            recipients = [r for r in recipients if r == "operator" or self.network.is_member(r)]
            if not recipients:
                return None
        meta: dict = {}
        extensions: list[str] = []
        intent_view: Optional[IntentView] = None
        if intent is not None:
            meta["intent"] = intent.model_dump(mode="json")
            extensions.append(NEED_TO_KNOW_EXT)
            intent_view = IntentView(
                motivation=intent.motivation,
                purpose_tag=intent.purpose_tag.value,
                requested_topic=intent.requested_topic,
                declared_scope=intent.declared_scope.value,
            )
        msg = Message.text_message(
            role, text, contextId=context_id, taskId=(task.id if task else None), metadata=meta
        )
        msg.extensions = extensions
        if task is not None:
            task.history.append(msg)

        self.metrics.record_message(context_id)
        for r in recipients:
            self.metrics.record_contact(context_id, r)

        self.broker.emit(
            EventType.MESSAGE_SENT,
            MessageSentPayload(
                message_id=msg.messageId,
                context_id=context_id,
                sender=sender,
                recipients=list(recipients),
                mode=mode.value,
                role=role,
                text=text,
                thinking=thinking,
                intent=intent_view,
                thread_id=thread_id,
                group_id=group_id,
            ),
            context_id=context_id,
        )
        if self.dbwriter is not None:
            self.dbwriter.record("message", {
                "id": msg.messageId, "context_id": context_id, "task_id": (task.id if task else None),
                "sender": sender, "recipients": list(recipients), "mode": mode.value, "role": role,
                "text": text, "thinking": thinking, "thread_id": thread_id, "group_id": group_id,
                "intent": (intent.model_dump(mode="json") if intent is not None else None),
            })
        return msg
