"""Shared test fixtures.

Production requires a real ``GROQ_API_KEY`` (no simulated provider). Tests can't
make real Groq calls, so they inject this deterministic offline double — it
reports ``available=False`` so the orchestrator uses its template safety-net,
giving stable, offline test behavior.
"""

from __future__ import annotations

import pytest


class OfflineLLM:
    name = "offline"

    @property
    def available(self) -> bool:
        return False

    async def phrase(self, kind, ctx):
        return None

    async def rerank(self, prompt, candidate_ids, blurbs):
        return None

    async def reason_share(self, **kwargs):
        return None

    async def judge_scope(self, prompt, *, org_summary):
        return None


@pytest.fixture
def offline_llm():
    return OfflineLLM()
