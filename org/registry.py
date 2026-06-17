"""
org/registry.py — the live org chart the gateway builds from telemetry.

As `hire` / `onboard` / `status` events stream in, this assembles the tree of
who-works-for-whom that the UI draws. It is a *projection* of the event log, so
it can always be rebuilt by replaying events.
"""
from __future__ import annotations


class OrgChart:
    def __init__(self) -> None:
        # agent_id -> {role, parentId, depth, status}
        self.members: dict[str, dict] = {}

    def apply(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "hire":
            self.members[ev["agentId"]] = {
                "role": ev.get("role", "?"), "parentId": ev.get("parentId"),
                "depth": ev.get("depth", 0), "status": "hired"}
        elif t == "onboard":
            m = self.members.setdefault(ev["agentId"], {"depth": ev.get("depth", 0)})
            m["role"] = ev.get("role", m.get("role", "?"))
            m["depth"] = ev.get("depth", m.get("depth", 0))
            m["status"] = "onboarded"
            if ev.get("parentId"):
                m["parentId"] = ev["parentId"]
        elif t == "status":
            m = self.members.get(ev.get("agentId"))
            if m:
                m["status"] = ev.get("state", m.get("status"))

    def snapshot(self) -> dict:
        return {aid: dict(m) for aid, m in self.members.items()}
