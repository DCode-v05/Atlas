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

    async def think(self, kind, ctx):
        return f"(reasoning) deciding how to handle {kind}"

    async def rerank(self, prompt, candidate_ids, blurbs):
        return None

    async def route(self, prompt, directory):
        return None  # undecided → orchestrator falls back to the deterministic scorer

    async def decide_share(self, *, requester, owner, item, intent):
        # stand-in for the owner agent's judgement: cautious by sensitivity.
        from atlas.org.ext_models import Sensitivity, ShareOutcome
        if item.sensitivity == Sensitivity.SECRET:
            return (ShareOutcome.ESCALATE, "secret — asking the operator to approve")
        if item.sensitivity in (Sensitivity.RESTRICTED, Sensitivity.CONFIDENTIAL):
            return (ShareOutcome.REDACT, "sensitive — sharing only a safe summary")
        return (ShareOutcome.SHARE, "in scope — shared")

    async def judge_scope(self, prompt, *, org_summary):
        return None

    async def judge_group(self, prompt, roster):
        return None  # undecided → orchestrator falls back to the keyword heuristic


@pytest.fixture
def offline_llm():
    return FakeLLM()
