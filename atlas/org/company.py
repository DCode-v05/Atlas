"""Per-organisation **company profiles** — what makes each org in a federation a genuinely
different company rather than a structural clone.

The line (see ``docs/DOCUMENTATION.md`` §14): **vary identity & content, keep capability &
structure.** Each company gets its own **projects**, its own **people** (a rotated name pool), and
its secrets reskinned to its projects. What stays canonical across every org: departments,
headcounts, role archetypes, and the **skill catalogs** — capability must match so routing scores
track and the membership-gated cross-org fallback stays well-defined.

Two hard rules (or the Policy Engine silently misclassifies items per org):

1. Substitution touches only **free text** (goals, secret titles/bodies) and **project
   identifiers** (``scope_ref`` / dept projects / the lexicon) — **never** ``topic_tags`` or
   ``sensitivity``, which the deterministic classifier keys on.
2. Peer project names contain **no** classification keyword (payments, pii, compensation,
   payroll, pricing, revenue, forecast, stripe, acquisition, …) — else a neutral item would be
   reclassified PCI/MNPI in that org.

The canonical (``atlas``) company is the identity profile, so ``generate_org(42)`` stays
byte-identical and the golden snapshot + single-org demo are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompanyProfile:
    key: str
    #: exactly THREE projects, each ``(id, display)``. Same arity as the canonical company (code
    #: + UI assume 3); only the names differ.
    projects: tuple[tuple[str, str], tuple[str, str], tuple[str, str]]
    #: rotates the shared first/last-name pools so each company has DIFFERENT people (0 = canonical).
    name_offset: int = 0


# The project ids/displays the SECRET_TEMPLATES + DEPT_SPECS are authored against.
_CANON: tuple[tuple[str, str], tuple[str, str], tuple[str, str]] = (
    ("atlas-core", "Atlas Core"),
    ("billing", "Billing"),
    ("mobile", "Mobile"),
)

CANONICAL_COMPANY = CompanyProfile("atlas", _CANON, name_offset=0)

# Distinct companies for the federation's peer orgs (index > 0). Different projects + different
# people. Every project name here is deliberately clear of the policy-classification keywords.
PEER_COMPANIES: dict[str, CompanyProfile] = {
    "globex": CompanyProfile("globex", (("orbit-core", "Orbit Core"), ("settle", "Settle"), ("fieldlink", "FieldLink")), 11),
    "initech": CompanyProfile("initech", (("tps-core", "TPS Core"), ("ledger", "Ledger"), ("dispatch", "Dispatch")), 23),
    "umbrella": CompanyProfile("umbrella", (("hive-core", "Hive Core"), ("vault", "Vault"), ("scout", "Scout")), 37),
    "hooli": CompanyProfile("hooli", (("nucleus", "Nucleus"), ("conduit", "Conduit"), ("beacon", "Beacon")), 41),
    "stark": CompanyProfile("stark", (("arc-core", "Arc Core"), ("forge", "Forge"), ("aegis", "Aegis")), 53),
    "wayne": CompanyProfile("wayne", (("gotham-core", "Gotham Core"), ("oracle-svc", "Oracle Service"), ("grapnel", "Grapnel")), 59),
    "acme": CompanyProfile("acme", (("anvil-core", "Anvil Core"), ("rocket", "Rocket"), ("portal", "Portal")), 67),
}


def company_for(org_id: str, index: int) -> CompanyProfile:
    """The company profile for an org in a federation. Index 0 (and ``atlas``) is canonical; named
    peers come from the table; anything beyond it gets a deterministic generic profile."""
    if index == 0 or org_id == "atlas":
        return CANONICAL_COMPANY
    if org_id in PEER_COMPANIES:
        return PEER_COMPANIES[org_id]
    cap = org_id.replace("-", " ").title()
    return CompanyProfile(
        org_id,
        ((f"{org_id}-core", f"{cap} Core"), (f"{org_id}-svc", f"{cap} Service"), (f"{org_id}-edge", f"{cap} Edge")),
        name_offset=(index * 29) % 97 + 1,
    )


def project_map(company: CompanyProfile) -> dict[str, str]:
    """Canonical project id → this company's project id (for scope_ref / dept projects / lexicon)."""
    return {c[0]: p[0] for c, p in zip(_CANON, company.projects)}


def text_substitutions(company: CompanyProfile) -> list[tuple[str, str]]:
    """Ordered ``(canonical → company)`` string replacements for free text (goals, secret
    titles/bodies). Longest canonical string first so ``"Atlas Core"`` is replaced before
    ``"atlas-core"``. For the canonical company every pair is an identity ⇒ a no-op."""
    reps: list[tuple[str, str]] = []
    for c, p in zip(_CANON, company.projects):
        reps.append((c[1], p[1]))  # display:  "Atlas Core" → "Orbit Core"
        reps.append((c[0], p[0]))  # id:       "atlas-core" → "orbit-core"
    reps.sort(key=lambda r: -len(r[0]))
    return reps


def apply_text(text: str, reps: list[tuple[str, str]]) -> str:
    for a, b in reps:
        text = text.replace(a, b)
    return text
