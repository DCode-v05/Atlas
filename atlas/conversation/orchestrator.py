"""The orchestrator — the scenario engine that drives every conversation.

It runs the SAME pipeline for a user prompt and for a cron-simulated task:

    route → identify context needs → discover sources (level 2) →
    for each source: ask (with intent) → policy decides → share / redact /
    deny / escalate-to-HITL → remember → finalize the task.

Real Mistral (Amazon Bedrock) is the engine on BOTH paths and is required: it
judges the org-scope gate, routes to an owner from the full directory, decides
whether to coordinate as a group, authors every agent message, and makes the
need-to-know decision itself (the owner agent chooses share / redact / deny /
escalate). There are NO templates — a message is genuine Mistral or it is
omitted. The deterministic policy matrix and skill-scorer survive only as an
offline fallback (traced live=False) for when the LLM is unreachable. Secret
payloads are appended verbatim — the LLM authors the prose, code guarantees the
exact value is present.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from atlas.a2a.ids import new_id
from atlas.a2a.models import TERMINAL_STATES, Artifact, DataPart, FilePart, Task, TaskState, TextPart
from atlas.bus.discovery import tokenize
from atlas.bus.registry import AgentRegistry
from atlas.bus.router import GATE_REASON, Router
from atlas.conversation.intent import build_request_intent, coordination_intent
from atlas.conversation.stores import GroupStore, ThreadStore
from atlas.events import (
    ContextSharePayload,
    CrossOrgExchangePayload,
    EventBroker,
    EventType,
    MessageSentPayload,
    PromptAcceptedPayload,
)
from atlas.hitl.queue import HitlQueue
from atlas.llm.base import LLMProvider
from atlas.metrics.collector import MetricsCollector
from atlas.org.agent import AgentStatus, LearnedFact, OrgAgent
from atlas.org.ext_models import (
    ContextItem,
    CoordinationMode,
    Department,
    HitlRequest,
    Intent,
    ShareDecision,
    ShareOutcome,
)
from atlas.org.generator import OrgSnapshot
from atlas.policy import PolicyEngine

USER_NODE = "operator"


def _clip(s: str, n: int = 88) -> str:
    """Word-boundary truncation with an ellipsis (no broken mid-word cuts)."""
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _build_llm_decision(item: ContextItem, outcome: ShareOutcome, reason: str,
                        rule_id: str = "LLM-OWNER") -> ShareDecision:
    """Wrap an agent's LLM share decision into a ShareDecision (fills the delivered
    body for SHARE/REDACT so the exact value never depends on the model's wording)."""
    body = None
    if outcome == ShareOutcome.SHARE:
        body = item.body
    elif outcome == ShareOutcome.REDACT:
        body = item.redacted_summary or f"[redacted: {item.title}]"
    return ShareDecision(
        outcome=outcome, reason=reason, item_id=item.item_id, rule_id=rule_id,
        sensitivity=item.sensitivity, delivered_title=item.title, delivered_body=body,
    )


GROUP_WORDS = frozenset(
    {
        "team", "standup", "sync", "coordinate", "coordination", "align", "alignment",
        "everyone", "group", "meeting", "plan", "planning", "retro", "kickoff",
        "incident", "all", "together", "collaborate",
    }
)


