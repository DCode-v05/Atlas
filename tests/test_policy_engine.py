"""Deterministic compliance Policy Engine — rule + combining tests.

Each test pins one rule (or the most-restrictive-wins fold) over the system's data
model. The engine reviews the OWNER agent's decision and may only tighten it; these
assert the codified outcome for representative requests against the seeded item shapes.
"""

from __future__ import annotations

from atlas.org.ext_models import (
    ContextItem,
    Department,
    Intent,
    Level,
    OrgProfile,
    PurposeTag,
    Scope,
    Sensitivity,
    ShareDecision,
    ShareOutcome,
)
from atlas.policy import PolicyEngine

ENGINE = PolicyEngine()
SHARE, REDACT, ESCALATE, DENY = (
    ShareOutcome.SHARE,
    ShareOutcome.REDACT,
    ShareOutcome.ESCALATE,
    ShareOutcome.DENY,
)


def prof(aid="AGT-R", dept=Department.ENGINEERING, clearance=3, teams=(), projects=()):
    return OrgProfile(
        agent_id=aid, human_name=aid, human_email=f"{aid}@x", department=dept,
        role_title="role", level=Level(min(max(clearance, 1), 5)), clearance=clearance,
        teams=list(teams), projects=list(projects),
    )


def item(title="Item", sens=Sensitivity.CONFIDENTIAL, scope=Scope.ORG, ref=None, tags=(),
         min_clr=1, summary="a safe summary", owner="AGT-O"):
    return ContextItem(
        item_id="item-x", owner_agent_id=owner, title=title, body="THE-BODY",
        sensitivity=sens, scope=scope, scope_ref=ref, min_clearance=min_clr,
        redacted_summary=summary, topic_tags=list(tags),
    )


def intent(purpose=PurposeTag.TASK_CONTEXT, scope=Scope.PROJECT):
    return Intent(motivation="m", purpose_tag=purpose, requested_topic="t", declared_scope=scope)


def _dec(outcome, it):
    body = it.body if outcome == SHARE else (it.redacted_summary if outcome == REDACT else None)
    return ShareDecision(outcome=outcome, reason="owner judged", item_id=it.item_id, rule_id="LLM-OWNER",
                         sensitivity=it.sensitivity, delivered_title=it.title, delivered_body=body)


OWNER = prof(aid="AGT-O", dept=Department.ENGINEERING, clearance=3)


def review(owner_outcome, requester, it, intent_=None, *, owner=OWNER, officer_id=None):
    return ENGINE.review(_dec(owner_outcome, it), requester, owner, it, intent_ or intent(), officer_id=officer_id)


# ─── single-rule pins ─────────────────────────────────────────────────────────
def test_clearance_gate_denies_under_cleared():
    it = item(sens=Sensitivity.CONFIDENTIAL, scope=Scope.ORG, min_clr=4)
    d = review(SHARE, prof(clearance=2), it)
    assert d.outcome == DENY and "CLEARANCE-GATE" in d.rule_id


def test_need_to_know_redacts_out_of_scope_confidential():
    it = item(sens=Sensitivity.CONFIDENTIAL, scope=Scope.PROJECT, ref="atlas-core")
    d = review(SHARE, prof(projects=["billing"]), it)  # not on atlas-core
    assert d.outcome == REDACT and "NEED-TO-KNOW" in d.rule_id
    assert d.delivered_body == it.redacted_summary  # a safe summary, not the body


def test_in_scope_confidential_concurs_with_share():
    it = item(sens=Sensitivity.CONFIDENTIAL, scope=Scope.PROJECT, ref="atlas-core")
    d = review(SHARE, prof(projects=["atlas-core"]), it)
    assert d.outcome == SHARE and d.rule_id == "LLM-OWNER"  # engine concurs, owner's decision stands


def test_least_privilege_escalates_out_of_scope_restricted():
    it = item(sens=Sensitivity.RESTRICTED, scope=Scope.TEAM, ref="devops-team-1")
    d = review(SHARE, prof(teams=["engineering-team-1"]), it)  # out of scope
    # soft floor: not a flat deny — routed to a human to decide the exception
    assert d.outcome == ESCALATE and "LEAST-PRIV-ESCALATE" in d.rule_id


def test_incident_carveout_suppresses_the_tightening():
    it = item(sens=Sensitivity.RESTRICTED, scope=Scope.TEAM, ref="devops-team-1")
    r = prof(dept=Department.DEVOPS, teams=["engineering-team-1"])  # responder, out of scope
    d = review(SHARE, r, it, intent(purpose=PurposeTag.INCIDENT))
    assert d.outcome == SHARE  # incident carve-out suppresses need-to-know + least-priv; nothing else tightens


