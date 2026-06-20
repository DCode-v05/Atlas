"""Deterministic generator for the 100-agent Atlas org.

``generate_org(seed)`` is a pure function: same seed ⇒ byte-identical company.
It builds a real hierarchy tree (every non-CEO has a resolvable ``reports_to``),
sets ``clearance = level``, wires teams and projects, gives each agent a faithful
A2A Agent Card carrying its org-profile extension, and attaches the seeded
secrets to sensible owners.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from random import Random

from atlas.a2a.extensions import COORDINATION_EXT, NEED_TO_KNOW_EXT
from atlas.a2a.models import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)
from atlas.org.agent import OrgAgent
from atlas.org.ext_models import (
    ContextItem,
    Department,
    Level,
    OrgProfile,
    User,
    profile_to_extension,
)
from atlas.org.taxonomy import (
    CEO_TITLE,
    DEPT_SPECS,
    ORG_NAME,
    OPS_LEXICON,
    SECRET_TEMPLATES,
    SKILL_CATALOG,
    FIRST_NAMES,
    LAST_NAMES,
    goal_for,
    leadership_skill,
    liaison_skill,
)


@dataclass
class OrgSnapshot:
    seed: int
    agents: dict[str, OrgAgent]
    items: dict[str, ContextItem]
    teams: dict[str, list[str]]  # team_id -> [lead, *members]
    projects: dict[str, list[str]]  # project_id -> member ids
    departments: dict[str, list[str]]  # dept value -> agent ids
    team_of: dict[str, str]  # agent_id -> team_id
    users: dict[str, User]  # user_id -> human user (1:1 with an agent)
    user_of_agent: dict[str, str]  # agent_id -> user_id
    org_lexicon: frozenset[str]
    ceo_id: str
    policy_officer_id: str = ""  # the Security head — independent compliance reviewer

    # convenience accessors -------------------------------------------------
    def head_of(self, dept: Department) -> str:
        for aid in self.departments.get(dept.value, []):
            if self.agents[aid].profile.level == Level.DEPT_HEAD:
                return aid
        raise KeyError(f"no head for {dept}")

    def manages_transitively(self, manager_id: str, agent_id: str) -> bool:
        """True if ``manager_id`` is anywhere up ``agent_id``'s reporting chain."""
        cur = self.agents.get(agent_id)
        seen: set[str] = set()
        while cur is not None and cur.profile.reports_to and cur.profile.reports_to not in seen:
            rt = cur.profile.reports_to
            if rt == manager_id:
                return True
            seen.add(rt)
            cur = self.agents.get(rt)
        return False

    def cards(self) -> dict[str, AgentCard]:
        return {aid: ag.card for aid, ag in self.agents.items()}

    def __len__(self) -> int:
        return len(self.agents)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _skills_for(dept: Department, level: Level, rng: Random) -> list[AgentSkill]:
    catalog = list(SKILL_CATALOG[dept])
    # Seniors carry fewer hands-on skills and lean on leadership/liaison skills,
    # so user *execution* prompts route to ICs while *strategy* prompts route up.
    if level == Level.CEO:
        chosen = catalog  # the two executive skills
    else:
        if level == Level.DEPT_HEAD:
            k = 2
        elif level in (Level.MANAGER, Level.LEAD):
            k = 3
        else:
            k = rng.randint(3, 5)
        k = min(len(catalog), k)
        chosen = rng.sample(catalog, k)
    skills = [
        AgentSkill(id=f"{dept.value}-{_slug(name)}", name=name, description=desc, tags=list(tags))
        for (name, desc, tags) in chosen
    ]
    if int(level) >= int(Level.DEPT_HEAD):
        name, desc, tags = liaison_skill(dept)
        skills.append(AgentSkill(id=f"{dept.value}-liaison", name=name, description=desc, tags=list(tags)))
    elif int(level) >= int(Level.LEAD):
        name, desc, tags = leadership_skill(dept)
        skills.append(AgentSkill(id=f"{dept.value}-leadership", name=name, description=desc, tags=list(tags)))
    return skills


