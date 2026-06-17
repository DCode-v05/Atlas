"""
org/onboarding.py — role conferral as a CONVERSATION.

An employee boots generic ("Generalist — awaiting assignment"). It becomes a
"VP Engineering" only by receiving an onboarding message: a `propose` carrying
an offer {role, goal, backstory, scope, depth}. The employee writes that offer
into its Identity and replies acceptance. You literally watch an agent receive
its identity over the wire — which is exactly the point.
"""
from __future__ import annotations

from dataclasses import dataclass

from org.envelope import Performative, meta


@dataclass
class Identity:
    agent_id: str
    role: str = "Generalist"
    goal: str = ""
    backstory: str = ""
    scope: str = ""
    depth: int = 0
    manage: bool = False          # was this role hired to lead a sub-team?
    onboarded: bool = False

    def label(self) -> str:
        return self.role if self.onboarded else f"{self.agent_id} · unassigned"


def offer_message(*, role: str, goal: str, backstory: str, scope: str, depth: int,
                  run_id: str, hirer_role: str, hirer_id: str, context_id: str,
                  manage: bool = False) -> tuple[str, dict]:
    """Build the (text, metadata) a hirer sends to onboard a generic employee."""
    text = f"You are hired as {role}. Your goal: {goal}"
    md = meta(Performative.propose, role=hirer_role, intent=f"onboard as {role}",
              motivation=goal, delegation_depth=depth,
              extra={"runId": run_id, "contextId": context_id, "hirerId": hirer_id,
                     "offer": {"role": role, "goal": goal, "backstory": backstory,
                               "scope": scope, "depth": depth, "hirerId": hirer_id,
                               "manage": manage}})
    return text, md


def apply_offer(identity: Identity, offer: dict) -> None:
    """Write a received offer into the employee's identity (the moment of role conferral)."""
    identity.role = offer.get("role") or identity.role
    identity.goal = offer.get("goal") or ""
    identity.backstory = offer.get("backstory") or ""
    identity.scope = offer.get("scope") or ""
    identity.depth = int(offer.get("depth") or identity.depth)
    identity.manage = bool(offer.get("manage"))
    identity.onboarded = True