def test_pci_secret_denies_unentitled():
    it = item(title="Stripe live secret key", sens=Sensitivity.SECRET, scope=Scope.PROJECT, ref="billing",
              tags=("billing", "secrets", "payments"), summary="[redacted payment credential]")
    d = review(SHARE, prof(projects=["mobile"]), it)  # no billing/incident nexus
    assert d.outcome == DENY


def test_pci_secret_escalates_entitled():
    it = item(title="Stripe live secret key", sens=Sensitivity.SECRET, scope=Scope.PROJECT, ref="billing",
              tags=("billing", "secrets", "payments"), summary="[redacted payment credential]")
    d = review(SHARE, prof(projects=["billing"]), it)  # on billing → in-scope + entitled
    assert d.outcome == ESCALATE and "PCI-SECRET" in d.rule_id


def test_pii_social_request_denied():
    it = item(title="User PII dataset access key", sens=Sensitivity.SECRET, scope=Scope.PROJECT, ref="atlas-core",
              tags=("data", "pii", "secrets"), summary="[redacted data-access credential]")
    r = prof(dept=Department.DATA, projects=["atlas-core"])  # in-scope but social purpose
    d = review(SHARE, r, it, intent(purpose=PurposeTag.SOCIAL))
    assert d.outcome == DENY and "PII-PURPOSE" in d.rule_id


def test_mnpi_escalates_for_non_business_disclosure():
    it = item(title="Unannounced pricing change", sens=Sensitivity.CONFIDENTIAL, scope=Scope.ORG,
              tags=("pricing", "billing", "revenue"))
    d = review(SHARE, prof(dept=Department.MARKETING), it, intent(purpose=PurposeTag.SOCIAL))
    assert d.outcome == ESCALATE and "FINANCIAL-MNPI" in d.rule_id


def test_secret_requires_four_eyes_even_when_in_scope():
    it = item(title="Embargoed CVE", sens=Sensitivity.SECRET, scope=Scope.ORG, min_clr=2, tags=("security",))
    d = review(SHARE, prof(dept=Department.SECURITY, clearance=3), it)  # cleared, in-scope, no pci/pii
    assert d.outcome == ESCALATE and "SECRET-FOUR-EYES" in d.rule_id


def test_officer_cannot_self_review_its_own_data():
    it = item(sens=Sensitivity.CONFIDENTIAL, scope=Scope.ORG, owner="AGT-SEC")
    officer = prof(aid="AGT-SEC", dept=Department.SECURITY, clearance=4)
    d = ENGINE.review(_dec(SHARE, it), prof(), officer, it, intent(), officer_id="AGT-SEC")
    assert d.outcome == ESCALATE and "OFFICER-SELF-REVIEW" in d.rule_id


# ─── invariants ───────────────────────────────────────────────────────────────
def test_tighten_only_never_loosens():
    it = item(sens=Sensitivity.PUBLIC, scope=Scope.ORG)  # no rule tightens a public item
    assert review(DENY, prof(), it).outcome == DENY        # owner DENY stays DENY (can't loosen)
    assert review(ESCALATE, prof(), it).outcome == ESCALATE  # owner ESCALATE never drops to share/redact
    assert review(SHARE, prof(), it).outcome == SHARE      # public → concur


def test_public_and_internal_always_concur():
    it = item(sens=Sensitivity.INTERNAL, scope=Scope.TEAM, ref="x-team")
    d = review(SHARE, prof(clearance=1, teams=["other-team"]), it)  # out of scope, but internal
    assert d.outcome == SHARE and d.rule_id == "LLM-OWNER"


def test_combining_takes_the_most_restrictive():
    # under-cleared (→DENY) AND out-of-scope confidential (→REDACT): DENY wins.
    it = item(sens=Sensitivity.CONFIDENTIAL, scope=Scope.PROJECT, ref="atlas-core", min_clr=4)
    d = review(SHARE, prof(clearance=2, projects=["billing"]), it)
    assert d.outcome == DENY and "CLEARANCE-GATE" in d.rule_id


def test_explain_lists_every_firing_rule():
    it = item(title="Stripe live secret key", sens=Sensitivity.SECRET, scope=Scope.PROJECT, ref="billing",
              tags=("billing", "secrets", "payments"), summary="[redacted payment credential]")
    fired = ENGINE.explain(_dec(SHARE, it), prof(projects=["mobile"]), OWNER, it, intent())
    ids = {rid for rid, _, _ in fired}
    assert "POLICY/LEAST-PRIV-ESCALATE" in ids and "POLICY/PCI-SECRET" in ids  # both fire; max() still picks DENY (PCI keeps the payment secret hard)