class Orchestrator:
    def __init__(
        self,
        *,
        snapshot: OrgSnapshot,
        registry: AgentRegistry,
        router: Router,
        broker: EventBroker,
        metrics: MetricsCollector,
        hitl: HitlQueue,
        threads: ThreadStore,
        groups: GroupStore,
        llm: LLMProvider,
        trace=None,
        hitl_timeout: float = 0.0,
        step_delay: float = 0.45,
        cron_max_inflight: int = 3,
        network=None,
    ) -> None:
        self.snapshot = snapshot
        self.registry = registry
        self.router = router
        self.broker = broker
        self.metrics = metrics
        self.hitl = hitl
        self.threads = threads
        self.groups = groups
        self.llm = llm
        self.trace = trace
        self.hitl_timeout = hitl_timeout
        self.step_delay = step_delay
        self.cron_max_inflight = cron_max_inflight
        self.network = network  # NetworkService when the authenticated-network mode is live, else None
        self.federation = None  # FederationGateway when this org is part of a federation, else None
        self.dbwriter = None  # set by build_runtime; durable write-through when persistence is on
        self._pending_auth: dict[str, list[dict]] = {}  # agent_id -> tasks parked auth-required until it joins
        self._cron_active = 0
        self._bg: set[asyncio.Task] = set()
        self._scenarios: dict[str, asyncio.Task] = {}  # task_id -> running scenario (for cancel)
        # The deterministic compliance Policy Engine reviews every owner share decision
        # (tighten-only). The Security department head is the compliance authority it runs
        # under (trace attribution); None if the org has no such head.
        self.policy = PolicyEngine()
        try:
            self._policy_officer_id: Optional[str] = snapshot.head_of(Department.SECURITY)
        except KeyError:
            self._policy_officer_id = None

    # ── network membership (gating is OFF unless the authenticated network is live) ──
    def _gating(self) -> bool:
        return self.network is not None and getattr(self.network, "active", False)

    def _is_member(self, agent_id: str) -> bool:
        return (not self._gating()) or self.network.is_member(agent_id)

    def _pool_ids(self) -> Optional[set]:
        """The agent ids allowed to communicate (joined network members), or None = all."""
        return self.network.member_ids() if self._gating() else None

    # ── public entry points ────────────────────────────────────────────────
    def _org_summary(self) -> str:
        """A concise description of the company for the LLM scope gate to judge against."""
        depts = ", ".join(sorted(self.snapshot.departments.keys()))
        projects = ", ".join(sorted(self.snapshot.projects.keys()))
        return (
            f"Atlas, a software product company. Departments: {depts}. "
            f"Active projects: {projects}. Its agents only hold and discuss internal "
            f"company context — people, teams, projects, products, data, and operations."
        )

    async def run_user_prompt(
        self, prompt: str, human_name: str = "Operator", reference_task_ids: Optional[list[str]] = None,
        acting_agent_id: Optional[str] = None,
    ) -> dict:
        """Gate + route (LLM re-rank when available), then run the scenario async."""
        ok, reason = self.router.org_scope_gate(prompt)
        # Authoritative LLM semantic gate: Mistral judges company-relevance on
        # every prompt it can reach, overriding the cheap lexical pre-check (so
        # "write a python script for wifi" is refused despite sharing the word
        # "python" with engineering's skills). If the LLM is unavailable or the
        # call fails/throttles, we fall back to the lexical verdict above.
        gate_live = False
        if self.llm.available:
            verdict = await self.llm.judge_scope(prompt, org_summary=self._org_summary())
            gate_live = verdict is not None
            if verdict is True:
                ok, reason = True, ""
            elif verdict is False:
                ok, reason = False, GATE_REASON
        if not ok:
            self.router.reject(prompt, reason or GATE_REASON)
            return {"rejected": True, "reason": reason or GATE_REASON}
        # Network membership: routing/communication is restricted to agents that have
        # authenticated to the network. An empty network has no one to route to.
        pool = self._pool_ids()  # None = gating off (all agents); else the joined-member set
        if pool is not None and not pool:
            msg = "No agents are in the network yet — authenticate one or more agents to the network first."
            self.router.reject(prompt, msg)
            return {"rejected": True, "reason": msg}

        # auth-required: when the prompt is issued AS a specific agent that has NOT joined the
        # network, the CALLER must authenticate first — park the task `auth-required`; it resumes
        # the moment that agent joins (resume_pending_auth, wired to the network-join hook).
        if acting_agent_id and self._gating() and not self.network.is_member(acting_agent_id):
            context_id = new_id("ctx-")
            task = self.router.new_task(context_id, message=prompt, reference_task_ids=reference_task_ids)
            actor = self.registry.get(acting_agent_id).name if acting_agent_id in self.registry.agents else acting_agent_id
            self.router.set_task_state(
                task, TaskState.AUTH_REQUIRED, message=f"{actor} must authenticate to the network before this task can run.")
            self._pending_auth.setdefault(acting_agent_id, []).append(
                {"task_id": task.id, "context_id": context_id, "prompt": prompt, "human": human_name})
            return {"rejected": False, "auth_required": True, "task_id": task.id, "context_id": context_id,
                    "state": "auth-required", "acting_agent": acting_agent_id}

        # Network-scope gate: when membership gating is on, the prompt must be answerable by an
        # agent that is actually IN the network. If the relevant team hasn't joined, no member is
        # a plausible owner, so it's out of scope for the CURRENT network — reject rather than
        # force it onto an unrelated member. (Skipped when gating is off: the whole org is available.)
        if pool is not None and set(tokenize(prompt)):
            _, member_scored = self.router.route_prompt(prompt, pool_ids=pool)
            if not member_scored or member_scored[0][1] < self.router.gate_floor:
                # No LOCAL member fits. Auto-fallback: a PEER org in the federation may have joined
                # members for this topic — route across the boundary, where only PUBLIC information
                # may cross. (Falls through to the original rejection when no peer fits either.)
                peer = (
                    self.federation.route_to_peer(
                        prompt, exclude_org_id=self.snapshot.org_id, gate_floor=self.router.gate_floor)
                    if self.federation is not None else None
                )
                if peer is not None:
                    context_id = new_id("ctx-")
                    task = self.router.new_task(context_id, message=prompt, reference_task_ids=reference_task_ids)
                    # the requester is the best LOCAL joined member (so the cross-org ask respects
                    # this org's membership — the peer owner is exempted only for transport)
                    requester_id = member_scored[0][0] if member_scored else next(iter(pool))
                    self._spawn(self._run_cross_org_request(prompt, context_id, task, peer[0], requester_id=requester_id),
                                task_id=task.id)
                    rep = self.federation.org(peer[0])
                    return {"rejected": False, "task_id": task.id, "context_id": context_id,
                            "cross_org": True, "routed_to_org": peer[0], "routed_to_org_name": rep.org_name}
                msg = ("No agent currently in the network can handle this request — the team it "
                       "needs hasn’t joined the network yet.")
                self.router.reject(prompt, msg)
                return {"rejected": True, "reason": msg}

        context_id = new_id("ctx-")
        task = self.router.new_task(context_id, message=prompt, reference_task_ids=reference_task_ids)
        return await self._accept_and_run(prompt, context_id, task, pool, human_name, gate_live=gate_live)

    async def _accept_and_run(
        self, prompt: str, context_id: str, task: Task, pool, human_name: str, *, gate_live: bool = False
    ) -> dict:
        """Route within ``pool``, announce the task (prompt.accepted + conversation header), and
        spawn the scenario/greeting on the given context/task. Shared by a fresh prompt and an
        auth-required resume (see ``_resume_auth``)."""
        def _fallback_agent() -> str:
            return self.snapshot.ceo_id if (pool is None or self.snapshot.ceo_id in pool) else next(iter(pool))

        # Routing is LLM-decided: Mistral reads the directory (restricted to network members when
        # gating is on); the deterministic scorer is the fallback when the LLM is down.
        greeting = not set(tokenize(prompt))
        route_live = False
        if greeting:
            chosen = _fallback_agent()
        else:
            chosen = None
            if self.llm.available:
                try:
                    pick = await self.llm.route(prompt, self._agent_directory(pool))
                    if pick in self.registry.agents and (pool is None or pick in pool):
                        chosen = pick
                        route_live = True
                except Exception:
                    chosen = None
            if chosen is None:  # LLM unavailable / invalid pick → deterministic safety net
                chosen, _ = self.router.route_prompt(prompt, pool_ids=pool)
            if chosen is None:  # nothing matched even deterministically → treat as social
                greeting = True
                chosen = _fallback_agent()
        scored = [(chosen, 1.0)]

        agent = self.registry.get(chosen)
        self._trace(USER_NODE, "judge_scope", f'admitted — “{_clip(prompt)}”', live=gate_live, context_id=context_id)
        self._trace(chosen, "route", f'routed here — “{_clip(prompt)}”', live=route_live, context_id=context_id,
                    detail="Mistral chose this agent from all 100 cards" if route_live else "deterministic fallback")
        self.router.emit_discovery(
            level=1, query=prompt, scored=scored, chosen=chosen, requester=USER_NODE, context_id=context_id
        )
        self.broker.emit(
            EventType.PROMPT_ACCEPTED,
            PromptAcceptedPayload(
                prompt=prompt, task_id=task.id, context_id=context_id,
                routed_to=chosen, routed_to_name=agent.name,
            ),
            context_id=context_id,
        )
        if self.dbwriter is not None:  # persist the conversation header so it survives a refresh/restart
            self.dbwriter.record("conversation", {
                "context_id": context_id, "prompt": prompt, "kind": "user",
                "routed_to": chosen, "routed_to_name": agent.name, "task_id": task.id,
            })
        self._spawn(
            self._run_greeting(prompt, chosen, context_id, task.id) if greeting
            else self._run_scenario(prompt, chosen, context_id, task.id),
            task_id=task.id,
        )
        return {
            "rejected": False, "task_id": task.id, "context_id": context_id,
            "routed_to": chosen, "routed_to_name": agent.name,
            "routed_to_role": agent.profile.role_title,
        }

    def resume_pending_auth(self, agent_id: str) -> None:
        """Network-join hook: resume every task parked ``auth-required`` on this agent joining."""
        for p in self._pending_auth.pop(agent_id, []):
            self._spawn(self._resume_auth(p))

    async def _resume_auth(self, p: dict) -> None:
        task = self.router.tasks.get(p["task_id"])
        if task is None or task.status.state != TaskState.AUTH_REQUIRED:
            return  # canceled / already resumed
        self.router.set_task_state(task, TaskState.WORKING, message="Authenticated — resuming.")
        await self._accept_and_run(p["prompt"], p["context_id"], task, self._pool_ids(), p["human"])

    def run_cron_task(self, initiator_id: str, prompt: str, *, label: Optional[str] = None) -> Optional[str]:
        """Autonomous goal initiated by an agent (cron simulation). Load-sheds when
        too many scenarios are already in flight — this is what keeps the LLM call
        volume (and rate-limit pressure) bounded. NOTE: the cron path deliberately
        does NOT run the LLM scope gate (goals are in-scope by construction), so it
        never spends a gate call against the rate-limit budget."""
        if self._cron_active >= self.cron_max_inflight:
            return None
        if not self._is_member(initiator_id):
            return None  # only agents authenticated to the network initiate goals
        self._cron_active += 1
        context_id = new_id("cron-")
        task = self.router.new_task(context_id, message=prompt, role="agent")
        agent = self.registry.get(initiator_id)
        # Surface the goal so the conversation timeline can show a "goal opened"
        # header (initiator = the agent that autonomously launched it).
        self.broker.emit(
            EventType.PROMPT_ACCEPTED,
            PromptAcceptedPayload(
                prompt=prompt, task_id=task.id, context_id=context_id,
                routed_to=initiator_id, routed_to_name=agent.name,
            ),
            context_id=context_id,
        )
        if self.dbwriter is not None:
            self.dbwriter.record("conversation", {
                "context_id": context_id, "prompt": prompt, "kind": "cron",
                "routed_to": initiator_id, "routed_to_name": agent.name, "task_id": task.id,
            })
        self._spawn(self._run_scenario(prompt, initiator_id, context_id, task.id, cron=True), task_id=task.id)
        return context_id

    # ── scenario ────────────────────────────────────────────────────────────
    async def _run_scenario(
        self, prompt: str, agent_id: str, context_id: str, task_id: str, *, cron: bool = False
    ) -> None:
        task = self.router.tasks[task_id]
        agent = self.registry.get(agent_id)
        try:
            self.metrics.record_hop(context_id, agent_id)
            self.router.set_status(agent_id, AgentStatus.THINKING)
            self.router.set_task_state(task, TaskState.WORKING)
            await self._pause()

            needs = self._identify_needs(agent, prompt)
            needs = [(it, rel) for (it, rel) in needs if self._is_member(it.owner_agent_id)]  # source only from members
            group_members = await self._decide_group(agent, prompt, context_id)
            grouped = bool(group_members)

            if grouped:
                await self._run_group(agent, prompt, context_id, task_id, member_ids=group_members)

            if needs:
                topic = needs[0][0].title
                scored2 = [(it.owner_agent_id, float(rel)) for it, rel in needs]
                self.router.emit_discovery(
                    level=2, query=topic, scored=scored2, chosen=None, requester=agent_id, context_id=context_id
                )
                await self._gather_individual(agent, needs, context_id, task_id)
            elif not grouped:
                await self._consult_manager(agent, prompt, context_id, task_id)

            await self._finalize(agent, prompt, context_id, task_id)
        except Exception as exc:  # pragma: no cover - safety net
            self.router.set_task_state(task, TaskState.FAILED, message=f"scenario error: {exc}")
            self.router.set_status(agent_id, AgentStatus.IDLE)
            import traceback

            traceback.print_exc()
        finally:
            if cron:
                self._cron_active = max(0, self._cron_active - 1)

    async def _finalize(self, agent: OrgAgent, prompt: str, context_id: str, task_id: str) -> None:
        task = self.router.tasks[task_id]
        m = self.metrics.ctx(context_id)
        self.router.set_status(agent.id, AgentStatus.SPEAKING)
        await self._pause()
        summary = await self._say(
            "summary",
            {"agent": agent.name, "prompt": prompt, "shared": m.items_shared, "redacted": m.items_redacted,
             "denied": m.items_denied, "hitl": m.hitl_escalations},
        )
        if summary:  # omit the closing message if the LLM couldn't author it
            self.broker.emit(
                EventType.MESSAGE_SENT,
                MessageSentPayload(
                    message_id=new_id("msg-"), context_id=context_id, sender=agent.id,
                    recipients=[USER_NODE], mode=CoordinationMode.INDIVIDUAL.value, role="agent", text=summary,
                ),
                context_id=context_id,
            )
            task.artifacts.append(Artifact(
                name="summary",
                parts=[
                    TextPart(text=summary),
                    # a structured, machine-readable outcome record — a real DataPart on a live path
                    DataPart(data={"owner": agent.id, "prompt": prompt, "metrics": m.model_dump(mode="json")}),
                    # a URL reference to the owner's A2A card (the URL-only FilePart variant)
                    FilePart.from_uri(
                        agent.card.url or f"atlas://agent/{agent.id}",
                        mimeType="application/json", name=f"{agent.id}-agent-card.json",
                    ),
                ],
            ))
        self.router.set_task_state(task, TaskState.COMPLETED, message=summary)
        self.router.set_status(agent.id, AgentStatus.IDLE)
        self.metrics.emit(context_id)

    async def _run_greeting(self, prompt: str, agent_id: str, context_id: str, task_id: str) -> None:
        """A greeting / social message the gate admitted but that needs no task work
        — the agent simply replies, warmly, in one real Mistral-authored line."""
        task = self.router.tasks[task_id]
        agent = self.registry.get(agent_id)
        try:
            self.metrics.record_hop(context_id, agent_id)
            self.router.set_status(agent_id, AgentStatus.SPEAKING)
            self.router.set_task_state(task, TaskState.WORKING)
            await self._pause()
            text = await self._say("greeting", {"agent": agent.name, "prompt": prompt})
            if text:
                self.broker.emit(
                    EventType.MESSAGE_SENT,
                    MessageSentPayload(
                        message_id=new_id("msg-"), context_id=context_id, sender=agent_id,
                        recipients=[USER_NODE], mode=CoordinationMode.INDIVIDUAL.value, role="agent", text=text,
                    ),
                    context_id=context_id,
                )
            self.router.set_task_state(task, TaskState.COMPLETED, message=text)
        except Exception as exc:  # pragma: no cover - safety net
            self.router.set_task_state(task, TaskState.FAILED, message=f"greeting error: {exc}")
        finally:
            self.router.set_status(agent_id, AgentStatus.IDLE)
            self.metrics.emit(context_id)

    # ── needs / grouping heuristics ─────────────────────────────────────────
    def _identify_needs(self, agent: OrgAgent, prompt: str) -> list[tuple[ContextItem, float]]:
        q = set(tokenize(prompt)) | set(tokenize(agent.profile.role_title))
        scored: list[tuple[ContextItem, float]] = []
        for item in self.snapshot.items.values():
            if item.owner_agent_id == agent.id:
                continue
            rel = 2.0 * len(q & set(item.topic_tags))
            if item.scope_ref and (item.scope_ref in agent.profile.projects or item.scope_ref in agent.profile.teams):
                rel += 1.0
            if rel > 0:
                scored.append((item, rel))
        scored.sort(key=lambda x: (-x[1], x[0].item_id))
        return scored[:3]

    def _should_group(self, agent: OrgAgent, prompt: str) -> bool:
        return bool(set(tokenize(prompt)) & GROUP_WORDS) and bool(agent.profile.teams)

    async def _decide_group(self, agent: OrgAgent, prompt: str, context_id: Optional[str] = None) -> list[str]:
        """LLM decides whether to coordinate as a group and WHICH teammates to pull
        in (a subset of the agent's REAL team roster — the model never invents
        people). Falls back to the keyword heuristic + whole team if the LLM is
        unavailable / undecided. Returns the member ids to involve ([] = solo)."""
        if not agent.profile.teams:
            return []
        team_id = agent.profile.teams[0]
        roster_ids = [m for m in self.snapshot.teams.get(team_id, []) if m != agent.id and self._is_member(m)]
        if not roster_ids:
            return []
        if self.llm.available:
            roster = [
                (rid, self.registry.get(rid).name, self.registry.get(rid).profile.role_title)
                for rid in roster_ids
            ]
            try:
                sel = await self.llm.judge_group(prompt, roster)
            except Exception:
                sel = None
            if sel is not None:  # LLM decided — keep only valid roster ids
                members = [s for s in sel if s in roster_ids]
                self._trace(agent.id, "judge_group",
                            f"coordinate {len(members)} teammate(s)" if members else "handle solo (1:1)",
                            live=True, context_id=context_id)
                return members
        # fallback: deterministic keyword heuristic → coordinate the whole team
        return roster_ids if self._should_group(agent, prompt) else []

    # ── individual sourcing ─────────────────────────────────────────────────
    async def _gather_individual(
        self, agent: OrgAgent, needs: list[tuple[ContextItem, float]], context_id: str, task_id: str
    ) -> None:
        task = self.router.tasks[task_id]
        for item, _rel in needs:
            owner = self.registry.get(item.owner_agent_id)
            if owner.id == agent.id:
                continue
            if agent.knows(item.item_id, raw_required=True):
                self.metrics.record_redundant_avoided(context_id)
                self.broker.emit(
                    EventType.CONTEXT_REUSED,
                    ContextSharePayload(
                        context_id=context_id, item_id=item.item_id, title=item.title,
                        sender=owner.id, recipient=agent.id, sensitivity=item.sensitivity.value,
                        rule_id="REUSE", reason="Requester already holds this at sufficient fidelity — contact skipped.",
                    ),
                    context_id=context_id,
                )
                continue

            intent = build_request_intent(agent.profile, item, task_ref=task_id)
            thread, created = self.threads.get_or_create(
                context_id, agent.id, owner.id, topic=item.title, task_id=task_id
            )
            if created:
                self.router.announce_thread(thread)

            self.router.set_status(owner.id, AgentStatus.THINKING)
            await self._pause()
            msg = await self._send_say(
                "request",
                {"requester": agent.name, "owner": owner.name, "item": item.title, "motivation": intent.motivation},
                context_id=context_id, sender=agent.id, recipients=[owner.id], intent=intent,
                thread_id=thread.thread_id, task=task,
            )
            if msg:
                thread.message_ids.append(msg.messageId)

            decision = await self._decide_share(agent, owner, item, intent, context_id)
            self.metrics.record_decision(context_id, decision.outcome)
            await self._apply_decision(
                decision, agent, owner, item, intent, context_id, task_id,
                mode=CoordinationMode.INDIVIDUAL, thread_id=thread.thread_id,
            )
            self.router.set_status(owner.id, AgentStatus.IDLE)

    async def _apply_decision(
        self, decision, agent: OrgAgent, owner: OrgAgent, item: ContextItem, intent: Intent,
        context_id: str, task_id: str, *,
        mode: CoordinationMode = CoordinationMode.INDIVIDUAL,
        thread_id: str | None = None, group_id: str | None = None,
        recipients: list[str] | None = None,
    ) -> None:
        task = self.router.tasks[task_id]
        out = decision.outcome
        to = recipients or [agent.id]
        if out == ShareOutcome.ESCALATE:
            await self._handle_hitl(
                decision, agent, owner, item, intent, context_id, task_id,
                mode=mode, thread_id=thread_id, group_id=group_id, recipients=to,
            )
            return

        self.router.set_status(owner.id, AgentStatus.SPEAKING)
        await self._pause(0.5)
        names = {"owner": owner.name, "requester": agent.name, "item": item.title}
        # The decision + its effects (remember / metrics / context event) are
        # deterministic and always recorded; only the spoken reply depends on the
        # LLM and is omitted if it can't be authored.
        if out == ShareOutcome.SHARE:
            body = decision.delivered_body or ""
            agent.remember(LearnedFact(item.item_id, item.title, body, item.sensitivity, False, owner.id))
            self.metrics.record_hop(context_id, owner.id)
            self._emit_context(EventType.CONTEXT_SHARED, context_id, item, owner, agent, decision)
            await self._send_say("reply_share", {**names, "body": body}, context_id=context_id, sender=owner.id,
                                 recipients=to, mode=mode, thread_id=thread_id, group_id=group_id, task=task, payload=body)
        elif out == ShareOutcome.REDACT:
            body = decision.delivered_body or ""
            agent.remember(LearnedFact(item.item_id, item.title, body, item.sensitivity, True, owner.id))
            self.metrics.record_hop(context_id, owner.id)
            self._emit_context(EventType.CONTEXT_REDACTED, context_id, item, owner, agent, decision, summary=body)
            await self._send_say("reply_redact", {**names, "summary": body}, context_id=context_id, sender=owner.id,
                                 recipients=to, mode=mode, thread_id=thread_id, group_id=group_id, task=task, payload=body)
        else:  # DENY
            self._emit_context(EventType.CONTEXT_DENIED, context_id, item, owner, agent, decision)
            await self._send_say("reply_deny", names, context_id=context_id, sender=owner.id,
                                 recipients=to, mode=mode, thread_id=thread_id, group_id=group_id, task=task)

    async def _handle_hitl(
        self, decision, agent: OrgAgent, owner: OrgAgent, item: ContextItem, intent: Intent,
        context_id: str, task_id: str, *,
        mode: CoordinationMode = CoordinationMode.INDIVIDUAL,
        thread_id: str | None = None, group_id: str | None = None, recipients: list[str] | None = None,
    ) -> None:
        task = self.router.tasks[task_id]
        to = recipients or [agent.id]
        names = {"owner": owner.name, "requester": agent.name, "item": item.title}
        self.router.set_status(owner.id, AgentStatus.WAITING_HITL)
        await self._send_say("escalate", names, context_id=context_id, sender=owner.id,
                             recipients=to, mode=mode, thread_id=thread_id, group_id=group_id, task=task)
        req = HitlRequest(
            task_id=task_id, context_id=context_id, owner_agent_id=owner.id, requester_agent_id=agent.id,
            item_id=item.item_id, item_title=item.title, intent=intent, proposed_outcome=ShareOutcome.SHARE,
            sensitivity=item.sensitivity, reason=decision.reason,
        )
        self.hitl.create(req)
        self.router.set_task_state(
            task, TaskState.INPUT_REQUIRED,
            message=f"Awaiting operator approval to share '{item.title}' with {agent.name}.",
        )
        resolved = await self.hitl.wait(req.request_id, timeout=self.hitl_timeout)
        self.router.set_task_state(task, TaskState.WORKING)
        self.router.set_status(owner.id, AgentStatus.SPEAKING)
        await self._pause(0.4)

        if resolved.state == "approved" and resolved.decided_outcome == ShareOutcome.REDACT:
            body = item.redacted_summary or f"[redacted: {item.title}]"
            agent.remember(LearnedFact(item.item_id, item.title, body, item.sensitivity, True, owner.id))
            self.metrics.record_resolution(context_id, ShareOutcome.REDACT)
            self.metrics.record_hop(context_id, owner.id)
            self._emit_context(EventType.CONTEXT_REDACTED, context_id, item, owner, agent, decision, summary=body, rule="HITL-REDACT")
            await self._send_say("hitl_redact", {**names, "summary": body}, context_id=context_id, sender=owner.id,
                                 recipients=to, mode=mode, thread_id=thread_id, group_id=group_id, task=task, payload=body)
        elif resolved.state == "approved":
            agent.remember(LearnedFact(item.item_id, item.title, item.body, item.sensitivity, False, owner.id))
            self.metrics.record_resolution(context_id, ShareOutcome.SHARE)
            self.metrics.record_hop(context_id, owner.id)
            self._emit_context(EventType.CONTEXT_SHARED, context_id, item, owner, agent, decision, rule="HITL-APPROVE")
            await self._send_say("hitl_share", {**names, "body": item.body}, context_id=context_id, sender=owner.id,
                                 recipients=to, mode=mode, thread_id=thread_id, group_id=group_id, task=task, payload=item.body)
        else:
            self.metrics.record_resolution(context_id, ShareOutcome.DENY)
            self._emit_context(EventType.CONTEXT_DENIED, context_id, item, owner, agent, decision, rule="HITL-DENY")
            await self._send_say("hitl_deny", names, context_id=context_id, sender=owner.id,
                                 recipients=to, mode=mode, thread_id=thread_id, group_id=group_id, task=task)
        self.router.set_status(owner.id, AgentStatus.IDLE)

    async def _consult_manager(self, agent: OrgAgent, prompt: str, context_id: str, task_id: str) -> None:
        mgr_id = agent.profile.reports_to
        if not mgr_id or mgr_id not in self.registry.agents or not self._is_member(mgr_id):
            return
        task = self.router.tasks[task_id]
        mgr = self.registry.get(mgr_id)
        topic = self._topic(prompt)
        thread, created = self.threads.get_or_create(context_id, agent.id, mgr_id, topic=topic, task_id=task_id)
        if created:
            self.router.announce_thread(thread)
        self.router.set_status(mgr_id, AgentStatus.THINKING)
        await self._pause()
        await self._send_say(
            "manager_consult", {"requester": agent.name, "manager": mgr.name, "topic": topic},
            context_id=context_id, sender=agent.id, recipients=[mgr_id],
            intent=coordination_intent(topic), thread_id=thread.thread_id, task=task,
        )
        self.metrics.record_hop(context_id, mgr_id)
        self.router.set_status(mgr_id, AgentStatus.SPEAKING)
        await self._pause(0.5)
        await self._send_say(
            "manager_reply", {"manager": mgr.name, "requester": agent.name, "topic": topic},
            context_id=context_id, sender=mgr_id, recipients=[agent.id], thread_id=thread.thread_id, task=task,
        )
        self.router.set_status(mgr_id, AgentStatus.IDLE)

    # ── group coordination ──────────────────────────────────────────────────
    async def _run_group(
        self, agent: OrgAgent, prompt: str, context_id: str, task_id: str, *, member_ids: list[str] | None = None
    ) -> None:
        task = self.router.tasks[task_id]
        team_id = agent.profile.teams[0]
        if member_ids is None:  # no LLM selection → the whole team (deterministic fallback)
            member_ids = [m for m in self.snapshot.teams.get(team_id, []) if m != agent.id]
        members = [agent.id] + [m for m in member_ids if m != agent.id and self._is_member(m)]
        topic = self._topic(prompt)
        group = self.groups.create(context_id, team_id, topic, members, initiator=agent.id)
        self.router.announce_group(group)

        others = [m for m in members if m != agent.id]
        for m in others:
            self.router.set_status(m, AgentStatus.THINKING)
        opening = await self._send_say(
            "group_open", {"initiator": agent.name, "topic": topic},
            context_id=context_id, sender=agent.id, recipients=others,
            intent=coordination_intent(topic), mode=CoordinationMode.GROUP, group_id=group.group_id, task=task,
        )
        if opening:
            group.message_ids.append(opening.messageId)
        await self._pause()

        for m in sorted(others):
            mem = self.registry.get(m)
            self.router.set_status(m, AgentStatus.SPEAKING)
            await self._pause(0.35)
            reply = await self._send_say(
                "group_reply", {"member": mem.name, "topic": topic},
                context_id=context_id, sender=m, recipients=[x for x in members if x != m],
                mode=CoordinationMode.GROUP, group_id=group.group_id, task=task,
            )
            if reply:
                group.message_ids.append(reply.messageId)
            self.metrics.record_hop(context_id, m)
            self.router.set_status(m, AgentStatus.IDLE)

        # A group also exercises need-to-know: the initiator sources real context
        # from a member who owns something relevant (share / redact / escalate).
        await self._group_context_exchange(agent, members, group, prompt, context_id, task_id)
        group.active = False

    async def _group_context_exchange(
        self, initiator: OrgAgent, members: list[str], group, prompt: str, context_id: str, task_id: str
    ) -> None:
        q = set(tokenize(prompt)) | set(tokenize(group.topic))
        best: tuple[OrgAgent, ContextItem] | None = None
        best_rel = 0.0
        for mid in members:
            if mid == initiator.id:
                continue
            owner = self.registry.get(mid)
            for item in owner.owned_items.values():
                rel = 2.0 * len(q & set(item.topic_tags))
                if item.scope_ref and (item.scope_ref in initiator.profile.projects or item.scope_ref in initiator.profile.teams):
                    rel += 1.0
                if rel > best_rel:
                    best_rel, best = rel, (owner, item)
        if best is None or initiator.knows(best[1].item_id, raw_required=True):
            return
        owner, item = best
        intent = build_request_intent(initiator.profile, item, task_ref=task_id)
        self.router.set_status(owner.id, AgentStatus.THINKING)
        await self._pause(0.4)
        sent = await self._send_say(
            "request", {"requester": initiator.name, "owner": owner.name, "item": item.title, "motivation": intent.motivation},
            context_id=context_id, sender=initiator.id, recipients=[owner.id], intent=intent,
            mode=CoordinationMode.GROUP, group_id=group.group_id, task=self.router.tasks[task_id],
        )
        if sent:
            group.message_ids.append(sent.messageId)
        decision = await self._decide_share(initiator, owner, item, intent, context_id)
        self.metrics.record_decision(context_id, decision.outcome)
        group.shared_items.append(item.item_id)
        await self._apply_decision(
            decision, initiator, owner, item, intent, context_id, task_id,
            mode=CoordinationMode.GROUP, group_id=group.group_id,
            recipients=[x for x in members if x != owner.id],
        )
        self.router.set_status(owner.id, AgentStatus.IDLE)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _emit_context(self, event_type, context_id, item, owner, agent, decision, *, summary=None, rule=None) -> None:
        self.broker.emit(
            event_type,
            ContextSharePayload(
                context_id=context_id, item_id=item.item_id, title=item.title,
                sender=owner.id, recipient=agent.id, sensitivity=item.sensitivity.value,
                rule_id=rule or decision.rule_id, reason=decision.reason, summary=summary,
            ),
            context_id=context_id,
        )
        if self.dbwriter is not None:
            self.dbwriter.record("share_decision", {
                "context_id": context_id, "kind": getattr(event_type, "value", str(event_type)).split(".")[-1],
                "item_id": item.item_id, "title": item.title, "sender": owner.id, "recipient": agent.id,
                "sensitivity": item.sensitivity.value, "rule_id": rule or decision.rule_id,
                "reason": decision.reason, "summary": summary,
            })

    def _trace(self, agent_id: str, kind: str, summary: str, *, live: bool = False,
               context_id: Optional[str] = None, detail: Optional[str] = None) -> None:
        if self.trace is not None:
            self.trace.record(agent_id=agent_id, kind=kind, summary=summary, live=live,
                              context_id=context_id, detail=detail)

    async def _think(self, kind: str, ctx: dict) -> Optional[str]:
        """The agent reasons briefly before acting — real Mistral, or absent (no
        template fallback for reasoning, same as the message itself)."""
        if not self.llm.available:
            return None
        think = getattr(self.llm, "think", None)
        if think is None:
            return None
        try:
            return await think(kind, ctx)
        except Exception:
            return None

    async def _say(self, kind: str, ctx: dict) -> Optional[str]:
        """Real Mistral text for this message — or None if the LLM can't produce
        it. Templates were removed: every agent message is genuine Mistral, or it
        is omitted (never faked)."""
        if not self.llm.available:
            return None
        try:
            out = await self.llm.phrase(kind, ctx)
            return out or None
        except Exception:
            return None

    async def _send_say(
        self, kind: str, ctx: dict, *, context_id: str, sender: str, recipients: list[str], task,
        mode: CoordinationMode = CoordinationMode.INDIVIDUAL, intent: Optional[Intent] = None,
        thread_id: Optional[str] = None, group_id: Optional[str] = None, payload: Optional[str] = None,
        external_ids: Optional[set[str]] = None,
    ):
        """Think, then author the line with Mistral and send it. Returns the
        Message, or None when the LLM couldn't produce text (the message — and its
        thought — are dropped; never templated). A ``payload`` (secret body/summary)
        is appended verbatim so the exact value never depends on the model."""
        thought = await self._think(kind, ctx)  # think before responding
        text = await self._say(kind, ctx)
        if not text:
            self._trace(sender, "phrase", f"{kind}: no reply (LLM unavailable)", live=False, context_id=context_id)
            return None  # message omitted → thought dropped (no dangling reasoning)
        if thought:
            self._trace(sender, "think", thought, live=True, context_id=context_id)
        self._trace(sender, "phrase", text, live=True, context_id=context_id, detail=kind.replace("_", " "))
        if payload and payload not in text:
            text = f"{text} {payload}"
        return self.router.send_message(
            context_id=context_id, sender=sender, recipients=recipients, text=text,
            intent=intent, mode=mode, thread_id=thread_id, group_id=group_id, task=task, thinking=thought,
            external_ids=external_ids,
        )

    async def decide_cross_org_share(
        self, requester: OrgAgent, item: ContextItem, intent: Intent, context_id: str = "x-org",
    ) -> ShareDecision:
        """Decide a request that arrived from a DIFFERENT organisation (via the federation
        gateway). This org owns ``item`` and decides about its own data — the owner agent's
        judgement under this org's Policy Engine — but with the federation boundary in force:
        ``cross_org=True`` is set HERE and only here, so only PUBLIC information can cross
        (everything else is denied by the ``CROSS-ORG-RESTRICT`` rule). ``requester`` is the
        foreign agent's ``OrgAgent`` (read for its profile only; it is not a local member)."""
        owner = self.registry.get(item.owner_agent_id)
        return await self._decide_share(requester, owner, item, intent, context_id, cross_org=True)

    # ── auto-fallback: route across the federation when no LOCAL member fits ─────────
    def _peer_needs(self, peer_org, prompt: str) -> list[ContextItem]:
        """The peer org's items relevant to the prompt topic (any tier). The boundary then
        shares only the PUBLIC ones and denies the rest — visibly — so this deliberately does
        NOT pre-filter by sensitivity. Capped, like the local needs scan."""
        q = set(tokenize(prompt))
        scored: list[tuple[ContextItem, float]] = []
        for item in peer_org.snapshot.items.values():
            rel = 2.0 * len(q & set(item.topic_tags)) + (1.0 if q & set(tokenize(item.title)) else 0.0)
            if rel > 0:
                scored.append((item, rel))
        scored.sort(key=lambda x: (-x[1], x[0].item_id))
        return [it for it, _ in scored[:3]]

    def _emit_cross_org(self, context_id: str, requester: OrgAgent, owner: OrgAgent, peer_org,
                        item: ContextItem, decision: ShareDecision, *, crossed: bool) -> None:
        """The boundary-crossing record (names both orgs) — what the Federation tab shows. The
        ``outcome`` reflects the FINAL result (after the operator gate): shared if it crossed,
        withheld otherwise."""
        self.broker.emit(
            EventType.CROSS_ORG_EXCHANGE,
            CrossOrgExchangePayload(
                source_org_id=self.snapshot.org_id, source_org_name=self.snapshot.org_name,
                target_org_id=peer_org.org_id, target_org_name=peer_org.org_name,
                requester_id=requester.id, requester_name=requester.name,
                owner_id=owner.id, owner_name=owner.name,
                item_id=item.item_id, item_title=item.title, sensitivity=item.sensitivity.value,
                outcome=("share" if crossed else "deny"), rule_id=decision.rule_id or "",
                reason=decision.reason or "", crossed=crossed,
            ),
            context_id=context_id, org_id=peer_org.org_id,
        )

    async def run_cross_org_prompt(self, prompt: str, target_org_id: str, *, requester_id: Optional[str] = None) -> dict:
        """Operator-directed cross-org request through the FULL pipeline (the live counterpart of
        the `/exchange` policy probe): open a Task and run the cross-org scenario — threads,
        messages, History, and the operator-approval HITL gate. Returns the task to watch."""
        if self.federation is None or target_org_id == self.snapshot.org_id or target_org_id not in self.federation.org_ids:
            return {"rejected": True, "reason": "unknown or same-org federation target"}
        pool = self._pool_ids()
        if requester_id is None:
            if pool:
                best, _ = self.router.route_prompt(prompt, pool_ids=pool)
                requester_id = best or next(iter(pool))
            else:
                requester_id = self.snapshot.ceo_id  # no membership gating ⇒ the org's external face
        context_id = new_id("ctx-")
        task = self.router.new_task(context_id, message=prompt)
        self._spawn(self._run_cross_org_request(prompt, context_id, task, target_org_id, requester_id=requester_id),
                    task_id=task.id)
        rep = self.federation.org(target_org_id)
        return {"rejected": False, "task_id": task.id, "context_id": context_id, "cross_org": True,
                "routed_to_org": target_org_id, "routed_to_org_name": rep.org_name, "requester_id": requester_id}

    async def _run_cross_org_request(
        self, prompt: str, context_id: str, task: Task, target_org_id: str, *, requester_id: Optional[str] = None,
    ) -> None:
        """A request that crosses the federation boundary, run through the REAL pipeline: the local
        requester (a joined member) opens a thread to the peer owner; messages go through the Router
        (so they thread + persist to History); the PEER's machinery decides under the Policy Engine
        (cross_org=True); and every share that WOULD cross is gated by OPERATOR APPROVAL (HITL) before
        any information leaves. Only PUBLIC may cross — non-public is hard-denied by policy, no human."""
        peer_org = self.federation.org(target_org_id)
        requester = self.registry.get(requester_id or self.snapshot.ceo_id)
        try:
            self.broker.emit(
                EventType.PROMPT_ACCEPTED,
                PromptAcceptedPayload(
                    prompt=prompt, task_id=task.id, context_id=context_id,
                    routed_to=requester.id, routed_to_name=f"{requester.name} → {peer_org.org_name}",
                ),
                context_id=context_id, org_id=target_org_id,
            )
            if self.dbwriter is not None:
                self.dbwriter.record("conversation", {
                    "context_id": context_id, "prompt": prompt, "kind": "user",
                    "routed_to": requester.id, "routed_to_name": f"{requester.name} → {peer_org.org_name}",
                    "task_id": task.id})
            self.metrics.record_hop(context_id, requester.id)
            self.router.set_status(requester.id, AgentStatus.THINKING)
            self.router.set_task_state(task, TaskState.WORKING)
            self._trace(requester.id, "route",
                        f"no local owner — asking {peer_org.org_name} across the federation",
                        live=False, context_id=context_id, detail="only PUBLIC information may cross the boundary")
            for item in self._peer_needs(peer_org, prompt):
                await self._cross_org_source(requester, peer_org, item, context_id, task)
            await self._finalize(requester, prompt, context_id, task.id)
        except Exception as exc:  # pragma: no cover - safety net
            self.router.set_task_state(task, TaskState.FAILED, message=f"cross-org error: {exc}")
            import traceback

            traceback.print_exc()

    async def _cross_org_source(
        self, requester: OrgAgent, peer_org, item: ContextItem, context_id: str, task: Task,
    ) -> None:
        """Source ONE peer item across the boundary, through the REAL pipeline: open a thread, ask
        (Router transport — threads + History persistence), let the PEER decide (Policy Engine,
        cross_org=True). A policy DENY is withheld with no human; a would-cross share is gated by
        OPERATOR APPROVAL (HITL) before delivery — information only leaves the building on sign-off."""
        owner_id = item.owner_agent_id
        owner = peer_org.registry.get(owner_id)
        ext = {owner_id}  # the peer owner is exempt from THIS org's membership backstop (gateway-vouched)
        intent = build_request_intent(requester.profile, item)
        thread, created = self.threads.get_or_create(context_id, requester.id, owner_id, topic=item.title, task_id=task.id)
        if created:
            self.router.announce_thread(thread)
        self.router.set_status(requester.id, AgentStatus.SPEAKING)
        await self._pause()
        names = {"owner": f"{owner.name} · {peer_org.org_name}", "requester": requester.name, "item": item.title}
        await self._send_say(
            "request", {**names, "motivation": intent.motivation},
            context_id=context_id, sender=requester.id, recipients=[owner_id], intent=intent,
            thread_id=thread.thread_id, task=task, external_ids=ext)

        # the PEER org decides about its OWN data, under its Policy Engine (cross_org=True)
        decision = await self.federation.request_across(
            requester=requester, target_org_id=peer_org.org_id, item=item, intent=intent, context_id=context_id)

        if decision.outcome == ShareOutcome.DENY:  # hard DENY (non-public): withheld at the boundary, NO human
            self.metrics.record_decision(context_id, ShareOutcome.DENY)
            self._emit_context(EventType.CONTEXT_DENIED, context_id, item, owner, requester, decision)
            await self._send_say("reply_deny", names, context_id=context_id, sender=owner_id,
                                 recipients=[requester.id], thread_id=thread.thread_id, task=task, external_ids=ext)
            self._emit_cross_org(context_id, requester, owner, peer_org, item, decision, crossed=False)
            return

        # would cross (PUBLIC) → OPERATOR APPROVAL GATE before anything leaves the building (HITL)
        self.metrics.record_decision(context_id, ShareOutcome.ESCALATE)
        await self._send_say("escalate", names, context_id=context_id, sender=owner_id,
                             recipients=[requester.id], thread_id=thread.thread_id, task=task, external_ids=ext)
        req = HitlRequest(
            task_id=task.id, context_id=context_id, owner_agent_id=owner_id, requester_agent_id=requester.id,
            item_id=item.item_id, item_title=item.title, intent=intent, proposed_outcome=ShareOutcome.SHARE,
            sensitivity=item.sensitivity,
            reason=(f"Cross-org disclosure {peer_org.org_name} → {self.snapshot.org_name}: only PUBLIC "
                    f"information may leave, and the operator must approve. {decision.reason}"))
        self.hitl.create(req)
        self.router.set_task_state(
            task, TaskState.INPUT_REQUIRED,
            message=f"Operator approval needed to release '{item.title}' from {peer_org.org_name} to {self.snapshot.org_name}.")
        self.router.set_status(requester.id, AgentStatus.WAITING_HITL)
        resolved = await self.hitl.wait(req.request_id, timeout=self.hitl_timeout)
        self.router.set_task_state(task, TaskState.WORKING)
        self.router.set_status(requester.id, AgentStatus.SPEAKING)
        await self._pause(0.4)

        if resolved.state == "approved":
            redacted = resolved.decided_outcome == ShareOutcome.REDACT or decision.outcome == ShareOutcome.REDACT
            body = (item.redacted_summary or f"[redacted: {item.title}]") if redacted else (decision.delivered_body or item.body)
            requester.remember(LearnedFact(item.item_id, item.title, body, item.sensitivity, redacted, owner_id))
            self.metrics.record_hop(context_id, owner_id)
            self.metrics.record_resolution(context_id, ShareOutcome.REDACT if redacted else ShareOutcome.SHARE)
            self._emit_context(EventType.CONTEXT_REDACTED if redacted else EventType.CONTEXT_SHARED,
                               context_id, item, owner, requester, decision, summary=body if redacted else None,
                               rule="HITL-APPROVE")
            await self._send_say("hitl_share", {**names, "body": body}, context_id=context_id, sender=owner_id,
                                 recipients=[requester.id], thread_id=thread.thread_id, task=task, payload=body, external_ids=ext)
            self._emit_cross_org(context_id, requester, owner, peer_org, item, decision, crossed=True)
        else:
            self.metrics.record_resolution(context_id, ShareOutcome.DENY)
            self._emit_context(EventType.CONTEXT_DENIED, context_id, item, owner, requester, decision, rule="HITL-DENY")
            await self._send_say("hitl_deny", names, context_id=context_id, sender=owner_id,
                                 recipients=[requester.id], thread_id=thread.thread_id, task=task, external_ids=ext)
            self._emit_cross_org(context_id, requester, owner, peer_org, item, decision, crossed=False)
        self.router.set_status(requester.id, AgentStatus.IDLE)

    async def _decide_share(self, requester: OrgAgent, owner: OrgAgent, item: ContextItem,
                            intent: Intent, context_id: str, *, cross_org: bool = False) -> ShareDecision:
        """The OWNER agent (Mistral) decides share / redact / deny / escalate for its OWN
        data; the deterministic **Policy Engine** then reviews that decision against codified
        compliance rules and may tighten it (never loosen). If the LLM can't be reached the
        decision is NOT chosen by code — it ESCALATEs to the human operator (no engine review).

        **Policy pre-gate (cost/latency optimisation).** The engine's deterministic floor is
        computed first (against a maximally-permissive hypothetical owner). When that floor is
        already DENY or ESCALATE — every denial, and every secret (four-eyes) — the owner's LLM
        is **skipped**: the model cannot loosen a deny, and a secret always needs human approval
        regardless of what the owner would say, so asking it would only spend a call. The model
        is consulted only when the floor leaves room for its judgement (SHARE / REDACT)."""
        officer_id = self._policy_officer_id
        floor = self.policy.review(
            _build_llm_decision(item, ShareOutcome.SHARE, "policy pre-gate"),
            requester.profile, owner.profile, item, intent, officer_id=officer_id, cross_org=cross_org,
        )
        if floor.outcome in (ShareOutcome.DENY, ShareOutcome.ESCALATE):
            # The policy already determines the outcome — decide outright, no owner LLM call.
            self.metrics.record_policy_review(context_id)
            self.metrics.record_policy_pregate(context_id)  # decided outright, NOT an override
            self._trace(owner.id, "decide_share", f"SKIPPED (policy pre-gate) '{item.title}'",
                        live=False, context_id=context_id,
                        detail="owner LLM not called — the policy floor already determines the outcome")
            self._trace(officer_id or owner.id, "policy_review",
                        f"PRE-GATE {floor.outcome.value.upper()} '{item.title}'",
                        live=False, context_id=context_id, detail=f"{floor.rule_id} — {floor.reason}")
            return floor
        # The owner's judgement can still change the result → ask the model, then review.
        decide = getattr(self.llm, "decide_share", None)
        if self.llm.available and decide is not None:
            try:
                res = await decide(requester=requester.profile, owner=owner.profile, item=item, intent=intent)
            except Exception:
                res = None
            if res is not None:
                outcome, reason = res
                self._trace(owner.id, "decide_share", f"{outcome.value.upper()} '{item.title}'",
                            live=True, context_id=context_id, detail=reason)
                decision = _build_llm_decision(item, outcome, reason)
                # deterministic compliance review (the Policy Engine — replaces the LLM officer)
                return self._policy_review(requester, owner, item, intent, decision, context_id, cross_org=cross_org)
        # LLM unreachable → hand the call to the human operator (HITL); the engine does not
        # decide for an absent owner, so an undecided share is a person's call, not code's.
        reason = "Owner's LLM was unavailable — escalated to the operator to decide."
        self._trace(owner.id, "decide_share", f"ESCALATE '{item.title}' (LLM unavailable → operator)",
                    live=False, context_id=context_id, detail=reason)
        return ShareDecision(
            outcome=ShareOutcome.ESCALATE, reason=reason, item_id=item.item_id, rule_id="LLM-UNAVAILABLE",
            sensitivity=item.sensitivity, delivered_title=item.title, delivered_body=None,
        )

    def _policy_review(self, requester: OrgAgent, owner: OrgAgent, item: ContextItem,
                       intent: Intent, decision: ShareDecision, context_id: str, *, cross_org: bool = False) -> ShareDecision:
        """Deterministic compliance review (the **Policy Engine**) over the owner's LLM
        decision: codified need-to-know / least-privilege / SoD / regulatory rules, folded
        most-restrictive-wins (tighten-only). Replaces the former LLM Policy Officer. Recorded
        as a `policy_review` trace span (live=False — deterministic) attributed to the Security
        head (the compliance authority); a tighten re-stamps the decision `rule_id="POLICY/<rule>"`."""
        officer_id = self._policy_officer_id
        reviewed = self.policy.review(
            decision, requester.profile, owner.profile, item, intent, officer_id=officer_id, cross_org=cross_org
        )
        self.metrics.record_policy_review(context_id)
        attrib = officer_id or owner.id
        if reviewed.outcome != decision.outcome:
            self.metrics.record_policy_override(context_id)
            self._trace(attrib, "policy_review",
                        f"RESTRICT {decision.outcome.value.upper()}→{reviewed.outcome.value.upper()} '{item.title}'",
                        live=False, context_id=context_id, detail=f"{reviewed.rule_id} — {reviewed.reason}")
            return reviewed
        self._trace(attrib, "policy_review", f"CONCUR {decision.outcome.value.upper()} '{item.title}'",
                    live=False, context_id=context_id, detail=f"{reviewed.rule_id} — {reviewed.reason}")
        return decision

    def _blurb(self, aid: str) -> str:
        ag = self.registry.get(aid)
        skills = ", ".join(s.name for s in ag.card.skills[:3])
        return f"{ag.profile.role_title}, {ag.profile.department.value} — {skills}"

    def _dir_line(self, ag) -> str:
        p = ag.profile
        tags = ", ".join(sorted(ag.card.skill_tags)[:6])
        return f"{ag.id} | {ag.name} — {p.role_title}, {p.department.value}, L{int(p.level)} | skills: {tags}"

    def _agent_directory(self, pool=None) -> str:
        """One compact 'card' per routable agent — the company the LLM router chooses from.
        When the network is gated this is restricted to joined members; otherwise it is the
        whole company (cached, since the org is immutable for a given seed)."""
        if pool is not None:
            return "\n".join(self._dir_line(self.registry.get(i)) for i in pool)
        cached = getattr(self, "_directory_cache", None)
        if cached is None:
            cached = "\n".join(self._dir_line(ag) for ag in self.snapshot.agents.values())
            self._directory_cache = cached
        return cached

    def _topic(self, prompt: str) -> str:
        toks = tokenize(prompt)
        return " ".join(toks[:4]) if toks else "the task"

    async def _pause(self, factor: float = 1.0) -> None:
        if self.step_delay > 0:
            await asyncio.sleep(self.step_delay * factor)

    def _spawn(self, coro, *, task_id: Optional[str] = None) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        if task_id is not None:
            self._scenarios[task_id] = task
            task.add_done_callback(lambda _t, k=task_id: self._scenarios.pop(k, None))
        return task

    async def cancel_task(self, task_id: str) -> Optional[Task]:
        """A2A ``tasks/cancel`` — abort an in-flight task (user goal or cron goal),
        drive it to the terminal ``canceled`` state, stop its scenario coroutine,
        clear any pending HITL, and return the agents to idle. Idempotent: a task
        that's already finished is returned unchanged."""
        task = self.router.tasks.get(task_id)
        if task is None:
            return None
        if task.status.state in TERMINAL_STATES:
            return task  # already completed/failed/canceled — nothing to do
        # 1. Freeze the state first so the running scenario can't flip it to completed.
        self.router.set_task_state(task, TaskState.CANCELED, message="Canceled by the operator.")
        # 2. Stop the scenario coroutine (it may be mid-LLM-call or parked on HITL).
        scenario = self._scenarios.pop(task_id, None)
        if scenario is not None and not scenario.done():
            scenario.cancel()
        # 3. Clear any pending HITL for this context (drops it from the queue + UI).
        for req in self.hitl.list_pending():
            if req.context_id == task.contextId:
                self.hitl.resolve(req.request_id, approved=False, outcome=ShareOutcome.DENY, decided_by="canceled")
        # 4. Return every agent that took part back to idle.
        for aid in self.metrics.involved(task.contextId):
            self.router.set_status(aid, AgentStatus.IDLE)
        self.metrics.emit(task.contextId)
        return task
