"""The LLM boundary.

A clean seam so the orchestrator never depends on a vendor directly. The only
provider is :class:`~atlas.llm.bedrock_provider.BedrockProvider` (Mistral on
Amazon Bedrock) — there is no simulated provider. AWS credentials are required
(enforced in ``atlas/llm/__init__.py``); without them the app raises at startup.
"""

from __future__ import annotations

from typing import Optional

from atlas.org.ext_models import ContextItem, Intent, OrgProfile, ShareOutcome


class LLMProvider:
    """Interface implemented by the real Bedrock provider (for typing)."""

    name: str = "llm"

    @property
    def available(self) -> bool:  # pragma: no cover - overridden
        return False

    async def phrase(self, kind: str, ctx: dict) -> Optional[str]:  # pragma: no cover
        ...

    async def think(self, kind: str, ctx: dict) -> Optional[str]:  # pragma: no cover
        """The agent's brief reasoning before it speaks, or None."""
        return None

    async def rerank(self, prompt: str, candidate_ids: list[str], blurbs: dict[str, str]) -> Optional[str]:  # pragma: no cover
        ...

    async def route(self, prompt: str, directory: str) -> Optional[str]:  # pragma: no cover
        """Choose the best-fit agent id from the full directory, or None."""
        return None

    async def judge_scope(self, prompt: str, *, org_summary: str) -> Optional[bool]:  # pragma: no cover
        """Is this prompt about the company? True=in, False=out, None=can't decide."""
        return None

    async def judge_group(self, prompt: str, roster) -> Optional[list]:  # pragma: no cover
        """Coordinate as a group? None=undecided, []=solo, [ids]=group members."""
        return None

    async def decide_share(
        self,
        *,
        requester: OrgProfile,
        owner: OrgProfile,
        item: ContextItem,
        intent: Intent,
    ) -> Optional[tuple[ShareOutcome, str]]:  # pragma: no cover
        """The owner agent's full share decision (no matrix). Returns (outcome, reason) or None."""
        return None
