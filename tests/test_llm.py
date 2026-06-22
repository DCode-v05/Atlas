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
def _provider(**kw) -> BedrockProvider:
    return BedrockProvider(
        region="us-east-1", reasoning_model="mistral.test", phrasing_model="mistral.test",
        access_key="AKIATEST", secret_key="secrettest", **kw,
    )


def test_bedrock_api_key_sets_bearer_env(monkeypatch):
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    BedrockProvider(region="us-east-1", reasoning_model="m", phrasing_model="m", api_key="bdrk-demo-key")
    assert os.environ.get("AWS_BEARER_TOKEN_BEDROCK") == "bdrk-demo-key"


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


async def test_token_bucket_acquire_waits_then_grants():
    import time as _t

    b = _TokenBucket(rpm=600, burst=1)  # ~10 tokens/sec → ~0.1s per token
    assert b.take() is True  # drain the burst token
    t0 = _t.monotonic()
    await b.acquire()  # pacing is now WAITING, not skipping
    assert _t.monotonic() - t0 >= 0.05  # it waited for a refill rather than skipping


async def test_bedrock_paces_by_waiting_then_makes_the_real_call():
    # Templates are removed: when the bucket is drained, _chat WAITS for a token
    # and still makes the real call — it never skips to a fallback.
    prov = _provider(rpm=600, burst=1)
    calls = {"n": 0}

    class _Client:
        @staticmethod
        def converse(**_):
            calls["n"] += 1
            return {"output": {"message": {"content": [{"text": "on it, will sync in-thread"}]}}}

    prov.client = _Client()
    prov._bucket("mistral.test").take()  # drain the single token
    out = await prov._chat("mistral.test", "s", "u", max_tokens=10, temperature=0.0)
    assert out == "on it, will sync in-thread"  # real call happened after the wait
    assert calls["n"] == 1
    assert prov.calls_ok == 1


def test_every_message_kind_has_a_prompt():
    # With no template fallback, a missing _phrase_prompt branch would silently
    # drop that message forever — so every kind the orchestrator emits must map
    # to a non-empty Mistral prompt.
    kinds = [
        "request", "reply_share", "reply_redact", "reply_deny", "escalate",
        "hitl_share", "hitl_redact", "hitl_deny", "group_open", "group_reply",
        "manager_consult", "manager_reply", "summary",
    ]
    ctx = {
        "requester": "A", "owner": "B", "item": "X", "motivation": "m", "body": "v",
        "summary": "s", "initiator": "I", "topic": "T", "member": "M", "manager": "Mg",
        "agent": "Ag", "prompt": "p", "shared": 1, "redacted": 0, "denied": 0, "hitl": 0,
    }
    for k in kinds:
        assert BedrockProvider._phrase_prompt(k, ctx), f"no Mistral prompt for message kind '{k}'"


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
