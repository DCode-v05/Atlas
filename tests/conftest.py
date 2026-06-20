"""Shared test fixtures.

Production runs real Mistral on Amazon Bedrock (no template fallback — agents
speak genuine Mistral or stay silent). Tests can't make real Bedrock calls, so
they inject this deterministic fake: it reports ``available=True`` and authors
short, varied text per (kind, ctx), so the message flow is exercised offline
exactly as it would be with a live model.
"""

from __future__ import annotations

import pytest


class FakeLLM:
    name = "fake"

    @property
    def available(self) -> bool:
        return True

    async def phrase(self, kind, ctx):
        # deterministic + varied; deliberately omits body/summary so the
        # verbatim-payload append in the orchestrator is genuinely exercised.
        bits = " ".join(str(v) for k, v in ctx.items() if k not in ("body", "summary") and v)
        return f"[{kind}] {bits}".strip()

    async def rerank(self, prompt, candidate_ids, blurbs):
        return None

    async def reason_share(self, **kwargs):
        return None

    async def judge_scope(self, prompt, *, org_summary):
        return None


@pytest.fixture
def offline_llm():
    return FakeLLM()
