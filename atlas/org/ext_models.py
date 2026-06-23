"""Org-extension domain models — the concepts Atlas layers on top of A2A.

These ride inside A2A messages / cards via the extension URIs in
``a2a/extensions.py``. They are the vocabulary of the communication layer:
who an agent is, how sensitive a piece of knowledge is, why someone is asking
for it, and what the share decision was.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from atlas.a2a.extensions import ORG_PROFILE_EXT
from atlas.a2a.ids import new_id, utcnow
from atlas.a2a.models import AgentCard, AgentExtension

# ─── Org identity enums ───────────────────────────────────────────────────────


class Department(str, Enum):
    EXEC = "exec"
    ENGINEERING = "engineering"
    PRODUCT = "product"
    QA = "qa"
    DEVOPS = "devops"
    SALES = "sales"
    DESIGN = "design"
    DATA = "data"
    MARKETING = "marketing"
    SUPPORT = "support"
    SECURITY = "security"
    HR = "hr"


class Level(int, Enum):
    IC = 1
    LEAD = 2
    MANAGER = 3
    DEPT_HEAD = 4
    CEO = 5


# ─── Need-to-know enums ───────────────────────────────────────────────────────


class Sensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    SECRET = "secret"


#: Ordered rank for comparisons (higher = more sensitive).
SENSITIVITY_RANK: dict[Sensitivity, int] = {
    Sensitivity.PUBLIC: 0,
    Sensitivity.INTERNAL: 1,
    Sensitivity.CONFIDENTIAL: 2,
    Sensitivity.RESTRICTED: 3,
    Sensitivity.SECRET: 4,
}


class Scope(str, Enum):
    """The need-to-know boundary a piece of knowledge belongs to."""

    ORG = "org"
    PROJECT = "project"
    TEAM = "team"
    ROLE = "role"
    PRIVATE = "private"


class PurposeTag(str, Enum):
    TASK_CONTEXT = "task-context"
    STATUS_CHECK = "status-check"
    HANDOFF = "handoff"
    INCIDENT = "incident"
    PLANNING = "planning"
    SOCIAL = "social"


#: Purpose tags that justify accessing scoped/sensitive context.
LEGITIMATE_PURPOSES: frozenset[PurposeTag] = frozenset(
    {
        PurposeTag.TASK_CONTEXT,
        PurposeTag.HANDOFF,
        PurposeTag.INCIDENT,
        PurposeTag.PLANNING,
    }
)


class ShareOutcome(str, Enum):
    SHARE = "share"
    REDACT = "redact"
    DENY = "deny"
    ESCALATE = "escalate"


class CoordinationMode(str, Enum):
    INDIVIDUAL = "individual"
    GROUP = "group"


# ─── Core domain models ───────────────────────────────────────────────────────


class OrgProfile(BaseModel):
    """An agent's place in the company. Carried on its Agent Card extension."""

    agent_id: str
    human_name: str
    human_email: str
    department: Department
    role_title: str
    level: Level
    clearance: int
    goal: str = ""  # the agent's standing responsibility ("like humans have")
    reports_to: Optional[str] = None
    manages: list[str] = Field(default_factory=list)
    teams: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    security_cleared: bool = False


class User(BaseModel):
    """A human user of Atlas, associated 1:1 with the agent that represents them.

    Every agent has exactly one human behind it; that human is the ``User``. The
    ``agent_id`` is the user's standing assignment — when this user submits a
    prompt, it is attributed to them and to the agent they operate.
    """

    user_id: str
    name: str
    email: str
    agent_id: str
    department: Department
    role_title: str


class ContextItem(BaseModel):
    """One unit of shareable (and possibly sensitive) knowledge an agent owns."""

    item_id: str
    owner_agent_id: str
    title: str
    body: str
    sensitivity: Sensitivity
    scope: Scope
    scope_ref: Optional[str] = None  # project/team/role this item is bound to
    min_clearance: int = 1
    redacted_summary: Optional[str] = None  # safe form returned on REDACT
    topic_tags: list[str] = Field(default_factory=list)


