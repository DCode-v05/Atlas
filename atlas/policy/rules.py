"""Deterministic compliance rules for the Policy Engine.

Each rule is a single-action **ABAC** floor (NIST SP 800-162) over the request's
attributes — sensitivity, scope/need-to-know, clearance, intent, department,
data-class — and cites a named control framework. The engine (`engine.py`) folds
the owner agent's LLM decision together with every firing rule by taking the
**most restrictive** outcome on the lattice ``SHARE < REDACT < ESCALATE < DENY``
(tighten-only, deny-overrides — OASIS XACML 3.0 / AWS IAM).

Frameworks referenced (rule_id ← source):
  CLEARANCE-GATE   Bell–LaPadula "no read up"; NIST 800-53 AC-3
  NEED-TO-KNOW     PCI-DSS v4.0 Req 7 (business need-to-know); NIST 800-53 AC-6
  LEAST-PRIV-DENY  PCI-DSS v4.0 Req 7 "deny all" default; AWS IAM deny-by-default
  PCI-SECRET-*     PCI-DSS v4.0 Req 3 & 7 (cardholder/secret protection)
  PII-PURPOSE      GDPR Art. 6 (lawful basis) / Art. 5(1)(b) (purpose limitation)
  PII-MINIMISE     GDPR Art. 5(1)(c); HIPAA §164.502(b) minimum-necessary
  HR-COMP          ISO/IEC 27001:2022 A.5.12; NIST 800-53 AC-6
  FINANCIAL-MNPI   SOX §404; ISO/IEC 27001:2022 A.5.12
  XDEPT-BOUNDARY   NIST 800-53 AC-6 least privilege; ISO 27001 A.5.12
  SECRET-FOUR-EYES SoD / maker-checker (ISACA; ISO 27001 A.5.3); NIST AC-5
  OFFICER-SELF-REV NIST 800-53 AC-5 (reviewer may not review itself)
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.org.ext_models import (
    SENSITIVITY_RANK,
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

#: Restrictiveness lattice — the engine takes the max over this (deny-overrides).
CONSERVATISM: dict[ShareOutcome, int] = {
    ShareOutcome.SHARE: 0,
    ShareOutcome.REDACT: 1,
    ShareOutcome.ESCALATE: 2,
    ShareOutcome.DENY: 3,
}

_CONFIDENTIAL = SENSITIVITY_RANK[Sensitivity.CONFIDENTIAL]
_RESTRICTED = SENSITIVITY_RANK[Sensitivity.RESTRICTED]
_DEPT_HEAD = int(Level.DEPT_HEAD)  # clearance 4 — dept head / exec


# ── data classification (deterministic, from the item itself) ──────────────────
def classify(item: ContextItem) -> frozenset[str]:
    """Tag an item with regulated-data classes from its tags/title — the data
    classification step of policy management (ISO 27001 A.5.12)."""
    tags = {t.lower() for t in item.topic_tags}
    title = item.title.lower()
    cls: set[str] = set()
    if "payments" in tags or "stripe" in title or "payment" in title:
        cls.add("pci")  # PCI-DSS — payment/cardholder-adjacent secret
    if "pii" in tags or "pii" in title or "personal" in title:
        cls.add("pii")  # GDPR — personal data
    if "compensation" in tags or "payroll" in tags or "compensation" in title or "comp band" in title:
        cls.add("hr-comp")  # HR-restricted compensation data
    if (tags & {"pricing", "revenue", "forecast"}) or any(
        k in title for k in ("unannounced", "pricing", "acquisition", "revenue forecast")
    ):
        cls.add("mnpi")  # SOX — material non-public financial info
    return frozenset(cls)


def in_scope(item: ContextItem, requester: OrgProfile) -> bool:
    """Need-to-know boundary check (PCI Req 7 / NIST AC-6)."""
    s = item.scope
    if s == Scope.ORG:
        return True
    if s == Scope.PROJECT:
        return bool(item.scope_ref) and item.scope_ref in requester.projects
    if s == Scope.TEAM:
        return bool(item.scope_ref) and item.scope_ref in requester.teams
    if s == Scope.ROLE:
        return bool(item.scope_ref) and requester.department.value == item.scope_ref
    if s == Scope.PRIVATE:
        return requester.agent_id == item.owner_agent_id
    return False


def is_incident_responder(requester: OrgProfile, item: ContextItem, intent: Intent) -> bool:
    """An incident-time exception: a plausible responder may reach restricted data
    they'd otherwise be denied (Google SRE / break-glass). Carve-out, not a grant."""
    if intent.purpose_tag != PurposeTag.INCIDENT:
        return False
    if requester.department in (Department.SECURITY, Department.DEVOPS):
        return True
    return bool(item.scope_ref) and item.scope_ref in requester.projects


@dataclass(frozen=True)
class Ctx:
    """Resolved attributes a rule evaluates over (computed once per review)."""

    requester: OrgProfile
    owner: OrgProfile
    item: ContextItem
    intent: Intent
    owner_outcome: ShareOutcome
    officer_id: str | None
    scoped: bool
    classes: frozenset[str]
    incident: bool

    @property
    def sens(self) -> int:
        return SENSITIVITY_RANK[self.item.sensitivity]

    @property
    def on_billing(self) -> bool:
        return "billing" in self.requester.projects


