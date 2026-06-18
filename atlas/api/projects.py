"""Projects Workspace — a project-centric, **read-only** lens on the org.

Atlas's structure is by department, but its *work* cuts across departments along
shared projects (``atlas-core``, ``billing``, ``mobile``). This module joins data
the snapshot already holds — project membership, project-scoped secrets — with
the live conversation state (1:1 threads and group sessions whose participants
belong to the project) so the UI can show a project as a single unit.

It touches nothing in the live flow: it only *reads* the snapshot, thread store,
and group store. The Router, policy engine, orchestrator and cron are untouched.
And like the other view endpoints, secret *bodies* are never exposed — only
titles + sensitivity — so need-to-know is honoured here too.
"""

from __future__ import annotations

from typing import Optional

from atlas.org.ext_models import SENSITIVITY_RANK, Scope

_LEVEL_LABEL = {5: "CEO", 4: "Dept Head", 3: "Manager", 2: "Lead", 1: "IC"}
_SENSITIVITY_RANK_BY_VALUE = {s.value: r for s, r in SENSITIVITY_RANK.items()}


def _members(rt, project_id: str) -> list:
    return rt.snapshot.projects.get(project_id, [])


def _member_view(rt, agent_id: str) -> dict:
    p = rt.snapshot.agents[agent_id].profile
    return {
        "agent_id": agent_id,
        "name": rt.snapshot.agents[agent_id].name,
        "role": p.role_title,
        "department": p.department.value,
        "level": int(p.level),
        "level_label": _LEVEL_LABEL.get(int(p.level), str(int(p.level))),
        "clearance": p.clearance,
    }


def _project_secrets(rt, project_id: str) -> list[dict]:
    out = []
    for it in rt.snapshot.items.values():
        if it.scope == Scope.PROJECT and it.scope_ref == project_id:
            out.append({
                "item_id": it.item_id,
                "title": it.title,  # title + sensitivity only — never the body
                "sensitivity": it.sensitivity.value,
                "owner_agent_id": it.owner_agent_id,
                "owner_name": rt.snapshot.agents[it.owner_agent_id].name,
            })
    out.sort(key=lambda s: _SENSITIVITY_RANK_BY_VALUE.get(s["sensitivity"], 0), reverse=True)
    return out


def _name(rt, agent_id: str) -> str:
    ag = rt.snapshot.agents.get(agent_id)
    return ag.name if ag else agent_id


def _conversations(rt, member_set: set[str]) -> dict:
    """Threads/groups whose participants belong to this project."""
    threads = []
    for t in rt.threads.threads.values():
        if t.participants and all(pid in member_set for pid in t.participants):
            threads.append({
                "thread_id": t.thread_id,
                "context_id": t.context_id,
                "topic": t.topic,
                "participants": [_name(rt, pid) for pid in t.participants],
                "messages": len(t.message_ids),
            })
    groups = []
    for g in rt.groups.groups.values():
        in_proj = [m for m in g.members if m in member_set]
        if len(in_proj) >= 2:  # a group counts as "on this project" if ≥2 members are in it
            groups.append({
                "group_id": g.group_id,
                "context_id": g.context_id,
                "topic": g.topic,
                "initiator": _name(rt, g.initiator),
                "members": len(g.members),
                "members_in_project": len(in_proj),
                "messages": len(g.message_ids),
                "active": g.active,
            })
    return {"threads": threads, "groups": groups}


def build_project_view(rt, project_id: str) -> Optional[dict]:
    member_ids = _members(rt, project_id)
    if not member_ids:
        return None
    members = [_member_view(rt, aid) for aid in member_ids]
    members.sort(key=lambda m: (-m["level"], m["department"], m["name"]))

    dept_counts: dict[str, int] = {}
    for m in members:
        dept_counts[m["department"]] = dept_counts.get(m["department"], 0) + 1
    departments = sorted(
        ({"department": d, "count": c} for d, c in dept_counts.items()),
        key=lambda x: x["count"], reverse=True,
    )

    secrets = _project_secrets(rt, project_id)
    convos = _conversations(rt, set(member_ids))
    return {
        "project_id": project_id,
        "members": members,
        "departments": departments,
        "secrets": secrets,
        "conversations": convos,
        "stats": {
            "members": len(members),
            "departments": len(departments),
            "secrets": len(secrets),
            "active_conversations": len(convos["threads"]) + len(convos["groups"]),
        },
    }


def list_projects(rt) -> dict:
    projects = []
    for pid, member_ids in rt.snapshot.projects.items():
        depts = {rt.snapshot.agents[aid].profile.department.value for aid in member_ids}
        secrets = sum(
            1 for it in rt.snapshot.items.values()
            if it.scope == Scope.PROJECT and it.scope_ref == pid
        )
        projects.append({
            "project_id": pid,
            "members": len(member_ids),
            "departments": len(depts),
            "secrets": secrets,
        })
    projects.sort(key=lambda p: p["members"], reverse=True)
    return {"count": len(projects), "projects": projects}
