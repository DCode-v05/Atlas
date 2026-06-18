"""Tests for the need-to-know policy engine.

Strategy (per design review): the bugs live in *column selection* and *data
alignment*, not in the 25 named cells — so we test the Cartesian product of the
axes, assert the ``rule_id`` (the *why*), and hammer the SECRET-cap invariant
across overrides.
"""

from __future__ import annotations

import itertools

import pytest

from atlas.org.ext_models import (
    ContextItem,
    Department,
    Intent,
    Level,
    OrgProfile,
    PurposeTag,
    Scope,
    Sensitivity,
    ShareOutcome,
)
from atlas.policy import evaluate_share, tighten_only
from atlas.policy.engine import _finalize
from atlas.policy.rules import (
    MATRIX,
    Column,
    IntentClass,
    ScopeMatch,
    select_column,
)

SHARE, REDACT, DENY, ESCALATE = (
    ShareOutcome.SHARE,
    ShareOutcome.REDACT,
    ShareOutcome.DENY,
    ShareOutcome.ESCALATE,
)


# ─── builders ─────────────────────────────────────────────────────────────────


def prof(aid, dept, level, *, clearance=None, teams=(), projects=(), security=False):
    return OrgProfile(
        agent_id=aid, human_name=aid, human_email=f"{aid}@atlas.dev",
        department=dept, role_title=f"{dept.value}-{level.name}", level=level,
        clearance=clearance if clearance is not None else int(level),
        teams=list(teams), projects=list(projects), security_cleared=security,
    )


def item(sens, scope, *, ref=None, min_clr=1, owner="OWN", summary="[safe summary]"):
    return ContextItem(
        item_id="it-1", owner_agent_id=owner, title="The Item", body="RAW-SECRET-BODY",
        sensitivity=sens, scope=scope, scope_ref=ref, min_clearance=min_clr,
        redacted_summary=summary,
    )


def intent(purpose, scope):
    return Intent(motivation="because", purpose_tag=purpose, requested_topic="topic", declared_scope=scope)


OWNER = prof("OWN", Department.ENGINEERING, Level.MANAGER)


# ─── column selection: full Cartesian product ─────────────────────────────────


def test_column_selection_precedence_is_total_and_pinned():
    for sm, clr_ok, ic in itertools.product(ScopeMatch, (True, False), IntentClass):
        col = select_column(sm, clr_ok, ic)
        if ic == IntentClass.ILLEGIT:
            assert col == Column.ILLEGIT
        elif (not clr_ok) or sm == ScopeMatch.NONE:
            assert col == Column.OUT
        elif sm == ScopeMatch.EXACT and ic == IntentClass.LEGIT:
            assert col == Column.EXACT_LEGIT
        elif sm == ScopeMatch.EXACT and ic == IntentClass.WEAK:
            assert col == Column.EXACT_WEAK
        elif sm == ScopeMatch.RELATED:
            assert col == Column.RELATED
        else:
            assert col == Column.OUT


def test_matrix_is_complete():
    for sens in Sensitivity:
        for col in Column:
            assert (sens, col) in MATRIX, (sens, col)


# ─── representative scenarios — assert outcome AND which rule fired ────────────


