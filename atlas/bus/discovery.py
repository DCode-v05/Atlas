"""Skill-matching discovery — both levels of the project's discovery story.

Level 1: a user prompt → the single best-matching agent.
Level 2: a discovered agent → other agents that can source context it needs.

The scorer is deliberately simple and explainable (tag overlap dominates), with
a small seniority bias for "leadership" words so strategy/approval prompts route
upward. An optional policy prefilter lets Level-2 skip agents the requester could
never be allowed to ask — which is also what powers "redundant contacts avoided".
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from atlas.bus.registry import AgentRegistry
from atlas.org.agent import OrgAgent

STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "with", "what", "whats", "how", "who", "can", "you",
        "please", "need", "want", "get", "give", "tell", "about", "from", "this",
        "that", "have", "has", "are", "our", "your", "their", "they", "them", "any",
        "all", "some", "out", "into", "onto", "was", "were", "will", "would", "should",
        "could", "doing", "done", "make", "made", "let", "lets", "got", "going",
    }
)

ROUTING_WORDS: frozenset[str] = frozenset(
    {
        "strategy", "roadmap", "approve", "approval", "decision", "budget", "vision",
        "company", "hiring", "escalate", "escalation", "priorities", "priority",
        "executive", "acquisition", "forecast", "okr", "okrs",
    }
)


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if len(t) > 2 and t not in STOPWORDS]


class Discovery:
    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry
        self._blob: dict[str, str] = {}

    def _search_blob(self, ag: OrgAgent) -> str:
        blob = self._blob.get(ag.id)
        if blob is None:
            blob = " ".join((s.name + " " + s.description).lower() for s in ag.card.skills)
            blob += " " + ag.profile.role_title.lower()
            self._blob[ag.id] = blob
        return blob

    def score(self, ag: OrgAgent, q_set: set[str]) -> float:
        tags = ag.card.skill_tags
        tag_overlap = len(q_set & tags)
        blob = self._search_blob(ag)
        token_match = sum(1 for t in q_set if t in blob)
        dept_hit = 1.0 if ag.profile.department.value in q_set else 0.0
        role_tokens = {t for t in re.findall(r"[a-z0-9]+", ag.profile.role_title.lower())}
        role_hit = 1.0 if (q_set & role_tokens) else 0.0
        # Seniority helps for leadership/strategy prompts, hurts for execution
        # prompts — so a "fix the billing API" task prefers an IC, while a
        # "company roadmap approval" prompt prefers a head/CEO.
        seniority = (int(ag.profile.level) - 1) / 4.0
        level_term = (0.8 * seniority) if (q_set & ROUTING_WORDS) else (-0.6 * seniority)
        return 2.0 * tag_overlap + 1.0 * token_match + 0.5 * dept_hit + 0.4 * role_hit + level_term

    def rank(
        self,
        query: str,
        *,
        exclude: Optional[set[str]] = None,
        pool: Optional[list[OrgAgent]] = None,
        prefilter: Optional[Callable[[OrgAgent], bool]] = None,
        top: int = 5,
    ) -> list[tuple[str, float]]:
        exclude = exclude or set()
        q_set = set(tokenize(query))
        if not q_set:
            return []
        candidates = pool if pool is not None else self.registry.all()
        scored: list[tuple[str, float]] = []
        for ag in candidates:
            if ag.id in exclude:
                continue
            if prefilter is not None and not prefilter(ag):
                continue
            s = self.score(ag, q_set)
            if s > 0:
                scored.append((ag.id, s))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:top]

    def route_prompt(self, query: str, *, top: int = 5, pool_ids=None) -> tuple[Optional[str], list[tuple[str, float]], float]:
        """Level-1: return (chosen_id, top_candidates, best_score). When ``pool_ids`` is given,
        ranking is restricted to those agents (the network members)."""
        pool = [self.registry.get(i) for i in pool_ids] if pool_ids is not None else None
        scored = self.rank(query, top=top, pool=pool)
        if not scored:
            return None, [], 0.0
        return scored[0][0], scored, scored[0][1]

    def find_sources(
        self,
        topic: str,
        requester_id: str,
        *,
        prefilter: Optional[Callable[[OrgAgent], bool]] = None,
        top: int = 5,
    ) -> list[tuple[str, float]]:
        """Level-2: rank other agents who could source ``topic`` for the requester."""
        return self.rank(topic, exclude={requester_id}, prefilter=prefilter, top=top)
