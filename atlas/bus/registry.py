"""The agent registry: holds the 100 agents, indexes their cards for discovery,
tracks status, and runs the idle heartbeat.

"Running continuously" means each agent has a live ``status`` + ``last_heartbeat``
here — not 100 hot loops. Agents are woken event-driven by the orchestrator; idle
is simply ``IDLE`` + a refreshed heartbeat.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from atlas.a2a.ids import utcnow
from atlas.events import AgentStatusPayload, EventBroker, EventType
from atlas.org.agent import AgentStatus, OrgAgent
from atlas.org.ext_models import Department
from atlas.org.generator import OrgSnapshot


class AgentRegistry:
    def __init__(self, snapshot: OrgSnapshot, broker: EventBroker) -> None:
        self.snapshot = snapshot
        self.broker = broker
        self.agents: dict[str, OrgAgent] = snapshot.agents
        self._by_tag: dict[str, set[str]] = defaultdict(set)
        self._by_dept: dict[str, list[str]] = defaultdict(list)
        self._hb_task: asyncio.Task | None = None
        self._build_index()

    def _build_index(self) -> None:
        for aid, ag in self.agents.items():
            self._by_dept[ag.profile.department.value].append(aid)
            for tag in ag.card.skill_tags:
                self._by_tag[tag].add(aid)

    # lookups --------------------------------------------------------------
    def get(self, agent_id: str) -> OrgAgent:
        return self.agents[agent_id]

    def all(self) -> list[OrgAgent]:
        return list(self.agents.values())

    def ids(self) -> list[str]:
        return list(self.agents.keys())

    def by_tag(self, tag: str) -> set[str]:
        return set(self._by_tag.get(tag.lower(), set()))

    def by_department(self, dept: Department | str) -> list[str]:
        key = dept.value if isinstance(dept, Department) else dept
        return list(self._by_dept.get(key, []))

    # status ---------------------------------------------------------------
    def set_status(self, agent_id: str, status: AgentStatus) -> None:
        ag = self.agents[agent_id]
        if ag.status == status:
            ag.last_heartbeat = utcnow()
            return
        ag.status = status
        ag.last_heartbeat = utcnow()
        self.broker.emit(
            EventType.AGENT_STATUS,
            AgentStatusPayload(
                agent_id=agent_id,
                status=status.value,
                name=ag.name,
                role=ag.profile.role_title,
                department=ag.profile.department.value,
            ),
        )

    def reset_all_idle(self) -> None:
        for ag in self.agents.values():
            ag.status = AgentStatus.IDLE
            ag.last_heartbeat = utcnow()

    # heartbeat ------------------------------------------------------------
    async def start_heartbeat(self, interval: float = 3.0) -> None:
        if self._hb_task is None:
            self._hb_task = asyncio.create_task(self._heartbeat_loop(interval))

    async def stop_heartbeat(self) -> None:
        if self._hb_task is not None:
            self._hb_task.cancel()
            try:
                await self._hb_task
            except asyncio.CancelledError:
                pass
            self._hb_task = None

    async def _heartbeat_loop(self, interval: float) -> None:
        # Keeps agents "alive" without flooding the SSE stream: just refresh
        # timestamps. Real status events are emitted on actual state changes.
        while True:
            await asyncio.sleep(interval)
            now = utcnow()
            for ag in self.agents.values():
                ag.last_heartbeat = now
