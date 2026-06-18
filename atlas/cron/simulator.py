"""The cron simulation engine.

While toggled on, agents autonomously launch a new **goal every ``cron_goal_seconds``**
(default 30s) — continuously, not a one-off burst — and work it through the
*identical* orchestrator pipeline, so policy, redaction, and HITL are enforced
exactly as on the interactive path (escalations land in the same operator queue).
Goals are **balanced across all departments** (round-robin), so activity isn't
concentrated in Engineering. The sequence is seeded for reproducibility; message
phrasing uses the same real Mistral (Amazon Bedrock) as the interactive path.
"""

from __future__ import annotations

import asyncio
import contextlib
from random import Random
from typing import Optional

from atlas.bus.registry import AgentRegistry
from atlas.config import Settings
from atlas.conversation.orchestrator import Orchestrator
from atlas.events import CronStatePayload, CronTickPayload, EventBroker, EventType
from atlas.org.ext_models import Department
from atlas.org.generator import OrgSnapshot

# One or more (label, prompt) goals per department. Wording with team/sync/align/
# coordinate/incident triggers a group session; sensitive items drive redaction /
# HITL. Every department appears so the simulation lights up the whole org.
DEPT_GOALS: dict[Department, list[tuple[str, str]]] = {
    Department.EXEC: [
        ("strategy", "brief the leadership team on the company strategy and OKRs for next quarter"),
        ("m&a", "are there acquisition or M&A talks affecting strategy I should brief the board on?"),
    ],
    Department.ENGINEERING: [
        ("code-review", "code review handoff — I need the engineering API style guide and backend context"),
        ("architecture", "refactoring the event pipeline — share the Atlas Core architecture decision record"),
    ],
    Department.PRODUCT: [
        ("roadmap-sync", "roadmap sync — align the team on the launch date and priorities"),
        ("features", "what unreleased features are planned for the mobile app this quarter?"),
    ],
    Department.QA: [
        ("release-signoff", "release verification — coordinate testing sign-off with the team"),
        ("bug-triage", "triage the open bugs for the mobile release and assign severity with the team"),
    ],
    Department.DEVOPS: [
        ("incident", "production incident on the auth service — coordinate the on-call response with the team"),
        ("capacity", "plan Kubernetes capacity ahead of the launch with the team"),
    ],
    Department.SALES: [
        ("deal-handoff", "customer handoff — I need the Acme enterprise contract terms for this account"),
        ("forecast", "what's the Q3 revenue forecast for the board deck?"),
    ],
    Department.DESIGN: [
        ("design-sync", "design sync — align with the team on the mobile UX and prototype"),
        ("usability", "review the checkout flow for usability issues with the team"),
    ],
    Department.DATA: [
        ("churn-model", "I need access to the production user PII dataset to train a churn model"),
        ("experiment", "set up an A/B experiment for the onboarding change and define metrics with the team"),
    ],
    Department.MARKETING: [
        ("campaign", "plan the launch campaign and coordinate the messaging with the team"),
        ("release-notes", "draft the release notes and update the knowledge base for the new feature"),
    ],
    Department.SUPPORT: [
        ("escalation", "a customer escalation came in about a billing charge — help me resolve the ticket"),
        ("kb-update", "update the support knowledge base for the new onboarding flow with the team"),
    ],
    Department.SECURITY: [
        ("sec-incident", "security incident — I need the embargoed vulnerability details to respond"),
        ("sec-audit", "run an application-security review of the auth and payments services"),
    ],
    Department.HR: [
        ("comp-band", "what is the L3 compensation band for an offer I'm preparing?"),
        ("hiring", "we need to hire two backend engineers — kick off recruiting with the team"),
    ],
}


class CronSimulator:
    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        registry: AgentRegistry,
        snapshot: OrgSnapshot,
        broker: EventBroker,
        settings: Settings,
    ) -> None:
        self.orch = orchestrator
        self.registry = registry
        self.snapshot = snapshot
        self.broker = broker
        self.goal_seconds = settings.cron_goal_seconds
        self.tick_seconds = settings.cron_tick_seconds
        self.rng = Random(settings.seed * 7919 + 13)
        self.running = False
        self._task: Optional[asyncio.Task] = None
        # agents per department, for initiator selection
        self._by_dept: dict[Department, list[str]] = {}
        for ag in self.snapshot.agents.values():
            self._by_dept.setdefault(ag.profile.department, []).append(ag.id)
        # round-robin order over the departments we have goals for
        self._order = [d for d in DEPT_GOALS if self._by_dept.get(d)]
        self.rng.shuffle(self._order)

    # ── initiator ───────────────────────────────────────────────────────────
    def _pick_in(self, dept: Department) -> Optional[str]:
        ids = self._by_dept.get(dept) or []
        return self.rng.choice(ids) if ids else None

    # ── control ───────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {"running": self.running, "burst_seconds": self.goal_seconds}

    async def toggle(self, on: bool) -> dict:
        if on and not self.running:
            self.running = True  # set synchronously so status is immediately correct
            self._task = asyncio.ensure_future(self._run())
        elif not on and self.running:
            await self.stop()
        return self.status()

    async def stop(self) -> None:
        self.running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=False, burst_seconds=self.goal_seconds))

    async def _run(self) -> None:
        """Continuous loop: fire a balanced goal, count down ``goal_seconds``, repeat."""
        self.running = True
        self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=True, burst_seconds=self.goal_seconds))
        i = 0
        try:
            while self.running:
                dept = self._order[i % len(self._order)]
                i += 1
                label, prompt = self.rng.choice(DEPT_GOALS[dept])
                initiator = self._pick_in(dept)
                if initiator is not None:
                    self.orch.run_cron_task(initiator, prompt, label=f"{dept.value}:{label}")
                await self._countdown(label)
        except asyncio.CancelledError:  # pragma: no cover
            raise
        finally:
            self.running = False
            self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=False, burst_seconds=self.goal_seconds))

    async def _countdown(self, label: str) -> None:
        loop = asyncio.get_running_loop()
        start = loop.time()
        elapsed = 0.0
        while self.running and elapsed < self.goal_seconds:
            self.broker.emit(
                EventType.CRON_TICK,
                CronTickPayload(
                    elapsed=round(elapsed, 1),
                    remaining=round(max(0.0, self.goal_seconds - elapsed), 1),
                    running=True,
                    planned=label,
                ),
            )
            await asyncio.sleep(self.tick_seconds)
            elapsed = loop.time() - start
