"""A2A Agent Card tiering — public vs authenticated *extended* cards.

A2A v1.0.0 lets a server publish a **public** Agent Card (the discovery entry
point) and serve a richer **extended** card to authenticated callers
(``capabilities.extendedAgentCard`` + ``GetExtendedAgentCard``). Atlas tiers on
its need-to-know seam:

* **public** — identity, skills, capabilities, security schemes, transport. What
  any client may discover. The internal **org-profile** extension (department,
  level, clearance, reporting line, goal) is withheld.
* **extended** — the full card *including* the org-profile extension. Served only
  to an authenticated caller (the edge API key), since an agent's place in the
  hierarchy + clearance is internal company structure.

These are pure projections of the immutable generated card — no runtime state.
"""

from __future__ import annotations

from atlas.a2a.extensions import ORG_PROFILE_EXT
from atlas.a2a.models import AgentCard, AgentExtension, AgentInterface, AgentSkill


def _public_extensions(card: AgentCard) -> list[AgentExtension]:
    """The extension declarations a PUBLIC client may see — need-to-know + coordination, but NOT
    the org-profile (internal hierarchy / clearance), which is extended-card-only."""
    return [
        AgentExtension(uri=ext.uri, description=ext.description, required=ext.required, version=ext.version)
        for ext in card.capabilities.extensions
        if ext.uri != ORG_PROFILE_EXT
    ]


def public_agent_card(card: AgentCard) -> dict:
    """The Agent Card an UNAUTHENTICATED client sees — identity, skills,
    capabilities, security, transport — but NOT the internal org profile."""
    pub = card.model_copy(deep=True)
    pub.capabilities.extensions = _public_extensions(card)
    return pub.model_dump(mode="json")


def extended_agent_card(card: AgentCard) -> dict:
    """The richer card an AUTHENTICATED caller sees — the full card including the
    org-profile extension (department / role / level / clearance / reportsTo / goal)."""
    return card.model_dump(mode="json")


def service_agent_card(snapshot) -> dict:
    """The Atlas service's primary public card, served at
    ``/.well-known/agent-card.json`` — the standard A2A discovery entry point.

    It represents the gateway in front of the 100 agents and carries the same
    security schemes + capabilities, plus a pointer to the agent catalog."""
    base = snapshot.agents[snapshot.ceo_id].card
    # The well-known service card is PUBLIC: advertise the extension mechanism (need-to-know /
    # coordination) but strip the org-profile so the CEO's hierarchy/clearance never leaks.
    caps = base.capabilities.model_copy(deep=True)
    caps.extensions = _public_extensions(base)
    card = AgentCard(
        id="atlas",
        name="Atlas",
        description=(
            f"A2A gateway for the Atlas software company — {len(snapshot.agents)} agents across "
            f"{len(snapshot.departments)} departments. Discover individual agents via the catalog; "
            "each exposes a public card and an authenticated extended card."
        ),
        provider=base.provider,
        version="1.0.0",
        protocolVersion="1.0.0",
        url="https://atlas.dev/.well-known/agent-card.json",
        preferredTransport="in-process",
        capabilities=caps,
        skills=[
            AgentSkill(id="agent-discovery", name="Agent Discovery",
                       description="Find the right agent for a task across the org.",
                       tags=["discovery", "routing", "a2a"]),
            AgentSkill(id="task-execution", name="Task Execution",
                       description="Route a prompt to an agent and run it through the need-to-know pipeline.",
                       tags=["tasks", "coordination", "need-to-know"]),
        ],
        securitySchemes=dict(base.securitySchemes),
        securityRequirements=[dict(r) for r in base.securityRequirements],
        interfaces=[AgentInterface(transport="in-process", url="atlas://gateway")],
    )
    out = card.model_dump(mode="json")
    # Non-standard discovery hint (A2A clients ignore unknown keys): where to enumerate agents.
    out["x-atlas-agent-catalog"] = "/.well-known/agents.json"
    out["x-atlas-agent-count"] = len(snapshot.agents)
    return out


def agent_catalog(snapshot) -> dict:
    """A discovery index of every agent + the URL of its public card."""
    return {
        "count": len(snapshot.agents),
        "agents": [
            {
                "id": ag.id,
                "name": ag.name,
                "role": ag.profile.role_title,
                "department": ag.profile.department.value,
                "card_url": f"/.well-known/agents/{ag.id}/agent-card.json",
            }
            for ag in snapshot.agents.values()
        ],
    }
