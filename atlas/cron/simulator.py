"""The cron simulation engine.

When toggled on, runs a ~15s burst where agents autonomously initiate tasks and
communicate — a stand-in for manual user prompts. Crucially it drives the
*identical* orchestrator pipeline, so policy, redaction, and HITL are enforced
exactly as on the interactive path (escalations land in the same operator queue).
It uses the same LLM as the interactive path — real Groq when a key is set,
deterministic templates otherwise — while the burst sequence itself is seeded.
"""

from __future__ import annotations

import asyncio
import contextlib
from random import Random
from typing import Callable, Optional

from atlas.bus.registry import AgentRegistry
from atlas.config import Settings
from atlas.conversation.orchestrator import Orchestrator
from atlas.events import CronStatePayload, CronTickPayload, EventBroker, EventType
from atlas.org.ext_models import Department, Level
from atlas.org.generator import OrgSnapshot

# (label, prompt) — the prompt's wording decides individual vs group via the
# orchestrator's group-word heuristic.
Archetype = tuple[str, str, Callable[["CronSimulator"], Optional[str]]]


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
        self.burst_seconds = settings.cron_burst_seconds
        self.tick_seconds = settings.cron_tick_seconds
        self.loop_forever = settings.cron_loop
        self.rng = Random(settings.seed * 7919 + 13)
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._pools = self._build_pools()
        self._weighted = self._build_weighted_archetypes()

    # ── pools ─────────────────────────────────────────────────────────────
    def _ids(self, *, dept=None, level=None, project=None) -> list[str]:
        out = []
        for ag in self.snapshot.agents.values():
            p = ag.profile
            if dept is not None and p.department != dept:
                continue
            if level is not None and p.level != level:
                continue
            if project is not None and project not in p.projects:
                continue
            out.append(ag.id)
        return out

    def _build_pools(self) -> dict[str, list[str]]:
        return {
            "eng_ic": self._ids(dept=Department.ENGINEERING, level=Level.IC),
            "billing_eng": self._ids(dept=Department.ENGINEERING, level=Level.IC, project="billing"),
            "mobile_eng": self._ids(dept=Department.ENGINEERING, level=Level.IC, project="mobile"),
            "devops_ic": self._ids(dept=Department.DEVOPS, level=Level.IC),
            "product": self._ids(dept=Department.PRODUCT),
            "sales_ic": self._ids(dept=Department.SALES, level=Level.IC),
            "hr_ic": self._ids(dept=Department.HR, level=Level.IC),
            "qa_ic": self._ids(dept=Department.QA, level=Level.IC),
            "design_ic": self._ids(dept=Department.DESIGN, level=Level.IC),
            "security_ic": self._ids(dept=Department.SECURITY, level=Level.IC),
        }

    def _pick(self, pool: str) -> Optional[str]:
        ids = self._pools.get(pool) or []
        return self.rng.choice(ids) if ids else None

    # ── archetypes ────────────────────────────────────────────────────────
    def _build_weighted_archetypes(self) -> list[Archetype]:
        a: list[Archetype] = [
            ("standup", "team standup sync — share status and blockers with the team", lambda s: s._pick("eng_ic")),
            ("incident", "production incident — coordinate the on-call response with the team", lambda s: s._pick("devops_ic")),
            ("code-review", "code review handoff — I need the engineering api style guide and backend context", lambda s: s._pick("eng_ic")),
            ("roadmap-sync", "roadmap sync — align the team on the launch date and priorities", lambda s: s._pick("product")),
            ("sales-handoff", "customer handoff — I need the acme enterprise contract terms for this account", lambda s: s._pick("sales_ic")),
            ("design-sync", "design sync — align with the team on the mobile UX and prototype", lambda s: s._pick("design_ic")),
            ("qa-release", "release verification — coordinate testing sign-off with the team", lambda s: s._pick("qa_ic")),
            # rarer, sensitive ones that trigger redaction / HITL:
            ("billing-secret", "I need the billing stripe payment credentials to wire the integration", lambda s: s._pick("billing_eng")),
            ("comp-question", "what is the L3 compensation band for an offer I'm preparing", lambda s: s._pick("hr_ic")),
            ("security-incident", "security incident — I need the embargoed vulnerability details to respond", lambda s: s._pick("security_ic")),
        ]
        # weight the common (first 7) more heavily than the sensitive (last 3)
        weights = [3, 3, 3, 3, 3, 3, 3, 1, 1, 1]
        weighted: list[Archetype] = []
        for arche, w in zip(a, weights):
            weighted.extend([arche] * w)
        return weighted

    # ── control ───────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {"running": self.running, "burst_seconds": self.burst_seconds}

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
        self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=False, burst_seconds=self.burst_seconds))

    async def _run(self) -> None:
        self.running = True
        self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=True, burst_seconds=self.burst_seconds))
        try:
            while True:
                await self._one_burst()
                if not self.loop_forever:
                    break
        except asyncio.CancelledError:  # pragma: no cover
            raise
        finally:
            self.running = False
            self.broker.emit(EventType.CRON_STATE, CronStatePayload(running=False, burst_seconds=self.burst_seconds))

    async def _one_burst(self) -> None:
        loop = asyncio.get_running_loop()
        start = loop.time()
        elapsed = 0.0
        while self.running and elapsed < self.burst_seconds:
            label, prompt, picker = self.rng.choice(self._weighted)
            initiator = picker(self)
            self.broker.emit(
                EventType.CRON_TICK,
                CronTickPayload(
                    elapsed=round(elapsed, 1),
                    remaining=round(max(0.0, self.burst_seconds - elapsed), 1),
                    running=True,
                    planned=label,
                ),
            )
            if initiator is not None:
                self.orch.run_cron_task(initiator, prompt)
            await asyncio.sleep(self.tick_seconds)
            elapsed = loop.time() - start
