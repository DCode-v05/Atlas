"""The need-to-know decision matrix and its column-selection logic.

The correctness of this engine lives in TWO places that are easy to get wrong:
the **column selection** (which of the five columns a request lands in, given the
three axes) and the **data alignment** (e.g. ROLE scope matches *department*, not
role title). Both are isolated here as small pure functions so they can be tested
over the full Cartesian product of axes — not just one example per named cell.
"""

from __future__ import annotations

from enum import Enum

from atlas.org.ext_models import (
    LEGITIMATE_PURPOSES,
    ContextItem,
    OrgProfile,
    PurposeTag,
    Scope,
    Sensitivity,
    SENSITIVITY_RANK,
    ShareOutcome,
)


class Column(str, Enum):
    EXACT_LEGIT = "exact_legit"  # in scope, cleared, legitimate intent
    EXACT_WEAK = "exact_weak"  # in scope, cleared, weak intent
    RELATED = "related"  # adjacent scope (same dept, not same team/project)
    OUT = "out"  # out of scope OR under-cleared
    ILLEGIT = "illegit"  # illegitimate intent (overrides everything but PUBLIC)


class ScopeMatch(str, Enum):
    EXACT = "exact"
    RELATED = "related"
    NONE = "none"


class IntentClass(str, Enum):
    LEGIT = "legit"
    WEAK = "weak"
    ILLEGIT = "illegit"


SEV_CODE: dict[Sensitivity, str] = {
    Sensitivity.PUBLIC: "P",
    Sensitivity.INTERNAL: "I",
    Sensitivity.CONFIDENTIAL: "C",
    Sensitivity.RESTRICTED: "R",
    Sensitivity.SECRET: "S",
}

_RESTRICTED_RANK = SENSITIVITY_RANK[Sensitivity.RESTRICTED]


# ─── The matrix: (sensitivity, column) -> outcome ─────────────────────────────

_S, _RD, _DN, _ES = (
    ShareOutcome.SHARE,
    ShareOutcome.REDACT,
    ShareOutcome.DENY,
    ShareOutcome.ESCALATE,
)

MATRIX: dict[tuple[Sensitivity, Column], ShareOutcome] = {}


def _row(sens: Sensitivity, exact_legit, exact_weak, related, out, illegit) -> None:
    MATRIX[(sens, Column.EXACT_LEGIT)] = exact_legit
    MATRIX[(sens, Column.EXACT_WEAK)] = exact_weak
    MATRIX[(sens, Column.RELATED)] = related
    MATRIX[(sens, Column.OUT)] = out
    MATRIX[(sens, Column.ILLEGIT)] = illegit


#            sensitivity        exact&legit  exact&weak   related  out    illegit
_row(Sensitivity.PUBLIC,       _S,          _S,          _S,      _S,    _S)
_row(Sensitivity.INTERNAL,     _S,          _S,          _S,      _RD,   _DN)
_row(Sensitivity.CONFIDENTIAL, _S,          _RD,         _RD,     _DN,   _DN)
_row(Sensitivity.RESTRICTED,   _RD,         _ES,         _ES,     _DN,   _DN)
_row(Sensitivity.SECRET,       _ES,         _ES,         _DN,     _DN,   _DN)


# ─── Axis computation ─────────────────────────────────────────────────────────


def compute_scope_match(item: ContextItem, requester: OrgProfile, owner: OrgProfile) -> ScopeMatch:
    """Where the requester stands relative to the item's need-to-know boundary."""
    s = item.scope
    if s == Scope.PRIVATE:
        return ScopeMatch.EXACT if requester.agent_id == owner.agent_id else ScopeMatch.NONE
    if s == Scope.ORG:
        return ScopeMatch.EXACT
    if s == Scope.ROLE:
        # scope_ref is a department / role-group key (e.g. "hr", "security").
        return ScopeMatch.EXACT if (item.scope_ref and requester.department.value == item.scope_ref) else ScopeMatch.NONE
    if s == Scope.TEAM:
        if item.scope_ref and item.scope_ref in requester.teams:
            return ScopeMatch.EXACT
        if requester.department == owner.department:
            return ScopeMatch.RELATED
        return ScopeMatch.NONE
    if s == Scope.PROJECT:
        if item.scope_ref and item.scope_ref in requester.projects:
            return ScopeMatch.EXACT
        if requester.department == owner.department:
            return ScopeMatch.RELATED
        return ScopeMatch.NONE
    return ScopeMatch.NONE


def classify_intent(intent_purpose: PurposeTag, declared_scope: Scope, item: ContextItem) -> IntentClass:
    """Legitimacy of the stated motivation.

    Legit requires a task-grade purpose AND a declared scope that matches the
    item's scope. Scopes are not nested, so we require equality (not ⊇).
    """
    if intent_purpose == PurposeTag.SOCIAL:
        return IntentClass.ILLEGIT
    if intent_purpose == PurposeTag.STATUS_CHECK:
        return IntentClass.WEAK
    if intent_purpose in LEGITIMATE_PURPOSES:
        return IntentClass.LEGIT if declared_scope == item.scope else IntentClass.WEAK
    return IntentClass.WEAK


def select_column(scope_match: ScopeMatch, clr_ok: bool, intent_cls: IntentClass) -> Column:
    """Pinned precedence — this ordering *is* the behavior in every overlap case.

    PUBLIC is handled by the matrix row (all SHARE), so it needs no short-circuit
    here. Order: illegitimate → out/under-cleared → exact&legit → exact&weak →
    related → (safety) out.
    """
    if intent_cls == IntentClass.ILLEGIT:
        return Column.ILLEGIT
    if (not clr_ok) or scope_match == ScopeMatch.NONE:
        return Column.OUT
    if scope_match == ScopeMatch.EXACT and intent_cls == IntentClass.LEGIT:
        return Column.EXACT_LEGIT
    if scope_match == ScopeMatch.EXACT and intent_cls == IntentClass.WEAK:
        return Column.EXACT_WEAK
    if scope_match == ScopeMatch.RELATED:
        return Column.RELATED
    return Column.OUT


def is_restricted_or_below(sensitivity: Sensitivity) -> bool:
    return SENSITIVITY_RANK[sensitivity] <= _RESTRICTED_RANK