# ── the rules — each returns (floor_outcome, reason) or None (no effect) ────────
def _r_clearance_gate(c: Ctx):
    if c.requester.clearance < c.item.min_clearance:
        return ShareOutcome.DENY, (
            f"requester clearance {c.requester.clearance} is below the item's "
            f"min_clearance {c.item.min_clearance} — no read-up (Bell–LaPadula)."
        )
    return None


def _r_need_to_know(c: Ctx):
    if (not c.scoped) and (not c.incident) and _CONFIDENTIAL <= c.sens <= _RESTRICTED:
        return ShareOutcome.REDACT, (
            "requester is outside the data's need-to-know scope; "
            "confidential/restricted data is downgraded to a safe summary (PCI Req 7 / NIST AC-6)."
        )
    return None


def _r_least_priv_deny(c: Ctx):
    if (not c.scoped) and c.sens >= _RESTRICTED and not c.incident:
        return ShareOutcome.DENY, (
            "restricted/secret data has no business leaving its boundary absent an explicit need — "
            "deny-by-default (PCI Req 7 'deny all' / AWS IAM)."
        )
    return None


def _r_pci_secret(c: Ctx):
    if "pci" not in c.classes:
        return None
    if c.on_billing or c.incident:
        return ShareOutcome.ESCALATE, (
            "live payment/API secret — even a plausibly-entitled requester needs human "
            "four-eyes approval before release (PCI-DSS Req 3 & 7)."
        )
    return ShareOutcome.DENY, (
        "live payment/API secret requested with no billing or incident nexus — "
        "strict need-to-know, denied (PCI-DSS Req 7)."
    )


def _r_pii_purpose(c: Ctx):
    if "pii" in c.classes and c.intent.purpose_tag == PurposeTag.SOCIAL:
        return ShareOutcome.DENY, (
            "personal data requested for a social/non-business purpose — no lawful basis "
            "(GDPR Art. 6 / Art. 5(1)(b) purpose limitation)."
        )
    return None


def _r_pii_minimise(c: Ctx):
    if (
        "pii" in c.classes
        and not c.scoped
        and c.intent.purpose_tag
        in (PurposeTag.TASK_CONTEXT, PurposeTag.STATUS_CHECK, PurposeTag.HANDOFF, PurposeTag.PLANNING)
    ):
        return ShareOutcome.REDACT, (
            "personal data — share only the minimum necessary for the stated purpose, "
            "not the full dataset/key (GDPR Art. 5(1)(c) / HIPAA minimum-necessary)."
        )
    return None


def _r_hr_comp(c: Ctx):
    if (
        "hr-comp" in c.classes
        and c.requester.department != Department.HR
        and c.requester.clearance < _DEPT_HEAD
    ):
        return ShareOutcome.REDACT, (
            "compensation data is restricted to People Ops + senior management; a non-HR, "
            "non-executive requester gets coarse ranges only (ISO 27001 A.5.12)."
        )
    return None


def _r_financial_mnpi(c: Ctx):
    if "mnpi" in c.classes and (c.intent.purpose_tag == PurposeTag.SOCIAL or not c.scoped):
        return ShareOutcome.ESCALATE, (
            "unreleased/material non-public financial info — disclosure outside scope or for a "
            "non-business reason needs human sign-off (SOX §404 / ISO 27001 A.5.12)."
        )
    return None


def _r_xdept_boundary(c: Ctx):
    if (
        c.item.scope in (Scope.TEAM, Scope.ROLE)
        and c.requester.department != c.owner.department
        and c.sens >= _RESTRICTED
        and c.intent.purpose_tag != PurposeTag.INCIDENT
    ):
        return ShareOutcome.REDACT, (
            "restricted team/role data crossing a department boundary (outside incident response) "
            "is summarised, not handed over in full (NIST AC-6 / ISO 27001 A.5.12)."
        )
    return None


def _r_secret_four_eyes(c: Ctx):
    if c.item.sensitivity == Sensitivity.SECRET and c.owner_outcome in (ShareOutcome.SHARE, ShareOutcome.REDACT):
        return ShareOutcome.ESCALATE, (
            "a secret-tier disclosure requires an independent human approver (maker ≠ checker) — "
            "it is never auto-shared (SoD / four-eyes, ISO 27001 A.5.3 / NIST AC-5)."
        )
    return None


def _r_officer_self_review(c: Ctx):
    if (
        c.officer_id is not None
        and c.owner.agent_id == c.officer_id
        and c.sens >= _CONFIDENTIAL
        and c.owner_outcome in (ShareOutcome.SHARE, ShareOutcome.REDACT)
    ):
        return ShareOutcome.ESCALATE, (
            "the compliance authority cannot self-approve a sensitive disclosure of its own data — "
            "route to an independent human (NIST 800-53 AC-5)."
        )
    return None


#: Ordered registry — rule_id → predicate. Order is cosmetic (max() decides).
RULES: tuple[tuple[str, object], ...] = (
    ("CLEARANCE-GATE", _r_clearance_gate),
    ("NEED-TO-KNOW", _r_need_to_know),
    ("LEAST-PRIV-DENY", _r_least_priv_deny),
    ("PCI-SECRET", _r_pci_secret),
    ("PII-PURPOSE", _r_pii_purpose),
    ("PII-MINIMISE", _r_pii_minimise),
    ("HR-COMP", _r_hr_comp),
    ("FINANCIAL-MNPI", _r_financial_mnpi),
    ("XDEPT-BOUNDARY", _r_xdept_boundary),
    ("SECRET-FOUR-EYES", _r_secret_four_eyes),
    ("OFFICER-SELF-REVIEW", _r_officer_self_review),
)
