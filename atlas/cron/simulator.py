"""The cron simulation engine.

When toggled on, agents autonomously launch goals and work each through the
*identical* orchestrator pipeline, so policy, redaction, and HITL are enforced
exactly as on the interactive path (escalations land in the same operator queue).
Goals are **balanced across all departments** (round-robin), so activity isn't
concentrated in Engineering. The sequence is seeded for reproducibility; message
phrasing uses the same real Mistral (Amazon Bedrock) as the interactive path.

Two modes (``settings.cron_loop``):

* **burst** (default) — a single ~``cron_burst_seconds`` (15s) window of activity,
  firing several goals across the window, then **auto-stops**. This is the spec's
  "cron job — when it is turned on for 15 seconds" simulation.
* **continuous** — keeps launching one goal every ``cron_goal_seconds`` until
  toggled off.
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
        self.loop_mode = settings.cron_loop          # True = continuous, False = 15s burst
        self.burst_seconds = settings.cron_burst_seconds
        self.goal_seconds = settings.cron_goal_seconds
        self.tick_seconds = settings.cron_tick_seconds
        # In burst mode, pace goals so several fire across the window (≈5).
        self.burst_gap = max(self.tick_seconds, self.burst_seconds / 5.0)
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
    @property
    def _window(self) -> float:
        """The countdown the UI shows: the burst window, or the inter-goal gap."""
        return self.goal_seconds if self.loop_mode else self.burst_seconds

    @property
    def _mode(self) -> str:
        return "continuous" if self.loop_mode else "burst"

    def status(self) -> dict:
        return {"running": self.running, "mode": self._mode, "burst_seconds": self._window}

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
        self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=False, burst_seconds=self._window, mode=self._mode))

    async def _run(self) -> None:
        """Fire balanced goals. Burst mode stops after ``burst_seconds``; continuous
        mode keeps going until toggled off. In-flight scenarios are load-shed by the
        orchestrator and finish on their own after the burst window closes."""
        self.running = True
        self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=True, burst_seconds=self._window, mode=self._mode))
        loop = asyncio.get_running_loop()
        start = loop.time()
        gap = self.goal_seconds if self.loop_mode else self.burst_gap
        i = 0
        try:
            while self.running:
                # Burst mode: stop launching new goals once the 15s window elapses.
                if not self.loop_mode and (loop.time() - start) >= self.burst_seconds:
                    break
                dept = self._order[i % len(self._order)]
                i += 1
                label, prompt = self.rng.choice(DEPT_GOALS[dept])
                initiator = self._pick_in(dept)
                if initiator is not None:
                    self.orch.run_cron_task(initiator, prompt, label=f"{dept.value}:{label}")
                await self._countdown(label, gap, burst_start=None if self.loop_mode else start)
        except asyncio.CancelledError:  # pragma: no cover
            raise
        finally:
            self.running = False
            self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=False, burst_seconds=self._window, mode=self._mode))

    async def _countdown(self, label: str, gap: float, *, burst_start: Optional[float]) -> None:
        """Tick until ``gap`` elapses (or, in burst mode, the burst window ends).

        The ``remaining`` shown to the UI is the overall burst countdown in burst
        mode, and the per-goal gap countdown in continuous mode.
        """
        loop = asyncio.get_running_loop()
        start = loop.time()
        elapsed = 0.0
        while self.running and elapsed < gap:
            if burst_start is not None:
                burst_elapsed = loop.time() - burst_start
                if burst_elapsed >= self.burst_seconds:
                    break
                remaining = max(0.0, self.burst_seconds - burst_elapsed)
            else:
                remaining = max(0.0, gap - elapsed)
            self.broker.emit(
                EventType.CRON_TICK,
                CronTickPayload(
                    elapsed=round(elapsed, 1),
                    remaining=round(remaining, 1),
                    running=True,
                    planned=label,
                ),
            )
            await asyncio.sleep(self.tick_seconds)
            elapsed = loop.time() - start
