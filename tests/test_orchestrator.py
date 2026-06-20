"""End-to-end orchestrator tests against the real (offline) runtime.

Drives the full pipeline for a user prompt and for a SECRET request that must
escalate to HITL, asserting the emitted SSE event sequence and final metrics.
"""

from __future__ import annotations

import asyncio

import pytest

from atlas.a2a.models import TaskState
from atlas.config import get_settings
from atlas.org.ext_models import Level, ShareOutcome
from atlas.runtime import build_runtime


def _events(broker, types=None):
    out = [e for e in broker.recent(10_000)]
    if types:
        out = [e for e in out if e.event in types]
    return out


async def _drain_until_completed(rt, context_id, *, resolve_hitl=None, timeout=5.0):
    """Spin the loop until the context's task completes, optionally resolving HITL."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.02)
        if resolve_hitl is not None:
            for req in rt.hitl.list_pending():
                rt.hitl.resolve(req.request_id, approved=resolve_hitl[0], outcome=resolve_hitl[1])
        done = [
            t for t in rt.tasks.values()
            if t.contextId == context_id and t.status.state in (TaskState.COMPLETED, TaskState.FAILED)
        ]
        if done:
            return done[0]
    raise AssertionError("task did not complete in time")


def _billing_engineer(rt) -> str:
    for ag in rt.snapshot.agents.values():
        p = ag.profile
        if p.department.value == "engineering" and p.level == Level.IC and "billing" in p.projects:
            return ag.id
    raise AssertionError("no billing engineer found")


@pytest.fixture
def rt(offline_llm):
    return build_runtime(get_settings(), step_delay=0.0, llm=offline_llm)


async def test_out_of_scope_prompt_is_gated(rt):
    res = await rt.orchestrator.run_user_prompt("what's the weather in Paris and a good pasta recipe?")
    assert res["rejected"] is True
    assert any(e.event == "gate.rejected" for e in rt.broker.recent(100))


class _ScopeLLM:
    """An available LLM double whose semantic scope verdict is fixed."""
    name = "scope-fake"

    def __init__(self, verdict):
        self._verdict = verdict

    @property
    def available(self):
        return True

    async def phrase(self, kind, ctx):
        return None

    async def rerank(self, prompt, candidate_ids, blurbs):
        return None

    async def reason_share(self, **kwargs):
        return None

    async def judge_scope(self, prompt, *, org_summary):
        return self._verdict


async def test_llm_gate_rejects_in_lexicon_but_out_of_scope():
    rt = build_runtime(get_settings(), step_delay=0.0, llm=_ScopeLLM(False))
    prompt = "give me the python script for generating wifi"
    # 'python' is an engineering skill tag, so the cheap lexical gate admits it…
    assert rt.router.org_scope_gate(prompt)[0] is True
    # …but the authoritative LLM semantic gate judges it OUT → rejected.
    res = await rt.orchestrator.run_user_prompt(prompt)
    assert res["rejected"] is True
    assert any(e.event == "gate.rejected" for e in rt.broker.recent(100))


async def test_llm_gate_admits_when_in_scope():
    rt = build_runtime(get_settings(), step_delay=0.0, llm=_ScopeLLM(True))
    res = await rt.orchestrator.run_user_prompt("give me the python script for generating wifi")
    assert res["rejected"] is False


class _GateLLM:
    """Available LLM that admits via judge_scope and authors text — for the gate
    (greeting) and group-decision paths."""
    name = "gate-fake"

    @property
    def available(self):
        return True

    async def phrase(self, kind, ctx):
        return f"[{kind}] hello there"

    async def rerank(self, prompt, ids, blurbs):
        return None

    async def reason_share(self, **kw):
        return None

    async def judge_scope(self, prompt, *, org_summary):
        return True

    async def judge_group(self, prompt, roster):
        return None

    async def route(self, prompt, directory):
        return None  # fall back to the deterministic scorer unless a test overrides


async def test_greeting_is_admitted_and_answered():
    rt = build_runtime(get_settings(), step_delay=0.0, llm=_GateLLM())
    res = await rt.orchestrator.run_user_prompt("Hi")
    assert res["rejected"] is False  # greeting admitted by the LLM gate, not blocked
    assert res["routed_to"] == rt.snapshot.ceo_id  # no skill match → CEO answers
    task = await _drain_until_completed(rt, res["context_id"], timeout=3.0)
    assert task.status.state == TaskState.COMPLETED
    msgs = [e for e in rt.broker.recent(10_000)
            if e.event == "message.sent" and e.context_id == res["context_id"]]
    assert msgs  # the agent actually replied to the greeting


async def test_llm_selects_group_members():
    # The prompt has NO group keyword, so the deterministic heuristic would NOT
    # group it — but the LLM decides to coordinate a subset of the team.
    class _GroupLLM(_GateLLM):
        async def judge_group(self, prompt, roster):
            return [r[0] for r in roster[:2]]  # pick up to 2 real teammates

    rt = build_runtime(get_settings(), step_delay=0.0, llm=_GroupLLM())
    res = await rt.orchestrator.run_user_prompt("review the billing module pull request")
    await _drain_until_completed(rt, res["context_id"], resolve_hitl=(True, ShareOutcome.SHARE), timeout=5.0)
    groups = [e for e in rt.broker.recent(10_000)
              if e.event == "group.formed" and e.context_id == res["context_id"]]
    assert groups, "the LLM's group decision should have formed a group"
    assert len(groups[0].data["members"]) >= 2  # initiator + selected teammate(s)


async def test_trace_spans_and_learned_facts_are_exposed(rt):
    from atlas.api.viewmodels import agent_card_view

    res = await rt.orchestrator.run_user_prompt(
        "review the billing module pull request and share the engineering API style guide"
    )
    await _drain_until_completed(rt, res["context_id"], resolve_hitl=(True, ShareOutcome.SHARE), timeout=6.0)

    spans = [e for e in rt.broker.recent(20_000) if e.event == "trace.span"]
    assert spans, "operations should emit trace spans"
    kinds = {e.data["kind"] for e in spans}
    assert {"route", "think", "phrase", "decide_share"} & kinds  # core operations traced
    # messages carry the agent's reasoning (thinking layer)
    msgs = [e for e in rt.broker.recent(20_000) if e.event == "message.sent" and e.data.get("thinking")]
    assert msgs, "agent messages should carry a 'thinking' field"
    # the agent card exposes its trace + learned facts (with fidelity)
    card = agent_card_view(rt, res["routed_to"])
    assert isinstance(card["trace"], list) and card["trace"]
    assert isinstance(card["learned"], list)


async def test_owner_agent_llm_decides_the_share():
    # The owner agent (Mistral) makes the share decision — no deterministic matrix.
    # Here it chooses DENY for a confidential item the matrix might have redacted.
    from atlas.org.ext_models import ShareOutcome as SO

    class _OwnerLLM(_GateLLM):
        async def decide_share(self, *, requester, owner, item, intent):
            return (SO.DENY, "owner judged this is outside the requester's need-to-know")

    rt = build_runtime(get_settings(), step_delay=0.0, llm=_OwnerLLM())
    res = await rt.orchestrator.run_user_prompt(
        "I'm refactoring the event pipeline; what's the Atlas Core architecture decision record?"
    )
    await _drain_until_completed(rt, res["context_id"], timeout=5.0)
    denied = [e for e in rt.broker.recent(20_000) if e.event == "context.denied" and e.context_id == res["context_id"]]
    shared = [e for e in rt.broker.recent(20_000) if e.event == "context.shared" and e.context_id == res["context_id"]]
    assert denied and not shared, "the owner LLM's DENY decision should be honoured (no matrix override)"
    # the decision is traced as a live Mistral call, not deterministic policy
    spans = [e.data for e in rt.broker.recent(20_000) if e.event == "trace.span" and e.data["kind"] == "decide_share"]
    assert spans and all(s["live"] for s in spans)


async def test_routing_follows_llm_choice_over_full_directory():
    # The LLM router picks an agent the skill-scorer never would (a People/HR person
    # for a billing-engineering task) — proving routing follows the LLM's choice,
    # made over the WHOLE directory, not the deterministic scorer.
    pick = {"id": None}

    class _RouteLLM(_GateLLM):
        async def route(self, prompt, directory):
            return pick["id"]

    rt = build_runtime(get_settings(), step_delay=0.0, llm=_RouteLLM())
    pick["id"] = next(a.id for a in rt.snapshot.agents.values() if a.profile.department.value == "hr")
    # the directory the LLM chooses from is the full 100-agent company
    assert len(rt.orchestrator._agent_directory().splitlines()) == 100
    res = await rt.orchestrator.run_user_prompt("fix the billing payment integration bug")
    assert res["routed_to"] == pick["id"]  # routed to the LLM's pick, not the scorer's


async def test_user_prompt_routes_and_completes(rt):
    res = await rt.orchestrator.run_user_prompt("help me fix the deployment pipeline incident on prod")
    assert res["rejected"] is False
    task = await _drain_until_completed(rt, res["context_id"], resolve_hitl=(True, ShareOutcome.SHARE))
    assert task.status.state == TaskState.COMPLETED
    types = {e.event for e in rt.broker.recent(10_000)}
    assert "prompt.accepted" in types
    assert "discovery.matched" in types
    assert "message.sent" in types
    assert "metrics.updated" in types


async def test_secret_request_escalates_and_resumes_on_approval(rt):
    eng = _billing_engineer(rt)
    cid = rt.orchestrator.run_cron_task(eng, "I need the billing stripe payment credentials to wire the integration")
    task = await _drain_until_completed(rt, cid, resolve_hitl=(True, ShareOutcome.SHARE))
    assert task.status.state == TaskState.COMPLETED

    evs = [e.event for e in rt.broker.recent(10_000) if e.context_id == cid]
    assert "hitl.requested" in evs, evs
    assert "hitl.resolved" in evs
    assert "context.shared" in evs  # approved → shared
    # the task passed through input-required and back to working→completed
    states = [e.data["state"] for e in rt.broker.recent(10_000) if e.event == "task.state" and e.context_id == cid]
    assert "input-required" in states
    assert "completed" in states
    # a SECRET escalation was metered
    m = rt.metrics.per_context[cid]
    assert m.hitl_escalations >= 1
    assert m.items_shared >= 1


def _devops_engineer(rt) -> str:
    for ag in rt.snapshot.agents.values():
        p = ag.profile
        if p.department.value == "devops" and p.level == Level.IC:
            return ag.id
    raise AssertionError("no devops engineer found")


async def test_group_conversation_exercises_need_to_know(rt):
    """A team group chat must also run the policy engine — not just coordinate."""
    dev = _devops_engineer(rt)
    cid = rt.orchestrator.run_cron_task(dev, "production incident — coordinate the on-call response with the team")
    await _drain_until_completed(rt, cid, resolve_hitl=(True, ShareOutcome.SHARE))
    evs = [e.event for e in rt.broker.recent(10_000) if e.context_id == cid]
    assert "group.formed" in evs, evs
    # a real share/redact/deny decision happened inside the group
    assert any(e in evs for e in ("context.shared", "context.redacted", "context.denied")), evs
    # and at least one message was sent in group mode
    group_msgs = [
        e for e in rt.broker.recent(10_000)
        if e.event == "message.sent" and e.context_id == cid and e.data.get("mode") == "group"
    ]
    assert group_msgs


class _FakeLLM:
    """An available provider that authors prose but OMITS the payload."""
    name = "fake"

    @property
    def available(self):
        return True

    async def phrase(self, kind, ctx):
        return f"[LLM:{kind}] understood, here you go"

    async def rerank(self, prompt, ids, blurbs):
        return None

    async def reason_share(self, **kw):
        return None


async def test_llm_authors_messages_and_payload_is_preserved(rt):
    """With an LLM available, agent messages are LLM-authored on the cron path —
    and the exact shared content survives even if the model omits it."""
    rt.orchestrator.llm = _FakeLLM()
    eng = _billing_engineer(rt)  # any engineering IC
    cid = rt.orchestrator.run_cron_task(
        eng, "code review handoff — I need the engineering api style guide and backend context"
    )
    await _drain_until_completed(rt, cid, resolve_hitl=(True, ShareOutcome.SHARE))
    texts = [e.data["text"] for e in rt.broker.recent(10_000) if e.event == "message.sent" and e.context_id == cid]
    blob = " ".join(texts)
    assert "[LLM:" in blob, "messages should be LLM-authored"
    assert "snake_case" in blob, "the exact shared payload must survive the LLM rephrase"


async def test_secret_request_denied_by_operator(rt):
    eng = _billing_engineer(rt)
    cid = rt.orchestrator.run_cron_task(eng, "share the billing stripe payment secret key please")
    task = await _drain_until_completed(rt, cid, resolve_hitl=(False, ShareOutcome.DENY))
    assert task.status.state == TaskState.COMPLETED
    evs = [e.event for e in rt.broker.recent(10_000) if e.context_id == cid]
    assert "hitl.resolved" in evs
    assert "context.denied" in evs