@pytest.mark.parametrize(
    "requester, it, intent_, manages, expected_outcome, rule_contains",
    [
        # self
        (OWNER, item(Sensitivity.SECRET, Scope.PROJECT, owner="OWN"),
         intent(PurposeTag.TASK_CONTEXT, Scope.PROJECT), False, SHARE, "SELF"),
        # public — always shared, even on a social ask
        (prof("R", Department.SALES, Level.IC), item(Sensitivity.PUBLIC, Scope.ORG),
         intent(PurposeTag.SOCIAL, Scope.ORG), False, SHARE, "P-"),
        # internal, in-team, legit
        (prof("R", Department.ENGINEERING, Level.IC, teams=["eng-team-1"]),
         item(Sensitivity.INTERNAL, Scope.TEAM, ref="eng-team-1"),
         intent(PurposeTag.TASK_CONTEXT, Scope.TEAM), False, SHARE, "I-exact_legit"),
        # internal, cross-dept (out) -> redact (with fallback body tested below)
        (prof("R", Department.SALES, Level.IC),
         item(Sensitivity.INTERNAL, Scope.TEAM, ref="eng-team-1"),
         intent(PurposeTag.TASK_CONTEXT, Scope.TEAM), False, REDACT, "I-out"),
        # confidential, org, weak intent -> redact
        (prof("R", Department.ENGINEERING, Level.IC),
         item(Sensitivity.CONFIDENTIAL, Scope.ORG),
         intent(PurposeTag.STATUS_CHECK, Scope.ORG), False, REDACT, "C-exact_weak"),
        # confidential, org, legit -> share
        (prof("R", Department.ENGINEERING, Level.IC),
         item(Sensitivity.CONFIDENTIAL, Scope.ORG),
         intent(PurposeTag.PLANNING, Scope.ORG), False, SHARE, "C-exact_legit"),
        # restricted, in-project, legit -> redact
        (prof("R", Department.ENGINEERING, Level.IC, projects=["billing"]),
         item(Sensitivity.RESTRICTED, Scope.PROJECT, ref="billing"),
         intent(PurposeTag.TASK_CONTEXT, Scope.PROJECT), False, REDACT, "R-exact_legit"),
        # restricted, in-project, weak (declared scope mismatch) -> escalate
        (prof("R", Department.ENGINEERING, Level.IC, projects=["billing"]),
         item(Sensitivity.RESTRICTED, Scope.PROJECT, ref="billing"),
         intent(PurposeTag.TASK_CONTEXT, Scope.TEAM), False, ESCALATE, "R-exact_weak"),
        # restricted, related (same dept not project) -> escalate
        (prof("R", Department.ENGINEERING, Level.IC, projects=["mobile"]),
         item(Sensitivity.RESTRICTED, Scope.PROJECT, ref="billing"),
         intent(PurposeTag.TASK_CONTEXT, Scope.PROJECT), False, ESCALATE, "R-related"),
        # restricted, cross-dept -> deny
        (prof("R", Department.SALES, Level.IC),
         item(Sensitivity.RESTRICTED, Scope.PROJECT, ref="billing"),
         intent(PurposeTag.TASK_CONTEXT, Scope.PROJECT), False, DENY, "R-out"),
        # secret, in-project, legit -> escalate (HITL)
        (prof("R", Department.ENGINEERING, Level.IC, projects=["billing"]),
         item(Sensitivity.SECRET, Scope.PROJECT, ref="billing"),
         intent(PurposeTag.TASK_CONTEXT, Scope.PROJECT), False, ESCALATE, "S-exact_legit"),
        # secret, related -> deny
        (prof("R", Department.ENGINEERING, Level.IC, projects=["mobile"]),
         item(Sensitivity.SECRET, Scope.PROJECT, ref="billing"),
         intent(PurposeTag.TASK_CONTEXT, Scope.PROJECT), False, DENY, "S-related"),
        # illegitimate intent overrides in-scope internal -> deny
        (prof("R", Department.ENGINEERING, Level.IC, teams=["eng-team-1"]),
         item(Sensitivity.INTERNAL, Scope.TEAM, ref="eng-team-1"),
         intent(PurposeTag.SOCIAL, Scope.TEAM), False, DENY, "I-illegit"),
        # under-cleared even though in scope -> out -> deny
        (prof("R", Department.ENGINEERING, Level.IC, clearance=1, projects=["billing"]),
         item(Sensitivity.CONFIDENTIAL, Scope.PROJECT, ref="billing", min_clr=3),
         intent(PurposeTag.TASK_CONTEXT, Scope.PROJECT), False, DENY, "C-out"),
        # CHAIN1: manager reads report's restricted data (cross-team) -> share
        (prof("R", Department.ENGINEERING, Level.MANAGER),
         item(Sensitivity.RESTRICTED, Scope.TEAM, ref="eng-team-9"),
         intent(PurposeTag.TASK_CONTEXT, Scope.TEAM), True, SHARE, "CHAIN1"),
        # CHAIN1 on a secret never shares — escalates
        (prof("R", Department.ENGINEERING, Level.MANAGER),
         item(Sensitivity.SECRET, Scope.PROJECT, ref="billing"),
         intent(PurposeTag.TASK_CONTEXT, Scope.PROJECT), True, ESCALATE, "CHAIN1"),
        # CEO can read confidential cross-dept
        (prof("R", Department.EXEC, Level.CEO),
         item(Sensitivity.CONFIDENTIAL, Scope.ORG),
         intent(PurposeTag.PLANNING, Scope.TEAM), False, SHARE, "CEO1"),
        # security incident upgrades a deny to escalate
        (prof("R", Department.SECURITY, Level.IC, security=True),
         item(Sensitivity.SECRET, Scope.ORG, min_clr=4),
         intent(PurposeTag.INCIDENT, Scope.ORG), False, ESCALATE, "SEC1"),
    ],
)
def test_scenarios(requester, it, intent_, manages, expected_outcome, rule_contains):
    d = evaluate_share(requester, OWNER, it, intent_, requester_manages_owner=manages)
    assert d.outcome == expected_outcome, (d.outcome, d.rule_id, d.reason)
    assert rule_contains in d.rule_id, d.rule_id
    assert d.reason  # always explained


