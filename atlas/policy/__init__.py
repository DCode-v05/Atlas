"""The deterministic compliance **Policy Engine**.

Codified need-to-know / least-privilege / segregation-of-duties / regulatory rules
(`rules.py`) folded by a tighten-only most-restrictive-wins engine (`engine.py`). It
reviews — and may tighten, never loosen — the owner agent's LLM share decision. Replaces
the former LLM "Policy Officer" agent with an auditable, deterministic control.
"""

from atlas.policy.engine import PolicyEngine
from atlas.policy.rules import CONSERVATISM, RULES, classify, in_scope, is_incident_responder

__all__ = [
    "PolicyEngine",
    "RULES",
    "CONSERVATISM",
    "classify",
    "in_scope",
    "is_incident_responder",
]
