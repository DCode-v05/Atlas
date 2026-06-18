"""``evaluate_share`` — the graded core.

Pipeline (order is load-bearing):
  1. self short-circuit (you can always read your own item)
  2. base matrix lookup via (sensitivity, selected column)
  3. loosen-only rule overrides: CHAIN1 (manager↔report), CEO1, SEC1 (incident)
  4. SECRET hard-cap — defense in depth: a SECRET item's loosest possible
     outcome is ESCALATE, full stop. No override may leak it.
  5. (later, at call site) an LLM may only *tighten* via ``tighten_only``.

Every decision carries a human-readable ``reason`` and a ``rule_id`` recording
exactly which cell/override fired, so tests can assert *why*, not just *what*.
"""

from __future__ import annotations

from atlas.org.ext_models import (
    SENSITIVITY_RANK,
    ContextItem,
    Department,
    Intent,
    Level,
    OrgProfile,
    PurposeTag,
    Sensitivity,
    ShareDecision,
    ShareOutcome,
)
from atlas.policy.rules import (
    MATRIX,
    SEV_CODE,
    Column,
    ScopeMatch,
    classify_intent,
    compute_scope_match,
    is_restricted_or_below,
    select_column,
)

#: Ordering used for the loosen-only overrides and the tighten-only LLM hook.
CONSERVATISM: dict[ShareOutcome, int] = {
    ShareOutcome.SHARE: 0,
    ShareOutcome.REDACT: 1,
    ShareOutcome.ESCALATE: 2,
    ShareOutcome.DENY: 3,
}


def _finalize(item: ContextItem, outcome: ShareOutcome, rule_id: str, reason: str) -> ShareDecision:
    body: str | None = None
    if outcome == ShareOutcome.SHARE:
        body = item.body
    elif outcome == ShareOutcome.REDACT:
        # REDACT must always deliver *something* safe, even if no summary was authored.
        body = item.redacted_summary or f"[redacted: {item.title}]"
    return ShareDecision(
        outcome=outcome,
        reason=reason,
        item_id=item.item_id,
        rule_id=rule_id,
        sensitivity=item.sensitivity,
        delivered_title=item.title,
        delivered_body=body,
    )


def _base_reason(outcome: ShareOutcome, item: ContextItem, sm: ScopeMatch, clr_ok: bool) -> str:
    sev = item.sensitivity.value
    under = "" if clr_ok else ", under-cleared"
    if outcome == ShareOutcome.SHARE:
        return f"'{item.title}' is {sev}; requester is in scope and authorised — shared in full."
    if outcome == ShareOutcome.REDACT:
        return f"'{item.title}' is {sev}; access is limited ({sm.value}{under}) — only a safe summary was shared."
    if outcome == ShareOutcome.ESCALATE:
        return f"'{item.title}' is {sev}; sharing needs the owner's human approval (HITL)."
    return f"'{item.title}' is {sev} and outside the requester's need-to-know (scope {item.scope.value}{under}) — denied."


def evaluate_share(
    requester: OrgProfile,
    owner: OrgProfile,
    item: ContextItem,
    intent: Intent,
    *,
    requester_manages_owner: bool = False,
) -> ShareDecision:
    # 1. self
    if requester.agent_id == owner.agent_id:
        return _finalize(item, ShareOutcome.SHARE, "SELF", f"'{item.title}' is the requester's own item.")

    # 2. base matrix
    sm = compute_scope_match(item, requester, owner)
    clr_ok = requester.clearance >= item.min_clearance
    ic = classify_intent(intent.purpose_tag, intent.declared_scope, item)
    col = select_column(sm, clr_ok, ic)
    outcome = MATRIX[(item.sensitivity, col)]
    rule = f"{SEV_CODE[item.sensitivity]}-{col.value}"
    reason = _base_reason(outcome, item, sm, clr_ok)

    # 3. loosen-only overrides
    if requester_manages_owner and outcome != ShareOutcome.SHARE:
        if is_restricted_or_below(item.sensitivity):
            if CONSERVATISM[outcome] > CONSERVATISM[ShareOutcome.SHARE]:
                outcome, rule = ShareOutcome.SHARE, rule + "+CHAIN1"
                reason = f"Requester manages the owner; '{item.title}' ({item.sensitivity.value}) shared within the reporting line."
        elif CONSERVATISM[outcome] > CONSERVATISM[ShareOutcome.ESCALATE]:
            outcome, rule = ShareOutcome.ESCALATE, rule + "+CHAIN1"
            reason = f"Requester manages the owner, but '{item.title}' is secret — owner approval still required."

    if requester.level == Level.CEO and outcome != ShareOutcome.SHARE:
        if is_restricted_or_below(item.sensitivity):
            if CONSERVATISM[outcome] > CONSERVATISM[ShareOutcome.SHARE]:
                outcome, rule = ShareOutcome.SHARE, rule + "+CEO1"
                reason = f"CEO authority: '{item.title}' ({item.sensitivity.value}) shared."
        elif CONSERVATISM[outcome] > CONSERVATISM[ShareOutcome.ESCALATE]:
            outcome, rule = ShareOutcome.ESCALATE, rule + "+CEO1"
            reason = f"Even the CEO needs approval for secret '{item.title}'."

    if requester.department == Department.SECURITY and intent.purpose_tag == PurposeTag.INCIDENT:
        if outcome == ShareOutcome.DENY:
            outcome, rule = ShareOutcome.ESCALATE, rule + "+SEC1"
            reason = f"Security incident: escalating '{item.title}' for approval rather than denying."
        elif outcome == ShareOutcome.REDACT:
            outcome, rule = ShareOutcome.SHARE, rule + "+SEC1"
            reason = f"Security incident: '{item.title}' shared to support response."

    # 4. SECRET hard cap
    if item.sensitivity == Sensitivity.SECRET and outcome in (ShareOutcome.SHARE, ShareOutcome.REDACT):
        outcome, rule = ShareOutcome.ESCALATE, rule + "+SECRETCAP"
        reason = f"'{item.title}' is secret — never shared without explicit human approval."

    return _finalize(item, outcome, rule, reason)


def tighten_only(
    base: ShareDecision,
    candidate_outcome: ShareOutcome,
    candidate_reason: str,
    item: ContextItem,
) -> ShareDecision:
    """Apply an LLM's judgement, but only if it makes the decision MORE cautious.

    The rule-based decision is the safety floor; the model can add caution
    (SHARE→REDACT→ESCALATE→DENY) but can never loosen it.
    """
    if CONSERVATISM[candidate_outcome] > CONSERVATISM[base.outcome]:
        return _finalize(item, candidate_outcome, base.rule_id + "+LLM", candidate_reason)
    return base
