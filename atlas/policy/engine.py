"""``PolicyEngine`` — the deterministic compliance review (the **Policy Engine**).

Runs AFTER the owner agent's LLM has decided share / redact / deny / escalate on its
own data, and **tightens** that decision so it satisfies codified compliance rules — it
never loosens it. This is the auditable, deterministic compliance control that replaces
the former LLM "Policy Officer" agent: the owner's primary judgment stays the model's,
but the *floor* is the policy.

Combining algorithm (OASIS XACML 3.0 *deny-overrides* / AWS IAM, expressed as a lattice
max): start from the owner's decision, evaluate every rule (``rules.py``), and take the
**most restrictive** outcome on ``SHARE < REDACT < ESCALATE < DENY``. Ties favour the
owner's decision (concur). The result is therefore always ``>=`` the owner's decision —
the tighten-only invariant.
"""

from __future__ import annotations

from atlas.org.ext_models import ContextItem, Intent, OrgProfile, ShareDecision, ShareOutcome
from atlas.policy.rules import RULES, CONSERVATISM, Ctx, classify, in_scope, is_incident_responder


def _finalize(item: ContextItem, outcome: ShareOutcome, rule_id: str, reason: str) -> ShareDecision:
    body: str | None = None
    if outcome == ShareOutcome.SHARE:
        body = item.body
    elif outcome == ShareOutcome.REDACT:
        # REDACT always delivers a pre-authored SAFE summary (never a partial secret),
        # so it stays a valid outcome even for credentials.
        body = item.redacted_summary or f"[redacted: {item.title}]"
    return ShareDecision(
        outcome=outcome, reason=reason, item_id=item.item_id, rule_id=rule_id,
        sensitivity=item.sensitivity, delivered_title=item.title, delivered_body=body,
    )


class PolicyEngine:
    """Stateless, deterministic compliance-review engine. Tighten-only."""

    def _ctx(self, decision, requester, owner, item, intent, officer_id, cross_org) -> Ctx:
        return Ctx(
            requester=requester, owner=owner, item=item, intent=intent,
            owner_outcome=decision.outcome, officer_id=officer_id,
            scoped=in_scope(item, requester), classes=classify(item),
            incident=is_incident_responder(requester, item, intent),
            cross_org=cross_org,
        )

    def review(
        self, decision: ShareDecision, requester: OrgProfile, owner: OrgProfile,
        item: ContextItem, intent: Intent, *, officer_id: str | None = None, cross_org: bool = False,
    ) -> ShareDecision:
        """Return the owner's ``decision`` unchanged (concur), or a tightened
        ``ShareDecision`` stamped ``rule_id="POLICY/<RULE>"``. ``cross_org`` marks a request from a
        DIFFERENT organisation — the federation boundary, where only PUBLIC data may cross."""
        ctx = self._ctx(decision, requester, owner, item, intent, officer_id, cross_org)
        winner_rank = CONSERVATISM[decision.outcome]
        winner = (decision.outcome, decision.rule_id, decision.reason)
        for rule_id, fn in RULES:
            res = fn(ctx)
            if res is None:
                continue
            outcome, reason = res
            if CONSERVATISM[outcome] > winner_rank:  # strictly more restrictive wins; ties keep owner
                winner_rank = CONSERVATISM[outcome]
                winner = (outcome, f"POLICY/{rule_id}", reason)
        outcome, rule_id, reason = winner
        if outcome == decision.outcome:
            return decision  # concur — the owner's decision (and its delivered body) stands
        return _finalize(item, outcome, rule_id, reason)

    def explain(
        self, decision: ShareDecision, requester: OrgProfile, owner: OrgProfile,
        item: ContextItem, intent: Intent, *, officer_id: str | None = None, cross_org: bool = False,
    ) -> list[tuple[str, str, str]]:
        """Every firing rule as ``(rule_id, outcome, reason)`` — for audit / observability."""
        ctx = self._ctx(decision, requester, owner, item, intent, officer_id, cross_org)
        fired: list[tuple[str, str, str]] = []
        for rule_id, fn in RULES:
            res = fn(ctx)
            if res is not None:
                fired.append((f"POLICY/{rule_id}", res[0].value, res[1]))
        return fired
