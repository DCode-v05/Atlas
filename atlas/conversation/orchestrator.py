"""The orchestrator — the scenario engine that drives every conversation.

It runs the SAME pipeline for a user prompt and for a cron-simulated task:

    route → identify context needs → discover sources (level 2) →
    for each source: ask (with intent) → policy decides → share / redact /
    deny / escalate-to-HITL → remember → finalize the task.

When a Groq key is configured, the LLM is the real engine on BOTH paths: it
generates every agent message, re-ranks routing, and gives the tighten-only
share judgement. The deterministic templates remain only as an automatic
fallback when no key is set (so the app still boots offline). Secret payloads
are always delivered verbatim — the LLM authors the prose, code guarantees the
exact value is present.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from atlas.a2a.ids import new_id
from atlas.a2a.models import Artifact, TaskState, TextPart
from atlas.bus.discovery import tokenize
from atlas.bus.registry import AgentRegistry
from atlas.bus.router import GATE_REASON, Router
from atlas.conversation import phrasing
from atlas.conversation.intent import build_request_intent, coordination_intent
from atlas.conversation.stores import GroupStore, ThreadStore
from atlas.events import (
    ContextSharePayload,
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
    HitlRequest,
    Intent,
    ShareOutcome,
)
from atlas.org.generator import OrgSnapshot
from atlas.policy import evaluate_share, tighten_only

USER_NODE = "operator"

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
        hitl_timeout: float = 0.0,
        step_delay: float = 0.45,
        cron_max_inflight: int = 3,
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
        self.hitl_timeout = hitl_timeout
        self.step_delay = step_delay
        self.cron_max_inflight = cron_max_inflight
        self._cron_active = 0
        self._bg: set[asyncio.Task] = set()

    # ── public entry points ────────────────────────────────────────────────
    async def run_user_prompt(self, prompt: str, human_name: str = "Operator") -> dict:
        """Gate + route (LLM re-rank when available), then run the scenario async."""
        ok, reason = self.router.org_scope_gate(prompt)
        if not ok:
            self.router.reject(prompt, reason)
            return {"rejected": True, "reason": reason}
        chosen, scored = self.router.route_prompt(prompt)
        if not chosen:
            self.router.reject(prompt, GATE_REASON)
            return {"rejected": True, "reason": GATE_REASON}

        if self.llm.available and len(scored) > 1:
            try:
                best = await self.llm.rerank(
                    prompt, [a for a, _ in scored], {a: self._blurb(a) for a, _ in scored}
                )
                if best:
                    chosen = best
            except Exception:
                pass

        context_id = new_id("ctx-")
        task = self.router.new_task(context_id, message=prompt)
        agent = self.registry.get(chosen)
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
        self._spawn(self._run_scenario(prompt, chosen, context_id, task.id))
        return {
            "rejected": False, "task_id": task.id, "context_id": context_id,
            "routed_to": chosen, "routed_to_name": agent.name,
            "routed_to_role": agent.profile.role_title,
        }

    def run_cron_task(self, initiator_id: str, prompt: str) -> Optional[str]:
        """Autonomous task initiated by an agent (cron simulation). Load-sheds when
        too many scenarios are already in flight — this is what keeps the LLM call
        volume (and rate-limit pressure) bounded during a burst."""
        if self._cron_active >= self.cron_max_inflight:
            return None
        self._cron_active += 1
        context_id = new_id("cron-")
        task = self.router.new_task(context_id, message=prompt, role="agent")
        self._spawn(self._run_scenario(prompt, initiator_id, context_id, task.id, cron=True))
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
            grouped = self._should_group(agent, prompt)

            if grouped:
                await self._run_group(agent, prompt, context_id, task_id)

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
            phrasing.final_summary(agent.name, prompt, m.items_shared, m.items_redacted, m.items_denied, m.hitl_escalations),
            {"agent": agent.name, "prompt": prompt, "shared": m.items_shared, "redacted": m.items_redacted,
             "denied": m.items_denied, "hitl": m.hitl_escalations},
        )
        self.broker.emit(
            EventType.MESSAGE_SENT,
            MessageSentPayload(
                message_id=new_id("msg-"), context_id=context_id, sender=agent.id,
                recipients=[USER_NODE], mode=CoordinationMode.INDIVIDUAL.value, role="agent", text=summary,
            ),
            context_id=context_id,
        )
        task.artifacts.append(Artifact(name="summary", parts=[TextPart(text=summary)]))
        self.router.set_task_state(task, TaskState.COMPLETED, message=summary)
        self.router.set_status(agent.id, AgentStatus.IDLE)
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
            ask = await self._say(
                "request",
                phrasing.request_text(agent.name, owner.name, item.title, intent.motivation),
                {"requester": agent.name, "owner": owner.name, "item": item.title, "motivation": intent.motivation},
            )
            msg = self.router.send_message(
                context_id=context_id, sender=agent.id, recipients=[owner.id], text=ask,
                intent=intent, mode=CoordinationMode.INDIVIDUAL, thread_id=thread.thread_id, task=task,
            )
            thread.message_ids.append(msg.messageId)

            manages = self.snapshot.manages_transitively(agent.id, owner.id)
            decision = evaluate_share(agent.profile, owner.profile, item, intent, requester_manages_owner=manages)
            decision = await self._maybe_llm_tighten(decision, agent, owner, item, intent)
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
        if out == ShareOutcome.SHARE:
            body = decision.delivered_body or ""
            reply = await self._say_payload("reply_share", phrasing.share_reply(item.title, body), {**names, "body": body}, body)
            agent.remember(LearnedFact(item.item_id, item.title, body, item.sensitivity, False, owner.id))
            self.metrics.record_hop(context_id, owner.id)
            self._emit_context(EventType.CONTEXT_SHARED, context_id, item, owner, agent, decision)
        elif out == ShareOutcome.REDACT:
            body = decision.delivered_body or ""
            reply = await self._say_payload("reply_redact", phrasing.redact_reply(item.title, body), {**names, "summary": body}, body)
            agent.remember(LearnedFact(item.item_id, item.title, body, item.sensitivity, True, owner.id))
            self.metrics.record_hop(context_id, owner.id)
            self._emit_context(EventType.CONTEXT_REDACTED, context_id, item, owner, agent, decision, summary=body)
        else:  # DENY
            reply = await self._say("reply_deny", phrasing.deny_reply(item.title), names)
            self._emit_context(EventType.CONTEXT_DENIED, context_id, item, owner, agent, decision)

        self.router.send_message(
            context_id=context_id, sender=owner.id, recipients=to, text=reply,
            mode=mode, thread_id=thread_id, group_id=group_id, task=task,
        )

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
        notice = await self._say("escalate", phrasing.escalate_notice(item.title), names)
        self.router.send_message(
            context_id=context_id, sender=owner.id, recipients=to, text=notice,
            mode=mode, thread_id=thread_id, group_id=group_id, task=task,
        )
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
            reply = await self._say_payload("hitl_redact", phrasing.hitl_approved_redact_reply(item.title, body), {**names, "summary": body}, body)
        elif resolved.state == "approved":
            agent.remember(LearnedFact(item.item_id, item.title, item.body, item.sensitivity, False, owner.id))
            self.metrics.record_resolution(context_id, ShareOutcome.SHARE)
            self.metrics.record_hop(context_id, owner.id)
            self._emit_context(EventType.CONTEXT_SHARED, context_id, item, owner, agent, decision, rule="HITL-APPROVE")
            reply = await self._say_payload("hitl_share", phrasing.hitl_approved_reply(item.title, item.body), {**names, "body": item.body}, item.body)
        else:
            self.metrics.record_resolution(context_id, ShareOutcome.DENY)
            self._emit_context(EventType.CONTEXT_DENIED, context_id, item, owner, agent, decision, rule="HITL-DENY")
            reply = await self._say("hitl_deny", phrasing.hitl_denied_reply(item.title), names)

        self.router.send_message(
            context_id=context_id, sender=owner.id, recipients=to, text=reply,
            mode=mode, thread_id=thread_id, group_id=group_id, task=task,
        )
        self.router.set_status(owner.id, AgentStatus.IDLE)

    async def _consult_manager(self, agent: OrgAgent, prompt: str, context_id: str, task_id: str) -> None:
        mgr_id = agent.profile.reports_to
        if not mgr_id or mgr_id not in self.registry.agents:
            return
        task = self.router.tasks[task_id]
        mgr = self.registry.get(mgr_id)
        topic = self._topic(prompt)
        thread, created = self.threads.get_or_create(context_id, agent.id, mgr_id, topic=topic, task_id=task_id)
        if created:
            self.router.announce_thread(thread)
        self.router.set_status(mgr_id, AgentStatus.THINKING)
        await self._pause()
        consult = await self._say(
            "manager_consult", phrasing.manager_consult(agent.name, mgr.name, topic),
            {"requester": agent.name, "manager": mgr.name, "topic": topic},
        )
        self.router.send_message(
            context_id=context_id, sender=agent.id, recipients=[mgr_id], text=consult,
            intent=coordination_intent(topic), mode=CoordinationMode.INDIVIDUAL, thread_id=thread.thread_id, task=task,
        )
        self.metrics.record_hop(context_id, mgr_id)
        self.router.set_status(mgr_id, AgentStatus.SPEAKING)
        await self._pause(0.5)
        guidance = await self._say(
            "manager_reply", f"{mgr.name}: sure — here's some guidance on {topic}. Keep specifics within the team.",
            {"manager": mgr.name, "requester": agent.name, "topic": topic},
        )
        self.router.send_message(
            context_id=context_id, sender=mgr_id, recipients=[agent.id], text=guidance,
            mode=CoordinationMode.INDIVIDUAL, thread_id=thread.thread_id, task=task,
        )
        self.router.set_status(mgr_id, AgentStatus.IDLE)

    # ── group coordination ──────────────────────────────────────────────────
    async def _run_group(self, agent: OrgAgent, prompt: str, context_id: str, task_id: str) -> None:
        task = self.router.tasks[task_id]
        team_id = agent.profile.teams[0]
        members = list(self.snapshot.teams.get(team_id, []))
        if agent.id not in members:
            members.append(agent.id)
        topic = self._topic(prompt)
        group = self.groups.create(context_id, team_id, topic, members, initiator=agent.id)
        self.router.announce_group(group)

        others = [m for m in members if m != agent.id]
        for m in others:
            self.router.set_status(m, AgentStatus.THINKING)
        opening_text = await self._say(
            "group_open", phrasing.group_opening(agent.name, topic), {"initiator": agent.name, "topic": topic}
        )
        opening = self.router.send_message(
            context_id=context_id, sender=agent.id, recipients=others, text=opening_text,
            intent=coordination_intent(topic), mode=CoordinationMode.GROUP, group_id=group.group_id, task=task,
        )
        group.message_ids.append(opening.messageId)
        await self._pause()

        for m in sorted(others):
            mem = self.registry.get(m)
            self.router.set_status(m, AgentStatus.SPEAKING)
            await self._pause(0.35)
            reply_text = await self._say(
                "group_reply", phrasing.group_reply(mem.name, topic), {"member": mem.name, "topic": topic}
            )
            reply = self.router.send_message(
                context_id=context_id, sender=m, recipients=[x for x in members if x != m],
                text=reply_text, mode=CoordinationMode.GROUP, group_id=group.group_id, task=task,
            )
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
        ask = await self._say(
            "request", phrasing.request_text(initiator.name, owner.name, item.title, intent.motivation),
            {"requester": initiator.name, "owner": owner.name, "item": item.title, "motivation": intent.motivation},
        )
        sent = self.router.send_message(
            context_id=context_id, sender=initiator.id, recipients=[owner.id], text=ask,
            intent=intent, mode=CoordinationMode.GROUP, group_id=group.group_id, task=self.router.tasks[task_id],
        )
        group.message_ids.append(sent.messageId)
        manages = self.snapshot.manages_transitively(initiator.id, owner.id)
        decision = evaluate_share(initiator.profile, owner.profile, item, intent, requester_manages_owner=manages)
        decision = await self._maybe_llm_tighten(decision, initiator, owner, item, intent)
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

    async def _say(self, kind: str, template: str, ctx: dict) -> str:
        """LLM-author the message when Groq is available; else the template."""
        if self.llm.available:
            try:
                out = await self.llm.phrase(kind, ctx)
                if out:
                    return out
            except Exception:
                pass
        return template

    async def _say_payload(self, kind: str, template: str, ctx: dict, payload: str) -> str:
        """Like _say, but guarantee the exact payload (secret body / summary) is
        present — the LLM authors the prose, code ensures the value isn't lost."""
        text = await self._say(kind, template, ctx)
        if payload and payload not in text:
            text = f"{text} {payload}"
        return text

    async def _maybe_llm_tighten(self, decision, agent, owner, item, intent):
        if not self.llm.available:
            return decision
        try:
            res = await self.llm.reason_share(
                requester=agent.profile, owner=owner.profile, item=item, intent=intent, base_outcome=decision.outcome
            )
            if res:
                outcome, reason = res
                return tighten_only(decision, outcome, reason, item)
        except Exception:
            pass
        return decision

    def _blurb(self, aid: str) -> str:
        ag = self.registry.get(aid)
        skills = ", ".join(s.name for s in ag.card.skills[:3])
        return f"{ag.profile.role_title}, {ag.profile.department.value} — {skills}"

    def _topic(self, prompt: str) -> str:
        toks = tokenize(prompt)
        return " ".join(toks[:4]) if toks else "the task"

    async def _pause(self, factor: float = 1.0) -> None:
        if self.step_delay > 0:
            await asyncio.sleep(self.step_delay * factor)

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
