"""JSON snapshot export — freeze a run for inspection / grading.

In-memory state rebuilds deterministically from the seed on boot, so only the
*mutable* run state is worth exporting: the metrics, tasks, HITL decisions, and
the recent event stream.
"""

from __future__ import annotations


def export_snapshot(rt) -> dict:
    return {
        "seed": rt.settings.seed,
        "llm": rt.llm.name,
        "agent_count": len(rt.snapshot),
        "metrics": rt.metrics.snapshot(),
        "tasks": [
            {"id": t.id, "context_id": t.contextId, "state": t.status.state.value}
            for t in rt.tasks.values()
        ],
        "hitl_resolved": [r.model_dump(mode="json") for r in rt.hitl.resolved],
        "hitl_pending": [r.model_dump(mode="json") for r in rt.hitl.list_pending()],
        "agents": [
            {"id": a.id, "status": a.status.value, "learned": len(a.learned), "owns": len(a.owned_items)}
            for a in rt.snapshot.agents.values()
        ],
        "events_recent": [e.model_dump() for e in rt.broker.recent(500)],
    }
