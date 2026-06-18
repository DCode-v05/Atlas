"""LLM boundary tests — offline simulated default + Groq parsing/tighten-only.

No network: the Groq provider's ``_chat`` is monkeypatched, so we test parsing
and behavior without an API key.
"""

from __future__ import annotations

import pytest

from atlas.config import Settings
from atlas.llm import get_provider
from atlas.llm.groq_provider import GroqProvider
from atlas.org.ext_models import (
    ContextItem,
    Department,
    Intent,
    Level,
    OrgProfile,
    PurposeTag,
    Scope,
    Sensitivity,
    ShareOutcome,
)

R = OrgProfile(agent_id="R", human_name="R", human_email="r@x", department=Department.ENGINEERING,
               role_title="engineer", level=Level.IC, clearance=1, teams=["t"], projects=["billing"])
O = OrgProfile(agent_id="O", human_name="O", human_email="o@x", department=Department.ENGINEERING,
               role_title="manager", level=Level.MANAGER, clearance=3)
ITEM = ContextItem(item_id="i", owner_agent_id="O", title="Stripe key", body="sk_live",
                   sensitivity=Sensitivity.SECRET, scope=Scope.PROJECT, scope_ref="billing", min_clearance=1)
INTENT = Intent(motivation="wiring billing", purpose_tag=PurposeTag.TASK_CONTEXT,
                requested_topic="billing", declared_scope=Scope.PROJECT)


def test_get_provider_requires_a_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ATLAS_GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_provider(Settings(_env_file=None))


def test_get_provider_returns_groq_when_key_present():
    p = get_provider(Settings(groq_api_key="gsk_test_key", _env_file=None))
    assert p.name == "groq"


def test_token_bucket_caps_burst():
    from atlas.llm.groq_provider import _TokenBucket

    b = _TokenBucket(rpm=10, burst=6)  # burst capacity 6
    taken = sum(1 for _ in range(1000) if b.take())
    assert taken <= 8  # capped near the burst, not 1000


async def test_groq_throttles_on_429_and_emits_status(monkeypatch):
    from atlas.events import EventBroker

    broker = EventBroker()
    prov = GroqProvider(api_key="x", reasoning_model="m", phrasing_model="f", broker=broker, rpm=1000, cooldown=5)

    class _RateLimited(Exception):
        status_code = 429

    class _Client:
        class chat:
            class completions:
                @staticmethod
                async def create(**_):
                    raise _RateLimited("429 Too Many Requests")

    prov.client = _Client()
    out = await prov._chat("m", "s", "u", max_tokens=10, temperature=0.0)
    assert out is None
    assert prov.calls_429 == 1
    assert prov.available is False  # backed off into cooldown
    statuses = [e for e in broker.recent(50) if e.event == "llm.status"]
    assert statuses and statuses[-1].data["throttled"] is True


async def test_groq_proactive_throttle_skips_call_when_over_budget():
    # When the per-model budget is exhausted, the call is skipped BEFORE the API.
    prov = GroqProvider(api_key="x", reasoning_model="m", phrasing_model="fast", rpm=1, burst=1)
    called = {"n": 0}

    class _Client:
        class chat:
            class completions:
                @staticmethod
                async def create(**_):
                    called["n"] += 1
                    raise RuntimeError("API should not be called when throttled")

    prov.client = _Client()
    assert prov._bucket("fast").take() is True  # drain the single token
    out = await prov.phrase("group_reply", {"member": "A", "topic": "x"})
    assert out is None
    assert prov.calls_throttled >= 1
    assert called["n"] == 0  # never hit the API


async def test_groq_reason_share_parses_outcome(monkeypatch):
    prov = GroqProvider(api_key="x", reasoning_model="m", phrasing_model="f")

    async def fake_chat(model, system, user, *, max_tokens, temperature):
        return "OUTCOME: redact\nREASON: the declared scope is broader than the item"

    monkeypatch.setattr(prov, "_chat", fake_chat)
    res = await prov.reason_share(requester=R, owner=O, item=ITEM, intent=INTENT, base_outcome=ShareOutcome.SHARE)
    assert res is not None
    outcome, reason = res
    assert outcome == ShareOutcome.REDACT
    assert "scope" in reason.lower()


async def test_groq_phrase_only_humanizes_requests(monkeypatch):
    prov = GroqProvider(api_key="x", reasoning_model="m", phrasing_model="f")

    async def fake_chat(*a, **k):
        return "Hey, could you send over the billing spec when you get a sec?"

    monkeypatch.setattr(prov, "_chat", fake_chat)
    assert await prov.phrase("share", {}) is None  # decision replies stay verbatim
    out = await prov.phrase("request", {"requester": "A", "owner": "B", "item": "X", "motivation": "m"})
    assert out and "billing" in out


async def test_groq_circuit_breaker_disables_after_failures():
    prov = GroqProvider(api_key="x", reasoning_model="m", phrasing_model="f", max_failures=2)

    class _Failing:  # a stub client whose create() always raises (no network)
        class chat:
            class completions:
                @staticmethod
                async def create(**_):
                    raise RuntimeError("boom")

    prov.client = _Failing()
    assert prov.available is True
    await prov._chat("m", "s", "u", max_tokens=10, temperature=0.0)
    await prov._chat("m", "s", "u", max_tokens=10, temperature=0.0)
    assert prov.available is False  # breaker tripped after 2 failures