class Intent(BaseModel):
    """The motivation behind an agent→agent request. Read by the owner agent + compliance reviewer."""

    motivation: str  # natural-language "why I'm asking"
    purpose_tag: PurposeTag
    requested_topic: str
    declared_scope: Scope
    task_ref: Optional[str] = None


class ShareDecision(BaseModel):
    """The need-to-know ruling on a single share request (the owner agent's LLM
    decision, possibly tightened by the Policy Officer)."""

    outcome: ShareOutcome
    reason: str
    item_id: str
    rule_id: str
    sensitivity: Sensitivity
    delivered_title: Optional[str] = None
    delivered_body: Optional[str] = None


# ─── Conversation + coordination state ────────────────────────────────────────


class Thread(BaseModel):
    """A 1:1 conversation between two agents within a context."""

    thread_id: str = Field(default_factory=lambda: new_id("thr-"))
    context_id: str
    participants: list[str]  # exactly two agent ids
    task_id: Optional[str] = None
    topic: str = ""
    message_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class GroupSession(BaseModel):
    """A team group chat coordinating around a topic."""

    group_id: str = Field(default_factory=lambda: new_id("grp-"))
    context_id: str
    team_id: str
    topic: str
    members: list[str]
    initiator: str
    message_ids: list[str] = Field(default_factory=list)
    shared_items: list[str] = Field(default_factory=list)
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class HitlRequest(BaseModel):
    """A sensitive-share escalation awaiting the global operator's decision."""

    request_id: str = Field(default_factory=lambda: new_id("hitl-"))
    task_id: str
    context_id: str
    owner_agent_id: str
    requester_agent_id: str
    item_id: str
    item_title: str
    intent: Intent
    proposed_outcome: ShareOutcome
    sensitivity: Sensitivity
    reason: str
    state: Literal["pending", "approved", "denied"] = "pending"
    decided_by: Optional[str] = None
    decided_outcome: Optional[ShareOutcome] = None
    created_at: datetime = Field(default_factory=utcnow)
    decided_at: Optional[datetime] = None


class Metrics(BaseModel):
    """Communication-efficiency counters (per-context and aggregated global)."""

    context_id: Optional[str] = None
    hops: int = 0
    messages: int = 0
    share_requests: int = 0
    items_shared: int = 0
    items_redacted: int = 0
    items_denied: int = 0
    redundant_contacts_avoided: int = 0
    hitl_escalations: int = 0
    distinct_agents_contacted: int = 0
    policy_reviews: int = 0       # deterministic compliance reviews the Policy Engine performed
    policy_overrides: int = 0     # times the Policy Engine tightened a real owner LLM decision
    policy_pregates: int = 0      # times the Policy Engine decided outright, owner LLM skipped (denials/secrets)

    def derived(self) -> dict[str, float]:
        """Ratios the UI shows; safe against divide-by-zero."""
        reqs = self.share_requests or 0
        return {
            "redaction_ratio": round(self.items_redacted / reqs, 3) if reqs else 0.0,
            "share_ratio": round(self.items_shared / reqs, 3) if reqs else 0.0,
            "hitl_ratio": round(self.hitl_escalations / reqs, 3) if reqs else 0.0,
            "efficiency": round(self.items_shared / self.messages, 3)
            if self.messages
            else 0.0,
            "policy_override_ratio": round(self.policy_overrides / self.policy_reviews, 3)
            if self.policy_reviews
            else 0.0,
        }


# ─── Card <-> profile helpers ─────────────────────────────────────────────────


def profile_to_extension(profile: OrgProfile) -> AgentExtension:
    """Wrap an :class:`OrgProfile` as the card's org-profile extension."""
    return AgentExtension(
        uri=ORG_PROFILE_EXT,
        version="1",
        metadata=profile.model_dump(mode="json"),
    )


def org_profile_of(card: AgentCard) -> OrgProfile:
    """Read the :class:`OrgProfile` back out of an Agent Card."""
    ext = card.extension(ORG_PROFILE_EXT)
    if ext is None:
        raise ValueError(f"card {card.id} has no org-profile extension")
    return OrgProfile(**ext.metadata)
