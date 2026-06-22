"""Communication-efficiency metrics — computed at the Router chokepoint.

Counters are kept per ``context_id`` and aggregated globally. These are the
numbers that answer the project's actual question: *how efficiently did the
agents coordinate?* — hops to resolve, messages exchanged, how much context was
shared vs redacted vs denied, and how many redundant contacts were avoided.
"""

from __future__ import annotations

from atlas.events import EventBroker, EventType, MetricsUpdatedPayload
from atlas.org.ext_models import Metrics, ShareOutcome


class MetricsCollector:
    def __init__(self, broker: EventBroker) -> None:
        self.broker = broker
        self.totals = Metrics(context_id=None)
        self.per_context: dict[str, Metrics] = {}
        self._chain: dict[str, set[str]] = {}  # agents in the resolution chain
        self._contacted: dict[str, set[str]] = {}  # distinct agents messaged

    def ctx(self, context_id: str) -> Metrics:
        m = self.per_context.get(context_id)
        if m is None:
            m = Metrics(context_id=context_id)
            self.per_context[context_id] = m
            self._chain[context_id] = set()
            self._contacted[context_id] = set()
        return m

    # event hooks ----------------------------------------------------------
    def record_message(self, context_id: str) -> None:
        self.ctx(context_id).messages += 1
        self.totals.messages += 1

    def record_contact(self, context_id: str, agent_id: str) -> None:
        self.ctx(context_id)
        seen = self._contacted[context_id]
        if agent_id not in seen:
            seen.add(agent_id)
            self.ctx(context_id).distinct_agents_contacted = len(seen)
            self.totals.distinct_agents_contacted += 1

    def record_hop(self, context_id: str, agent_id: str) -> None:
        """An agent actually contributed to resolving this context (a real hop)."""
        self.ctx(context_id)
        chain = self._chain[context_id]
        if agent_id not in chain:
            chain.add(agent_id)
            self.ctx(context_id).hops = len(chain)
            self.totals.hops += 1

    def record_decision(self, context_id: str, outcome: ShareOutcome) -> None:
        m = self.ctx(context_id)
        m.share_requests += 1
        self.totals.share_requests += 1
        if outcome == ShareOutcome.SHARE:
            m.items_shared += 1
            self.totals.items_shared += 1
        elif outcome == ShareOutcome.REDACT:
            m.items_redacted += 1
            self.totals.items_redacted += 1
        elif outcome == ShareOutcome.DENY:
            m.items_denied += 1
            self.totals.items_denied += 1
        elif outcome == ShareOutcome.ESCALATE:
            m.hitl_escalations += 1
            self.totals.hitl_escalations += 1

    def record_resolution(self, context_id: str, outcome: ShareOutcome) -> None:
        """Record a HITL-resolved outcome WITHOUT re-counting the share request
        (the original ESCALATE already counted toward ``share_requests``)."""
        m = self.ctx(context_id)
        if outcome == ShareOutcome.SHARE:
            m.items_shared += 1
            self.totals.items_shared += 1
        elif outcome == ShareOutcome.REDACT:
            m.items_redacted += 1
            self.totals.items_redacted += 1
        elif outcome == ShareOutcome.DENY:
            m.items_denied += 1
            self.totals.items_denied += 1

    def record_redundant_avoided(self, context_id: str) -> None:
        self.ctx(context_id).redundant_contacts_avoided += 1
        self.totals.redundant_contacts_avoided += 1

    def record_policy_review(self, context_id: str) -> None:
        """The Policy Officer gave an independent compliance second opinion."""
        self.ctx(context_id).policy_reviews += 1
        self.totals.policy_reviews += 1

    def record_policy_override(self, context_id: str) -> None:
        """The Policy Officer tightened the owner's share decision."""
        self.ctx(context_id).policy_overrides += 1
        self.totals.policy_overrides += 1

    # emit -----------------------------------------------------------------
    def emit(self, context_id: str | None = None) -> None:
        m = self.per_context.get(context_id) if context_id else None
        payload = MetricsUpdatedPayload(
            context_id=context_id,
            metrics=(m.model_dump() if m else {}),
            derived=(m.derived() if m else {}),
            totals={**self.totals.model_dump(), "derived": self.totals.derived()},
        )
        self.broker.emit(EventType.METRICS_UPDATED, payload, context_id=context_id)

    def snapshot(self) -> dict:
        return {
            "totals": {**self.totals.model_dump(), "derived": self.totals.derived()},
            "per_context": {
                cid: {**m.model_dump(), "derived": m.derived()}
                for cid, m in self.per_context.items()
            },
        }
