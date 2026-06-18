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
