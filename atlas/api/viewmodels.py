"""View models — REST shapes the frontend consumes for static/catch-up state.

The live state arrives over SSE; these endpoints provide the initial snapshot
(the 100 agents, the faithful Agent Card, a conversation transcript). Note that
secret *bodies* are never exposed here — only titles + sensitivity — so the API
itself honours need-to-know.
"""

from __future__ import annotations

from atlas.org.ext_models import SENSITIVITY_RANK, Sensitivity

_SENSITIVE = {Sensitivity.CONFIDENTIAL, Sensitivity.RESTRICTED, Sensitivity.SECRET}


def build_org_view(rt) -> dict:
    nodes = []
    reporting_edges = []
    for ag in rt.snapshot.agents.values():
        p = ag.profile
        if p.reports_to:
            reporting_edges.append({"source": p.reports_to, "target": ag.id})
        nodes.append(
            {
                "id": ag.id,
                "name": ag.name,
                "role": p.role_title,
                "goal": p.goal,
                "user_id": rt.snapshot.user_of_agent.get(ag.id),
                "department": p.department.value,
                "level": int(p.level),
                "clearance": p.clearance,
                "reports_to": p.reports_to,
                "manages": p.manages,
                "teams": p.teams,
                "projects": p.projects,
                "security_cleared": p.security_cleared,
                "status": ag.status.value,
                "skills": [{"name": s.name, "tags": s.tags} for s in ag.card.skills],
                "owns_sensitive": sum(1 for it in ag.owned_items.values() if it.sensitivity in _SENSITIVE),
                "owns_total": len(ag.owned_items),
            }
        )
    return {
        "org_id": rt.snapshot.org_id,
        "org_name": rt.snapshot.org_name,
        "seed": rt.snapshot.seed,
        "node_count": len(nodes),
        "nodes": nodes,
        "reporting_edges": reporting_edges,
        "teams": rt.snapshot.teams,
        "projects": rt.snapshot.projects,
        "departments": rt.snapshot.departments,
        "ceo_id": rt.snapshot.ceo_id,
        "llm": rt.llm.name,
        "llm_status": rt.llm.status() if hasattr(rt.llm, "status") else {"provider": rt.llm.name, "available": True, "throttled": False},
    }


def agent_card_view(rt, agent_id: str) -> dict:
    ag = rt.registry.get(agent_id)
    user_id = rt.snapshot.user_of_agent.get(agent_id)
    user = rt.snapshot.users.get(user_id) if user_id else None
    return {
        "card": ag.card.model_dump(mode="json"),
        "status": ag.status.value,
        "goal": ag.profile.goal,
        "user": user.model_dump(mode="json") if user else None,
        "owned_items": [
            {
                "item_id": it.item_id,
                "title": it.title,
                "sensitivity": it.sensitivity.value,
                "scope": it.scope.value,
                "scope_ref": it.scope_ref,
                "min_clearance": it.min_clearance,
            }
            for it in ag.owned_items.values()
        ],
        "learned_count": len(ag.learned),
        "learned": [
            {
                "item_id": f.item_id,
                "title": f.title,
                "sensitivity": f.sensitivity.value,
                "redacted": f.redacted,  # True = only ever saw the safe summary
                "source": f.source_agent_id,
                "source_name": _name_of(rt, f.source_agent_id),
            }
            for f in ag.learned.values()
        ],
        "trace": [s.model_dump(mode="json") for s in rt.trace.for_agent(agent_id, limit=60)],
        "manager": ag.profile.reports_to,
        "manages": ag.profile.manages,
    }


def _name_of(rt, agent_id: str) -> str:
    ag = rt.registry.agents.get(agent_id)
    return ag.name if ag else agent_id


def thread_view(rt, context_id: str) -> dict:
    messages = [
        e.data for e in rt.broker.recent(5000) if e.event == "message.sent" and e.context_id == context_id
    ]
    threads = [t.model_dump(mode="json") for t in rt.threads.threads.values() if t.context_id == context_id]
    groups = [g.model_dump(mode="json") for g in rt.groups.groups.values() if g.context_id == context_id]
    return {"context_id": context_id, "threads": threads, "groups": groups, "messages": messages}
