"""The need-to-know policy engine (the graded core)."""

from atlas.policy.engine import CONSERVATISM, evaluate_share, tighten_only
from atlas.policy.rules import (
    MATRIX,
    Column,
    IntentClass,
    ScopeMatch,
    classify_intent,
    compute_scope_match,
    select_column,
)

__all__ = [
    "evaluate_share",
    "tighten_only",
    "CONSERVATISM",
    "MATRIX",
    "Column",
    "ScopeMatch",
    "IntentClass",
    "select_column",
    "compute_scope_match",
    "classify_intent",
]
