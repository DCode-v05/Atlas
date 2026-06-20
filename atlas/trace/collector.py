"""Trace / span collector — one observable record per agent operation.

It powers two user-facing surfaces from a single source: the **thinking layer**
(a `think` span carries the agent's reasoning before it speaks) and the
**agent-inspection trace** (every LLM call + policy step the agent performed).
Crucially, each span records whether it was a **real Mistral call** (`live=True`)
or a deterministic / fallback step — so the trace answers "is this real LLM?"
per operation.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Optional

from atlas.a2a.ids import new_id, utcnow
from atlas.events import EventBroker, EventType, TraceSpanPayload


class TraceCollector:
    def __init__(self, broker: EventBroker, *, cap: int = 4000, per_agent: int = 120) -> None:
        self.broker = broker
        self._per_agent_cap = per_agent
        self._spans: deque[TraceSpanPayload] = deque(maxlen=cap)
        self._by_agent: dict[str, deque[TraceSpanPayload]] = defaultdict(lambda: deque(maxlen=per_agent))
        self._by_context: dict[str, list[TraceSpanPayload]] = defaultdict(list)

    def record(
        self,
        *,
        agent_id: str,
        kind: str,
        summary: str,
        live: bool = False,
        context_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> TraceSpanPayload:
        span = TraceSpanPayload(
            span_id=new_id("span-"),
            ts=utcnow().isoformat(),
            agent_id=agent_id,
            context_id=context_id,
            kind=kind,
            summary=summary,
            live=live,
            detail=detail,
        )
        self._spans.append(span)
        self._by_agent[agent_id].append(span)
        if context_id:
            self._by_context[context_id].append(span)
        self.broker.emit(EventType.TRACE_SPAN, span, context_id=context_id)
        return span

    def for_agent(self, agent_id: str, limit: int = 50) -> list[TraceSpanPayload]:
        """Most-recent spans for an agent, newest first."""
        return list(self._by_agent.get(agent_id, []))[-limit:][::-1]

    def for_context(self, context_id: str) -> list[TraceSpanPayload]:
        return list(self._by_context.get(context_id, []))
