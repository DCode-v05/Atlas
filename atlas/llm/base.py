"""The LLM boundary.

A clean seam so the orchestrator never depends on a vendor directly. The only
provider is :class:`~atlas.llm.groq_provider.GroqProvider` — there is no
simulated provider. A ``GROQ_API_KEY`` is required (enforced in
``atlas/llm/__init__.py``); without one the app raises at startup.
"""

from __future__ import annotations

from typing import Optional

from atlas.org.ext_models import ContextItem, Intent, OrgProfile, ShareOutcome


class LLMProvider:
    """Interface implemented by the real Groq provider (for typing)."""

    name: str = "llm"

    @property
    def available(self) -> bool:  # pragma: no cover - overridden
        return False

    async def phrase(self, kind: str, ctx: dict) -> Optional[str]:  # pragma: no cover
        ...

    async def rerank(self, prompt: str, candidate_ids: list[str], blurbs: dict[str, str]) -> Optional[str]:  # pragma: no cover
        ...

    async def reason_share(
        self,
        *,
        requester: OrgProfile,
        owner: OrgProfile,
        item: ContextItem,
        intent: Intent,
        base_outcome: ShareOutcome,
    ) -> Optional[tuple[ShareOutcome, str]]:  # pragma: no cover
        ...
