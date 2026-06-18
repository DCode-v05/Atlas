"""Golden tests for the deterministic 100-agent org generator."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from atlas.org.ext_models import Department, Level, Sensitivity, org_profile_of
from atlas.org.generator import generate_org


@pytest.fixture(scope="module")
def org():
    return generate_org(42)


def test_exactly_100_agents(org):
    assert len(org) == 100


def test_single_ceo_and_eleven_heads(org):
    levels = Counter(a.profile.level for a in org.agents.values())
    assert levels[Level.CEO] == 1
    assert levels[Level.DEPT_HEAD] == 11


def test_department_distribution(org):
    counts = Counter(a.profile.department.value for a in org.agents.values())
    assert counts == {
        "exec": 1, "engineering": 40, "product": 8, "qa": 8, "devops": 7,
        "sales": 7, "design": 6, "data": 6, "marketing": 5, "support": 5,
        "security": 4, "hr": 3,
    }
    assert sum(counts.values()) == 100


def test_valid_hierarchy_tree(org):
    """Every non-CEO has a resolvable manager; the CEO has none."""
    for a in org.agents.values():
        if a.profile.level == Level.CEO:
            assert a.profile.reports_to is None
        else:
            assert a.profile.reports_to in org.agents


def test_clearance_equals_level(org):
    for a in org.agents.values():
        assert a.profile.clearance == int(a.profile.level)


def test_every_department_has_one_head(org):
    for dept in Department:
        if dept == Department.EXEC:
            continue
        head = org.head_of(dept)
        assert org.agents[head].profile.level == Level.DEPT_HEAD


def test_secrets_attached_and_span_all_sensitivities(org):
    assert len(org.items) == 18
    by_sev = Counter(i.sensitivity for i in org.items.values())
    # at least one of every sensitivity tier so the policy engine is exercised
    for sev in Sensitivity:
        assert by_sev[sev] >= 1, sev
    for item in org.items.values():
        assert item.owner_agent_id in org.agents
        assert item.item_id in org.agents[item.owner_agent_id].owned_items


def test_all_agent_names_are_unique(org):
    names = [a.profile.human_name for a in org.agents.values()]
    assert len(set(names)) == 100, "agent names must be unique"


def test_every_agent_has_a_goal(org):
    """Each agent carries a standing responsibility ("like humans have")."""
    for a in org.agents.values():
        assert a.profile.goal, f"{a.id} has no goal"
    # the goal round-trips through the Agent Card's org-profile extension
    for a in org.agents.values():
        assert org_profile_of(a.card).goal == a.profile.goal


def test_goal_reflects_seniority(org):
    ceo = org.agents[org.ceo_id]
    assert "strategy" in ceo.profile.goal.lower()
    head = org.agents[org.head_of(Department.ENGINEERING)]
    ic = next(
        a for a in org.agents.values()
        if a.profile.department == Department.ENGINEERING and a.profile.level == Level.IC
    )
    assert head.profile.goal != ic.profile.goal


def test_one_user_per_agent_assigned_1to1(org):
    assert len(org.users) == 100
    assert len(org.user_of_agent) == 100
    # bijection: every user maps to a distinct, real agent and back
    assert {u.agent_id for u in org.users.values()} == set(org.agents.keys())
    for uid, user in org.users.items():
        assert org.user_of_agent[user.agent_id] == uid
        ag = org.agents[user.agent_id]
        assert user.name == ag.profile.human_name
        assert user.department == ag.profile.department


def test_profile_round_trips_through_card(org):
    for a in org.agents.values():
        p = org_profile_of(a.card)
        assert p.agent_id == a.id
        assert p.level == a.profile.level
        assert p.department == a.profile.department


def test_org_lexicon_is_populated(org):
    assert len(org.org_lexicon) > 100
    assert "roadmap" in org.org_lexicon
    assert "engineering" in org.org_lexicon
    assert "atlas-core" in org.org_lexicon


def test_generation_is_deterministic():
    a, b = generate_org(42), generate_org(42)

    def dump(o):
        return json.dumps(
            {aid: ag.card.model_dump(mode="json") for aid, ag in o.agents.items()},
            sort_keys=True,
        )

    assert dump(a) == dump(b)


def test_different_seed_changes_skills_not_structure():
    a, b = generate_org(42), generate_org(7)
    # structure identical (counts, hierarchy), but skill sampling differs
    assert len(a) == len(b) == 100
    a_skills = {aid: [s.id for s in ag.card.skills] for aid, ag in a.agents.items()}
    b_skills = {aid: [s.id for s in ag.card.skills] for aid, ag in b.agents.items()}
    assert a_skills != b_skills
