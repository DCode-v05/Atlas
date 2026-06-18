"""LLM boundary tests — Bedrock (Mistral) provider, offline.

No network: the provider's Converse call / ``_chat`` is mocked, so we test
parsing, throttling, and the API-key (bearer-token) wiring without AWS.
"""

from __future__ import annotations

import os

import pytest

from atlas.config import Settings
from atlas.llm import get_provider
from atlas.llm.bedrock_provider import BedrockProvider, _TokenBucket
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
ITEM = ContextItem(item_id="i", owner_agent_id="O", title="Stripe key", body="redacted-demo",
                   sensitivity=Sensitivity.SECRET, scope=Scope.PROJECT, scope_ref="billing", min_clearance=1)
INTENT = Intent(motivation="wiring billing", purpose_tag=PurposeTag.TASK_CONTEXT,
                requested_topic="billing", declared_scope=Scope.PROJECT)


def _provider(**kw) -> BedrockProvider:
    return BedrockProvider(
        region="us-east-1", reasoning_model="mistral.test", phrasing_model="mistral.test",
        access_key="AKIATEST", secret_key="secrettest", **kw,
    )


def test_bedrock_api_key_sets_bearer_env(monkeypatch):
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    BedrockProvider(region="us-east-1", reasoning_model="m", phrasing_model="m", api_key="bdrk-demo-key")
    assert os.environ.get("AWS_BEARER_TOKEN_BEDROCK") == "bdrk-demo-key"


async def test_bedrock_reason_share_parses_outcome(monkeypatch):
    prov = _provider()

    async def fake_chat(model, system, user, *, max_tokens, temperature):
        return "OUTCOME: redact\nREASON: the declared scope is broader than the item"

    monkeypatch.setattr(prov, "_chat", fake_chat)
    res = await prov.reason_share(requester=R, owner=O, item=ITEM, intent=INTENT, base_outcome=ShareOutcome.SHARE)
    assert res is not None
    outcome, reason = res
    assert outcome == ShareOutcome.REDACT
    assert "scope" in reason.lower()


async def test_bedrock_phrase_humanizes_requests(monkeypatch):
    prov = _provider()

    async def fake_chat(*a, **k):
        return "Hey, could you send over the billing spec when you get a sec?"

    monkeypatch.setattr(prov, "_chat", fake_chat)
    assert await prov.phrase("not-a-kind", {}) is None
    out = await prov.phrase("request", {"requester": "A", "owner": "B", "item": "X", "motivation": "m"})
    assert out and "billing" in out


async def test_bedrock_throttles_on_throttling_exception():
    from atlas.events import EventBroker

    broker = EventBroker()
    prov = _provider(broker=broker, rpm=1000, cooldown=5)

    from botocore.exceptions import ClientError

    class _Client:
        @staticmethod
        def converse(**_):
            raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}}, "Converse")

    prov.client = _Client()
    out = await prov._chat("mistral.test", "s", "u", max_tokens=10, temperature=0.0)
    assert out is None
    assert prov.calls_429 == 1
    assert prov.available is False  # backed off into cooldown
    statuses = [e for e in broker.recent(50) if e.event == "llm.status"]
    assert statuses and statuses[-1].data["throttled"] is True


def test_token_bucket_caps_burst():
    b = _TokenBucket(rpm=10, burst=6)
    taken = sum(1 for _ in range(1000) if b.take())
    assert taken <= 8  # capped near the burst, not 1000


async def test_bedrock_proactive_throttle_skips_call_when_over_budget():
    prov = _provider(rpm=1, burst=1)
    called = {"n": 0}

    class _Client:
        @staticmethod
        def converse(**_):
            called["n"] += 1
            raise RuntimeError("API should not be called when throttled")

    prov.client = _Client()
    assert prov._bucket(prov.phrasing_model).take() is True  # drain the single token
    out = await prov.phrase("group_reply", {"member": "A", "topic": "x"})
    assert out is None
    assert prov.calls_throttled >= 1
    assert called["n"] == 0  # never hit the API


def test_get_provider_requires_credentials(monkeypatch):
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    import atlas.llm as llmmod

    class _NoCredsSession:
        def get_credentials(self):
            return None

    monkeypatch.setattr("boto3.Session", lambda *a, **k: _NoCredsSession())
    with pytest.raises(RuntimeError):
        get_provider(Settings(_env_file=None))


def test_get_provider_returns_bedrock_with_creds():
    p = get_provider(Settings(aws_access_key_id="AKIATEST", aws_secret_access_key="secret", _env_file=None))
    assert p.name == "bedrock"
