"""Declarative data for the Atlas software company.

This module is pure data: department structure and counts (which sum to exactly
100), the per-department skill catalogs that drive discovery, the seeded project
secrets that exercise every policy outcome, and the org lexicon the scope-gate
uses to decide whether a prompt is "about the company" at all.

The generation *logic* lives in ``generator.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from atlas.org.ext_models import Department, Scope, Sensitivity

# ─── Department structure (counts sum to 100, incl. the CEO) ───────────────────


@dataclass(frozen=True)
class DeptSpec:
    dept: Department
    head_title: str
    manager_title: str
    ic_title: str
    n_managers: int
    n_ics: int
    projects: tuple[str, ...] = ()  # projects this department participates in


# CEO is handled separately (the single Exec agent). 11 heads + 15 managers +
# 73 ICs + 1 CEO = 100.
DEPT_SPECS: tuple[DeptSpec, ...] = (
    DeptSpec(Department.ENGINEERING, "VP of Engineering", "Engineering Manager",
             "Software Engineer", n_managers=6, n_ics=33,
             projects=("atlas-core", "billing", "mobile")),
    DeptSpec(Department.PRODUCT, "Head of Product", "Product Manager",
             "Product Analyst", n_managers=1, n_ics=6,
             projects=("atlas-core", "billing", "mobile")),
    DeptSpec(Department.QA, "QA Director", "QA Lead",
             "QA Engineer", n_managers=1, n_ics=6,
             projects=("atlas-core", "billing", "mobile")),
    DeptSpec(Department.DEVOPS, "Head of DevOps/SRE", "SRE Lead",
             "Site Reliability Engineer", n_managers=1, n_ics=5),
    DeptSpec(Department.SALES, "VP of Sales", "Sales Manager",
             "Account Executive", n_managers=1, n_ics=5),
    DeptSpec(Department.DESIGN, "Head of Design", "Design Lead",
             "Product Designer", n_managers=1, n_ics=4,
             projects=("atlas-core", "mobile")),
    DeptSpec(Department.DATA, "Head of Data/ML", "Data Science Lead",
             "Data Scientist", n_managers=1, n_ics=4,
             projects=("atlas-core",)),
    DeptSpec(Department.MARKETING, "Head of Marketing", "Marketing Manager",
             "Marketing Specialist", n_managers=1, n_ics=3),
    DeptSpec(Department.SUPPORT, "Head of Support", "Support Manager",
             "Support Engineer", n_managers=1, n_ics=3),
    DeptSpec(Department.SECURITY, "Chief Security Officer", "Security Lead",
             "Security Engineer", n_managers=1, n_ics=2),
    DeptSpec(Department.HR, "Head of People", "People Ops Manager",
             "People Ops Specialist", n_managers=0, n_ics=2),
)

CEO_TITLE = "Chief Executive Officer"
ORG_NAME = "Atlas"

# ─── Skill catalogs: (name, description, tags) per department ──────────────────

SKILL_CATALOG: dict[Department, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    Department.ENGINEERING: (
        ("Backend Services", "Design and build backend APIs and services", ("python", "api", "backend", "microservices")),
        ("Frontend Engineering", "Build responsive web UIs", ("react", "typescript", "frontend", "ui")),
        ("Database & Storage", "Schema design, queries, migrations", ("database", "sql", "postgres", "storage")),
        ("Auth & Access", "Authentication, tokens, access control", ("auth", "oauth", "identity", "access-control")),
        ("Distributed Systems", "Scaling, queues, caching", ("distributed-systems", "scaling", "queue", "cache")),
        ("API Integration", "Third-party and partner integrations", ("api", "integration", "webhooks")),
        ("Code Review & Quality", "Review code and enforce standards", ("code-review", "quality", "mentoring")),
        ("Mobile Engineering", "iOS and Android applications", ("mobile", "ios", "android")),
    ),
    Department.PRODUCT: (
        ("Product Roadmap", "Own the roadmap and priorities", ("roadmap", "product", "strategy", "planning")),
        ("Requirements & Specs", "Write PRDs and detailed specs", ("requirements", "prd", "specs")),
        ("User Research", "Interviews and user feedback", ("user-research", "feedback", "discovery")),
        ("Release Planning", "Coordinate feature releases", ("release", "launch", "planning")),
        ("Product Metrics", "Define and track product KPIs", ("metrics", "analytics", "kpi")),
    ),
    Department.QA: (
        ("Test Automation", "Automated test suites", ("testing", "automation", "qa", "selenium")),
        ("Manual QA", "Exploratory and regression testing", ("qa", "manual-testing", "regression")),
        ("Bug Triage", "Triage and track defects", ("bug-triage", "defects", "quality")),
        ("Release Verification", "Sign off on releases", ("release", "verification", "qa")),
        ("Performance Testing", "Load and performance testing", ("performance", "load-testing")),
    ),
    Department.DEVOPS: (
        ("CI/CD Pipelines", "Build and deploy pipelines", ("cicd", "deployment", "pipelines")),
        ("Kubernetes & Infra", "Container orchestration and infra", ("kubernetes", "infra", "docker")),
        ("Observability", "Monitoring, logging, alerting", ("observability", "monitoring", "logging")),
        ("Incident Response", "On-call and incident handling", ("incident-response", "oncall", "reliability")),
        ("Cloud & Networking", "Cloud resources and networking", ("cloud", "aws", "networking")),
    ),
    Department.SALES: (
        ("Pipeline Management", "Manage the sales pipeline", ("pipeline", "crm", "sales")),
        ("Contract Negotiation", "Negotiate deals and contracts", ("contracts", "negotiation", "deals")),
        ("Account Management", "Manage key customer accounts", ("accounts", "customer", "relationship")),
        ("Lead Qualification", "Qualify inbound leads", ("leads", "qualification", "prospecting")),
    ),
    Department.DESIGN: (
        ("UX Design", "User experience and flows", ("ux", "design", "wireframes")),
        ("UI Design", "Visual and interface design", ("ui", "visual-design", "figma")),
        ("Design Systems", "Component libraries and tokens", ("design-system", "components")),
        ("Prototyping", "Interactive prototypes", ("prototyping", "figma")),
    ),
    Department.DATA: (
        ("Data Pipelines", "ETL and data pipelines", ("data", "etl", "pipelines")),
        ("Machine Learning", "Models and training", ("ml", "machine-learning", "models")),
        ("Analytics & BI", "Dashboards and analysis", ("analytics", "bi", "dashboards")),
        ("Experimentation", "A/B testing and experiments", ("experimentation", "ab-testing", "metrics")),
    ),
    Department.MARKETING: (
        ("Content Marketing", "Content and campaigns", ("content", "marketing", "campaigns")),
        ("Growth & SEO", "Growth, SEO and funnels", ("growth", "seo", "funnel")),
        ("Brand & Comms", "Brand and communications", ("brand", "comms", "pr")),
    ),
    Department.SUPPORT: (
        ("Customer Support", "Resolve customer tickets", ("support", "tickets", "customer")),
        ("Escalation Handling", "Handle escalations", ("escalation", "support", "incident")),
        ("Knowledge Base", "Docs and help center", ("knowledge-base", "docs", "help")),
    ),
    Department.SECURITY: (
        ("Application Security", "AppSec and vulnerability management", ("security", "appsec", "vulnerabilities")),
        ("Incident & Compliance", "Security incidents and compliance", ("security", "compliance", "incident-response")),
        ("Access & Secrets", "Secrets and access control", ("security", "secrets", "access-control")),
    ),
    Department.HR: (
        ("Recruiting & Hiring", "Hiring and recruiting", ("hiring", "recruiting", "hr")),
        ("People Operations", "Compensation, benefits, policy", ("people-ops", "compensation", "hr", "benefits")),
    ),
    Department.EXEC: (
        ("Company Strategy", "Set company strategy and vision", ("strategy", "vision", "leadership", "company")),
        ("Executive Decisions", "Cross-org decisions and approvals", ("executive", "approvals", "leadership")),
    ),
}


def leadership_skill(dept: Department) -> tuple[str, str, tuple[str, ...]]:
    return (
        "Team Leadership",
        "Lead, coordinate, and unblock a team",
        ("coordination", "leadership", "mentoring", dept.value),
    )


def liaison_skill(dept: Department) -> tuple[str, str, tuple[str, ...]]:
    return (
        f"{dept.value.title()} Leadership",
        f"Represent and coordinate the {dept.value} department",
        ("coordination", "escalation", dept.value),
    )


# ─── Seeded project / team / role secrets (exercise every policy outcome) ──────


@dataclass(frozen=True)
class SecretTemplate:
    key: str
    title: str
    body: str
    sensitivity: Sensitivity
    scope: Scope
    # owner_spec resolved by the generator:
    #   ("ceo",) | ("head", dept) | ("manager", dept) | ("team_lead", dept)
    owner_spec: tuple
    # scope_ref_spec resolved by the generator:
    #   None | ("project", name) | ("team_of_owner",) | ("role", name)
    owner_dept: Department = Department.EXEC
    scope_ref_spec: Optional[tuple] = None
    min_clearance: int = 1
    redacted_summary: Optional[str] = None
    topic_tags: tuple[str, ...] = field(default_factory=tuple)


SECRET_TEMPLATES: tuple[SecretTemplate, ...] = (
    # --- PUBLIC / INTERNAL (these should freely SHARE) ---
    SecretTemplate("roadmap-public", "Public roadmap highlights",
                   "We are publicly committed to faster onboarding and an analytics revamp.",
                   Sensitivity.PUBLIC, Scope.ORG, ("head", Department.PRODUCT),
                   owner_dept=Department.PRODUCT, min_clearance=1,
                   topic_tags=("roadmap", "product", "planning")),
    SecretTemplate("api-style-guide", "Engineering API style guide",
                   "Standard: REST, snake_case JSON, semantic versioning, 90% test coverage.",
                   Sensitivity.INTERNAL, Scope.ORG, ("head", Department.ENGINEERING),
                   owner_dept=Department.ENGINEERING, min_clearance=1,
                   topic_tags=("api", "backend", "code-review")),
    SecretTemplate("rate-limit-config", "Auth service rate-limit config",
                   "Auth endpoints limited to 100 req/min/IP, burst 20, via the gateway.",
                   Sensitivity.INTERNAL, Scope.TEAM, ("team_lead", Department.ENGINEERING),
                   owner_dept=Department.ENGINEERING, scope_ref_spec=("team_of_owner",),
                   min_clearance=1, topic_tags=("auth", "api", "rate-limit")),
    # --- CONFIDENTIAL (SHARE in-scope, else REDACT/DENY) ---
    SecretTemplate("q3-launch-date", "Q3 launch date (internal)",
                   "Atlas Core GA is locked for September 18 — not yet announced externally.",
                   Sensitivity.CONFIDENTIAL, Scope.ORG, ("head", Department.PRODUCT),
                   owner_dept=Department.PRODUCT, min_clearance=1,
                   redacted_summary="GA is planned for Q3; the exact date is internal.",
                   topic_tags=("roadmap", "launch", "release")),
    SecretTemplate("core-adr", "Atlas Core architecture decision record",
                   "Moving to event-sourcing with Kafka; migration spans two quarters.",
                   Sensitivity.CONFIDENTIAL, Scope.PROJECT, ("head", Department.ENGINEERING),
                   owner_dept=Department.ENGINEERING, scope_ref_spec=("project", "atlas-core"),
                   min_clearance=1,
                   redacted_summary="Core is undergoing an architecture change (details project-internal).",
                   topic_tags=("architecture", "distributed-systems", "atlas-core")),
    SecretTemplate("offline-mode", "Unreleased feature: offline mode",
                   "Mobile offline mode ships next release; sync via CRDTs.",
                   Sensitivity.CONFIDENTIAL, Scope.PROJECT, ("head", Department.PRODUCT),
                   owner_dept=Department.PRODUCT, scope_ref_spec=("project", "mobile"),
                   min_clearance=1,
                   redacted_summary="An unannounced mobile feature is in progress.",
                   topic_tags=("mobile", "feature", "release")),
    SecretTemplate("rev-forecast", "Q3 revenue forecast",
                   "Q3 forecast is $4.2M, 18% above plan, driven by enterprise renewals.",
                   Sensitivity.CONFIDENTIAL, Scope.ORG, ("head", Department.SALES),
                   owner_dept=Department.SALES, min_clearance=2,
                   redacted_summary="Q3 is tracking above plan (figures are finance-restricted).",
                   topic_tags=("revenue", "forecast", "sales")),
    # --- RESTRICTED (REDACT in-scope, ESCALATE near-scope, DENY otherwise) ---
    SecretTemplate("pricing-change", "Unannounced pricing change",
                   "New usage-based pricing launches with billing v2; +12% blended.",
                   Sensitivity.RESTRICTED, Scope.PROJECT, ("manager", Department.PRODUCT),
                   owner_dept=Department.PRODUCT, scope_ref_spec=("project", "billing"),
                   min_clearance=1,
                   redacted_summary="A pricing change is planned alongside billing v2.",
                   topic_tags=("pricing", "billing", "revenue")),
    SecretTemplate("db-replica-dsn", "Production DB read-replica DSN",
                   "read-replica host db-replica.prod.atlas.internal:5432 / db core (redacted DSN)",
                   Sensitivity.RESTRICTED, Scope.TEAM, ("team_lead", Department.DEVOPS),
                   owner_dept=Department.DEVOPS, scope_ref_spec=("team_of_owner",),
                   min_clearance=1,
                   redacted_summary="A production replica exists; connection details are restricted.",
                   topic_tags=("database", "infra", "production")),
    SecretTemplate("comp-band-l3", "Compensation band for L3",
                   "L3 band: $145k–$175k base, 0.05%–0.1% equity.",
                   Sensitivity.RESTRICTED, Scope.ROLE, ("head", Department.HR),
                   owner_dept=Department.HR, scope_ref_spec=("role", "hr"), min_clearance=3,
                   redacted_summary="Compensation bands are restricted to People Ops.",
                   topic_tags=("compensation", "hr", "people-ops")),
    SecretTemplate("acme-contract", "Acme Corp contract terms",
                   "Acme: 3-year, $1.8M, custom SLA 99.95%, early-termination clause.",
                   Sensitivity.RESTRICTED, Scope.TEAM, ("manager", Department.SALES),
                   owner_dept=Department.SALES, scope_ref_spec=("team_of_owner",),
                   min_clearance=1,
                   redacted_summary="A major enterprise contract exists; terms are deal-team only.",
                   topic_tags=("contracts", "deals", "accounts")),
    # --- SECRET (always ESCALATE to HITL at best, else DENY) ---
    SecretTemplate("stripe-key", "Stripe live secret key",
                   "live payment key sk_live_<redacted-demo-placeholder> (not a real Stripe key)",
                   Sensitivity.SECRET, Scope.PROJECT, ("manager", Department.ENGINEERING),
                   owner_dept=Department.ENGINEERING, scope_ref_spec=("project", "billing"),
                   min_clearance=1,
                   redacted_summary="[redacted payment credential — request via the billing lead]",
                   topic_tags=("billing", "secrets", "payments")),
    SecretTemplate("signing-cert", "Mobile app-store signing certificate",
                   "mobile distribution signing certificate + passphrase (redacted demo placeholder)",
                   Sensitivity.SECRET, Scope.PROJECT, ("manager", Department.ENGINEERING),
                   owner_dept=Department.ENGINEERING, scope_ref_spec=("project", "mobile"),
                   min_clearance=1,
                   redacted_summary="[redacted signing credential]",
                   topic_tags=("mobile", "secrets", "release")),
    SecretTemplate("break-glass", "Production break-glass credentials",
                   "Root admin recovery account + MFA seed for prod.",
                   Sensitivity.SECRET, Scope.ROLE, ("head", Department.SECURITY),
                   owner_dept=Department.SECURITY, scope_ref_spec=("role", "security"),
                   min_clearance=5,
                   redacted_summary="[redacted privileged credential]",
                   topic_tags=("security", "secrets", "access-control")),
    SecretTemplate("embargoed-cve", "Embargoed CVE in auth service",
                   "Critical auth bypass (CVE pending); patch in progress, disclosure embargoed.",
                   Sensitivity.SECRET, Scope.ORG, ("head", Department.SECURITY),
                   owner_dept=Department.SECURITY, min_clearance=2,
                   redacted_summary="A security issue is being handled under embargo.",
                   topic_tags=("security", "vulnerabilities", "incident-response")),
    SecretTemplate("pii-access-key", "User PII dataset access key",
                   "Key granting read on the production user-PII warehouse.",
                   Sensitivity.SECRET, Scope.PROJECT, ("head", Department.DATA),
                   owner_dept=Department.DATA, scope_ref_spec=("project", "atlas-core"),
                   min_clearance=2,
                   redacted_summary="[redacted data-access credential]",
                   topic_tags=("data", "pii", "secrets")),
    SecretTemplate("layoffs", "Planned reduction in force",
                   "A 6% reduction is planned for next quarter; legal review underway.",
                   Sensitivity.SECRET, Scope.ORG, ("ceo",),
                   owner_dept=Department.EXEC, min_clearance=4,
                   redacted_summary="Sensitive organisational planning is underway.",
                   topic_tags=("hr", "people-ops", "strategy")),
    SecretTemplate("acquisition", "Acquisition talks with NovaSoft",
                   "Early-stage acquisition discussions with NovaSoft at ~$40M.",
                   Sensitivity.SECRET, Scope.ORG, ("ceo",),
                   owner_dept=Department.EXEC, min_clearance=4,
                   redacted_summary="Confidential corporate development is in progress.",
                   topic_tags=("strategy", "company", "executive")),
)


# ─── Org lexicon for the scope-gate ───────────────────────────────────────────
# Tokens that mean "this prompt is about running the company". Combined at
# generation time with every skill tag, department name, and project id.

OPS_LEXICON: frozenset[str] = frozenset(
    {
        "agent", "agents", "team", "teams", "department", "dept", "project", "projects",
        "sprint", "standup", "roadmap", "release", "launch", "deploy", "deployment",
        "incident", "outage", "oncall", "ticket", "tickets", "bug", "bugs", "feature",
        "review", "code", "pr", "merge", "customer", "customers", "account", "accounts",
        "contract", "deal", "pipeline", "revenue", "forecast", "pricing", "billing",
        "hiring", "recruiting", "onboarding", "payroll", "compensation", "comp", "benefits",
        "security", "vulnerability", "compliance", "audit", "credential", "secret", "secrets",
        "database", "infra", "server", "service", "api", "endpoint", "auth", "login",
        "design", "ux", "ui", "prototype", "metrics", "analytics", "dashboard", "data",
        "model", "experiment", "campaign", "marketing", "brand", "content", "seo",
        "status", "update", "blocker", "blocked", "priority", "deadline", "milestone",
        "meeting", "sync", "handoff", "escalate", "escalation", "approve", "approval",
        "manager", "lead", "engineer", "designer", "analyst", "director", "head", "ceo",
        "company", "org", "organisation", "organization", "strategy", "okr", "goal", "goals",
        "atlas", "core", "mobile", "platform", "product", "support", "help", "qa", "test",
        "testing", "quality", "performance", "scaling", "kubernetes", "cloud", "release",
    }
)

# Human-name pools for deterministic, varied agent names.
FIRST_NAMES: tuple[str, ...] = (
    "Ada", "Liam", "Nora", "Kai", "Priya", "Diego", "Mira", "Sven", "Yara", "Owen",
    "Lena", "Tariq", "Ines", "Marco", "Zoe", "Hugo", "Aisha", "Felix", "Maya", "Ravi",
    "Elsa", "Noah", "Sana", "Theo", "Lucia", "Omar", "Greta", "Iris", "Pablo", "Nina",
    "Arjun", "Cleo", "Hana", "Bjorn", "Talia", "Emil", "Rosa", "Dmitri", "Freya", "Idris",
)
LAST_NAMES: tuple[str, ...] = (
    "Vale", "Okoro", "Lindqvist", "Sato", "Mehra", "Rossi", "Haddad", "Nilsson", "Costa", "Park",
    "Ferreira", "Khan", "Dubois", "Bauer", "Moreau", "Santos", "Ivanov", "Brandt", "Reyes", "Novak",
    "Ahmed", "Kowalski", "Bianchi", "Stern", "Marchetti", "Holt", "Vargas", "Lindgren", "Osei", "Petrov",
    "Calderon", "Berg", "Yamamoto", "Andersson", "Farouk", "Keller", "Romano", "Sokolov", "Engel", "Diallo",
)