def generate_org(seed: int) -> OrgSnapshot:
    rng = Random(seed)
    agents: dict[str, OrgAgent] = {}
    items: dict[str, ContextItem] = {}
    teams: dict[str, list[str]] = {}
    projects: dict[str, list[str]] = {}
    departments: dict[str, list[str]] = {}
    team_of: dict[str, str] = {}
    heads: dict[Department, str] = {}
    managers: dict[Department, list[str]] = {}

    idx = 0

    def make_agent(dept: Department, role_title: str, level: Level, reports_to: str | None) -> OrgAgent:
        nonlocal idx
        aid = f"AGT-{idx + 1:03d}"
        nf, nl = len(FIRST_NAMES), len(LAST_NAMES)
        # the `+ idx // nf` block offset breaks the period-N collision so all
        # 100 names are unique (no two agents share a name).
        first = FIRST_NAMES[idx % nf]
        last = LAST_NAMES[(idx * 13 + idx // nf) % nl]
        profile = OrgProfile(
            agent_id=aid,
            human_name=f"{first} {last}",
            human_email=f"{first}.{last}@atlas.dev".lower(),
            department=dept,
            role_title=role_title,
            level=level,
            clearance=int(level),
            goal=goal_for(dept, level, role_title),
            reports_to=reports_to,
            security_cleared=dept in (Department.SECURITY, Department.EXEC),
        )
        ag = OrgAgent(card=_placeholder_card(profile), profile=profile)
        agents[aid] = ag
        departments.setdefault(dept.value, []).append(aid)
        idx += 1
        return ag

    def _placeholder_card(profile: OrgProfile) -> AgentCard:
        # real skills are filled in pass 2 once relationships are wired
        return AgentCard(
            id=profile.agent_id,
            name=profile.human_name,
            description=f"{profile.role_title}, {profile.department.value.title()} @ {ORG_NAME}",
            provider=AgentProvider(organization=ORG_NAME, url="https://atlas.dev"),
        )

    # ── Pass 1: structure (deterministic, no rng) ──────────────────────────
    ceo = make_agent(Department.EXEC, CEO_TITLE, Level.CEO, None)
    ceo_id = ceo.id

    for spec in DEPT_SPECS:
        head = make_agent(spec.dept, spec.head_title, Level.DEPT_HEAD, ceo_id)
        heads[spec.dept] = head.id

        dept_managers = [
            make_agent(spec.dept, spec.manager_title, Level.MANAGER if spec.n_managers > 4 and j < 2 else Level.LEAD, head.id)
            for j in range(spec.n_managers)
        ]
        managers[spec.dept] = [m.id for m in dept_managers]

        dept_ics = [make_agent(spec.dept, spec.ic_title, Level.IC, None) for _ in range(spec.n_ics)]

        # teams + reporting wiring
        if dept_managers:
            for j, mgr in enumerate(dept_managers):
                team_id = f"{spec.dept.value}-team-{j + 1}"
                teams[team_id] = [mgr.id]
                team_of[mgr.id] = team_id
                mgr.profile.teams = [team_id]
            for k, ic in enumerate(dept_ics):
                mgr = dept_managers[k % len(dept_managers)]
                ic.profile.reports_to = mgr.id
                mgr.profile.manages.append(ic.id)
                team_id = team_of[mgr.id]
                ic.profile.teams = [team_id]
                team_of[ic.id] = team_id
                teams[team_id].append(ic.id)
            head.profile.manages = [m.id for m in dept_managers]
        else:
            # no managers (HR): ICs report directly to the head; one team led by head
            team_id = f"{spec.dept.value}-team-1"
            teams[team_id] = [head.id]
            team_of[head.id] = team_id
            for ic in dept_ics:
                ic.profile.reports_to = head.id
                head.profile.manages.append(ic.id)
                ic.profile.teams = [team_id]
                team_of[ic.id] = team_id
                teams[team_id].append(ic.id)

        head.profile.teams = [t for t in teams if t.startswith(f"{spec.dept.value}-team-")]

        # projects
        if spec.projects:
            for p in spec.projects:
                projects.setdefault(p, [])
            ic_proj_counter = 0
            for ag in [head, *dept_managers, *dept_ics]:
                if ag.profile.level == Level.IC:
                    p = spec.projects[ic_proj_counter % len(spec.projects)]
                    ic_proj_counter += 1
                    ag.profile.projects = [p]
                else:
                    ag.profile.projects = list(spec.projects)
                for p in ag.profile.projects:
                    projects[p].append(ag.id)

    ceo.profile.manages = list(heads.values())

    # ── Pass 2: skills + final cards (rng confined here, fixed order) ───────
    for ag in agents.values():
        skills = _skills_for(ag.profile.department, ag.profile.level, rng)
        ag.card = AgentCard(
            id=ag.id,
            name=ag.profile.human_name,
            description=f"{ag.profile.role_title}, {ag.profile.department.value.title()} @ {ORG_NAME}",
            provider=AgentProvider(organization=ORG_NAME, url="https://atlas.dev"),
            skills=skills,
            interfaces=[AgentInterface(transport="in-process", url=f"atlas://agent/{ag.id}")],
            capabilities=AgentCapabilities(
                streaming=True,
                extensions=[AgentExtension(uri=NEED_TO_KNOW_EXT), AgentExtension(uri=COORDINATION_EXT)],
            ),
            extensions=[profile_to_extension(ag.profile)],
        )

    # ── Pass 3: secrets (deterministic) ────────────────────────────────────
    for tmpl in SECRET_TEMPLATES:
        kind = tmpl.owner_spec[0]
        if kind == "ceo":
            owner = ceo_id
        elif kind == "head":
            owner = heads[tmpl.owner_spec[1]]
        elif kind in ("manager", "team_lead"):
            owner = managers[tmpl.owner_spec[1]][0]
        else:  # pragma: no cover - guard
            raise ValueError(f"bad owner_spec {tmpl.owner_spec}")

        scope_ref: str | None = None
        if tmpl.scope_ref_spec is not None:
            s = tmpl.scope_ref_spec
            if s[0] in ("project", "role"):
                scope_ref = s[1]
            elif s[0] == "team_of_owner":
                scope_ref = team_of.get(owner)

        item_id = f"item-{tmpl.key}"
        item = ContextItem(
            item_id=item_id,
            owner_agent_id=owner,
            title=tmpl.title,
            body=tmpl.body,
            sensitivity=tmpl.sensitivity,
            scope=tmpl.scope,
            scope_ref=scope_ref,
            min_clearance=tmpl.min_clearance,
            redacted_summary=tmpl.redacted_summary,
            topic_tags=list(tmpl.topic_tags),
        )
        items[item_id] = item
        agents[owner].owned_items[item_id] = item

    # ── Users: one human per agent, associated 1:1 (their standing assignment) ─
    users: dict[str, User] = {}
    user_of_agent: dict[str, str] = {}
    for ag in agents.values():
        uid = f"user-{ag.id}"
        users[uid] = User(
            user_id=uid,
            name=ag.profile.human_name,
            email=ag.profile.human_email,
            agent_id=ag.id,
            department=ag.profile.department,
            role_title=ag.profile.role_title,
        )
        user_of_agent[ag.id] = uid

    # ── Org lexicon (scope gate) ───────────────────────────────────────────
    lexicon: set[str] = set(OPS_LEXICON)
    lexicon.update(d.value for d in Department)
    lexicon.update(projects.keys())
    for ag in agents.values():
        lexicon.update(ag.card.skill_tags)
        lexicon.update(_slug(ag.profile.role_title).split("-"))
    lexicon.discard("")

    return OrgSnapshot(
        seed=seed,
        agents=agents,
        items=items,
        teams=teams,
        projects=projects,
        departments=departments,
        team_of=team_of,
        users=users,
        user_of_agent=user_of_agent,
        org_lexicon=frozenset(lexicon),
        ceo_id=ceo_id,
        policy_officer_id=heads.get(Department.SECURITY, ceo_id),
    )