# ─── the load-bearing invariant ──────────────────────────────────────────────


def test_secret_is_never_shared_or_redacted_under_any_combination():
    """A SECRET item's loosest possible outcome is ESCALATE — across every axis
    and every override."""
    depts = [Department.ENGINEERING, Department.SECURITY, Department.EXEC, Department.SALES]
    levels = [Level.IC, Level.MANAGER, Level.DEPT_HEAD, Level.CEO]
    scopes = list(Scope)
    purposes = list(PurposeTag)
    for dept, lvl, scope, purpose, manages, min_clr in itertools.product(
        depts, levels, scopes, purposes, (True, False), (1, 4)
    ):
        requester = prof("R", dept, lvl, teams=["eng-team-1"], projects=["billing"], security=(dept == Department.SECURITY))
        it = item(Sensitivity.SECRET, scope, ref="billing", min_clr=min_clr)
        d = evaluate_share(requester, OWNER, it, intent(purpose, scope), requester_manages_owner=manages)
        assert d.outcome in (ESCALATE, DENY), (dept, lvl, scope, purpose, manages, d.outcome, d.rule_id)
        assert d.delivered_body is None  # nothing raw or summarized leaks


def test_redact_always_delivers_a_body_even_without_a_summary():
    no_summary = item(Sensitivity.INTERNAL, Scope.TEAM, ref="eng-team-1", summary=None)
    requester = prof("R", Department.SALES, Level.IC)  # cross-dept -> OUT -> REDACT
    d = evaluate_share(requester, OWNER, no_summary, intent(PurposeTag.TASK_CONTEXT, Scope.TEAM))
    assert d.outcome == REDACT
    assert d.delivered_body == "[redacted: The Item]"


# ─── tighten-only LLM hook ────────────────────────────────────────────────────


def test_llm_can_tighten_but_never_loosen():
    it = item(Sensitivity.CONFIDENTIAL, Scope.ORG)
    base_share = _finalize(it, SHARE, "C-exact_legit", "base")
    # tighten share -> redact: accepted
    tightened = tighten_only(base_share, REDACT, "model was cautious", it)
    assert tightened.outcome == REDACT and tightened.rule_id.endswith("+LLM")
    # try to loosen escalate -> share: rejected
    base_esc = _finalize(it, ESCALATE, "R-exact_weak", "base")
    same = tighten_only(base_esc, SHARE, "model tried to loosen", it)
    assert same.outcome == ESCALATE and same.rule_id == "R-exact_weak"
