"""The runtime agent: identity + private memory + status.

An :class:`OrgAgent` is a stateful object (not Pydantic) so the registry can
attach an asyncio mailbox to it. Its *identity* (card + profile) is immutable
after generation; its *memory* (owned secrets + facts learned from others) and
*status* evolve as it communicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from atlas.a2a.ids import utcnow
from atlas.a2a.models import AgentCard
from atlas.org.ext_models import ContextItem, OrgProfile, Sensitivity


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    SPEAKING = "speaking"
    WAITING_HITL = "waiting_hitl"


@dataclass
class LearnedFact:
    """A fact an agent received from someone else, kept at the fidelity given.

    ``redacted=True`` means the agent only ever saw the safe summary, so it
    cannot re-share the raw secret — provenance and fidelity travel together.
    """

    item_id: str
    title: str
    body: str
    sensitivity: Sensitivity
    redacted: bool
    source_agent_id: str
    received_at: datetime = field(default_factory=utcnow)


@dataclass
class OrgAgent:
    card: AgentCard
    profile: OrgProfile
    owned_items: dict[str, ContextItem] = field(default_factory=dict)
    status: AgentStatus = AgentStatus.IDLE
    last_heartbeat: datetime = field(default_factory=utcnow)
    learned: dict[str, LearnedFact] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.profile.agent_id

    @property
    def name(self) -> str:
        return self.profile.human_name

    def knows(self, item_id: str, *, raw_required: bool) -> bool:
        """True if this agent already holds the fact at sufficient fidelity.

        Used to avoid redundant contacts: if I already have what I'd be asking
        for (raw when raw is needed), there's no reason to ask again.
        """
        if item_id in self.owned_items:
            return True
        fact = self.learned.get(item_id)
        if fact is None:
            return False
        return (not fact.redacted) if raw_required else True

    def remember(self, fact: LearnedFact) -> None:
        """Store a learned fact, upgrading redacted→raw but never downgrading."""
        existing = self.learned.get(fact.item_id)
        if existing and not existing.redacted and fact.redacted:
            return
        self.learned[fact.item_id] = fact
