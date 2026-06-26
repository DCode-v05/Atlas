"""``FederationGateway`` — the one and only door between organisations.

Every cross-org interaction goes through here, and **``cross_org=True`` originates
nowhere else**. Inside an org, the Router is the single chokepoint; between orgs, this
gateway is. The two invariants it guarantees:

1. **Sealed orgs.** Each org's Router only knows its own registry, so an org's agents
   cannot reach a peer except by calling the gateway. There is no other path.
2. **The target org decides about its own data.** A request from org A for an item in
   org B is run through **B's** owner agent + **B's** Policy Engine — with ``cross_org``
   set — so the federation boundary (only PUBLIC may cross) is B's rule on B's data.

Discovery across the boundary uses peers' **PUBLIC** agent cards only (org-profile
stripped), so a foreign org never sees a peer's internal hierarchy, clearances, or
skill detail — just enough to address a public request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from atlas.a2a.cards import public_agent_card
from atlas.org.ext_models import ContextItem, Intent, ShareDecision, ShareOutcome

if TYPE_CHECKING:  # avoids an import cycle (runtime.py imports this module)
    from atlas.runtime import OrgRuntime


class FederationGateway:
    """Routes and authorises communication *between* sealed organisations."""

    def __init__(self, orgs: "dict[str, OrgRuntime]") -> None:
        self._orgs = orgs

    # ── topology ────────────────────────────────────────────────────────────────
    @property
    def org_ids(self) -> list[str]:
        return list(self._orgs)

    def org(self, org_id: str) -> "OrgRuntime":
        return self._orgs[org_id]

    def peers(self, org_id: str) -> "list[OrgRuntime]":
        """Every org that is NOT ``org_id`` — the foreign networks it may address."""
        return [o for oid, o in self._orgs.items() if oid != org_id]

    def route_to_peer(self, prompt: str, *, exclude_org_id: str, gate_floor: float) -> "Optional[tuple[str, str, float]]":
        """Pick the SINGLE best peer org that has **joined members** able to handle ``prompt``
        (returns ``(peer_org_id, peer_agent_id, score)`` or ``None``). One best peer, never a
        fan-out across all peers — N orgs already share one rate-limit bucket. Used by the
        auto-fallback: when no LOCAL member fits, a peer with the right joined team may, and only
        PUBLIC information will then cross the boundary."""
        best: Optional[tuple[str, str, float]] = None
        for org in self.peers(exclude_org_id):
            pool = org.orchestrator._pool_ids()  # joined members (None ⇒ gating off ⇒ all)
            if pool is not None and not pool:
                continue  # this peer has nobody in its network
            _, scored = org.router.route_prompt(prompt, pool_ids=pool)
            if not scored:
                continue
            agent_id, score = scored[0]
            if score >= gate_floor and (best is None or score > best[2]):
                best = (org.org_id, agent_id, score)
        return best

    def public_directory(self, target_org_id: str) -> list[dict]:
        """The peer org's PUBLIC agent cards — all a foreign org is allowed to see of it
        (name/role/skills, but org-profile: dept/level/reportsTo/clearance stripped)."""
        org = self._orgs[target_org_id]
        return [public_agent_card(ag.card) for ag in org.snapshot.agents.values()]

    # ── the boundary crossing ─────────────────────────────────────────────────────
    async def request_across(
        self, *, requester, target_org_id: str, item: ContextItem, intent: Intent,
        context_id: str = "x-org",
    ) -> ShareDecision:
        """Ask org ``target_org_id`` for ``item`` on behalf of ``requester`` (a foreign
        ``OrgAgent``). The TARGET org's machinery decides — its owner agent's judgement
        under its Policy Engine, with the federation boundary in force (only PUBLIC may
        cross; anything else is denied). The returned ``ShareDecision`` is the answer that
        crosses back to the caller — no Task is opened in the target org (the minimal model:
        the gateway returns the decision, the caller's own Task records it)."""
        target = self._orgs[target_org_id]
        return await target.orchestrator.decide_cross_org_share(requester, item, intent, context_id)

    async def source_public_context(
        self, *, requester, target_org_id: str, items: list[ContextItem], intent: Intent,
        context_id: str = "x-org",
    ) -> "list[tuple[ContextItem, ShareDecision]]":
        """Auto-fallback path: a foreign org needs several things from a peer. Each is run
        through the peer's machinery; only the items that legitimately cross (PUBLIC →
        SHARE) come back — everything internal/confidential/restricted/secret is denied at
        the boundary. The result is therefore, by construction, **PUBLIC-only** — exactly
        "only the necessary things leave the building"."""
        out: list[tuple[ContextItem, ShareDecision]] = []
        for it in items:
            decision = await self.request_across(
                requester=requester, target_org_id=target_org_id, item=it,
                intent=intent, context_id=context_id,
            )
            if decision.outcome in (ShareOutcome.SHARE, ShareOutcome.REDACT) and decision.delivered_body is not None:
                out.append((it, decision))
        return out
