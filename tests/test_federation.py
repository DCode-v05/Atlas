"""Multi-org federation — the cross-organisation boundary (Phase 1).

The federation invariant: inside an org, need-to-know governs as usual (detailed,
unrestricted-about-the-org sharing); BETWEEN orgs, only PUBLIC information may cross —
the two private networks talk publicly, and "only necessary things leave the building."

This pins the boundary at the deterministic Policy Engine (the auditable floor), proven
three ways: PUBLIC crosses, non-PUBLIC is denied crossing, and the same non-PUBLIC item
still flows INSIDE its own org. Plus the generator's org-tagging that distinguishes two
independently-seeded organisations.
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
from atlas.config import Settings
from atlas.org.generator import generate_org
from atlas.policy import PolicyEngine
from atlas.runtime import build_federation, build_runtime

ENGINE = PolicyEngine()
SHARE, REDACT, ESCALATE, DENY = (
    ShareOutcome.SHARE,
    ShareOutcome.REDACT,
    ShareOutcome.ESCALATE,
    ShareOutcome.DENY,
)


def _prof(aid, dept=Department.ENGINEERING, clearance=3, teams=(), projects=()):
    return OrgProfile(
        agent_id=aid, human_name=aid, human_email=f"{aid}@x", department=dept,
        role_title="role", level=Level(min(max(clearance, 1), 5)), clearance=clearance,
        teams=list(teams), projects=list(projects),
    )


def _item(sens, scope=Scope.ORG, owner="OWN", tags=()):
    return ContextItem(
        item_id="item-x", owner_agent_id=owner, title="Roadmap note", body="THE-BODY",
        sensitivity=sens, scope=scope, scope_ref=None, min_clearance=1,
        redacted_summary="a safe summary", topic_tags=list(tags),
    )


def _intent(purpose=PurposeTag.TASK_CONTEXT):
    return Intent(motivation="m", purpose_tag=purpose, requested_topic="t", declared_scope=Scope.ORG)


def _share_decision(it):
    """The owner's hypothetical SHARE — what the engine then reviews/tightens."""
    return ShareDecision(
        outcome=SHARE, reason="owner judged", item_id=it.item_id, rule_id="LLM-OWNER",
        sensitivity=it.sensitivity, delivered_title=it.title, delivered_body=it.body,
    )


# ── the three-way boundary proof ────────────────────────────────────────────────
def test_public_crosses_the_org_boundary():
    """A PUBLIC item owned by org B may be shared to a requester in org A."""
    requester = _prof("SEP-A-requester")  # org A
    owner = _prof("SEP-B-owner")          # org B
    it = _item(Sensitivity.PUBLIC)
    decision = _share_decision(it)

    reviewed = ENGINE.review(decision, requester, owner, it, _intent(), cross_org=True)

    assert reviewed.outcome == SHARE
    assert "CROSS-ORG" not in (reviewed.rule_id or "")
    assert reviewed.delivered_body == "THE-BODY"


def test_internal_is_denied_at_the_org_boundary():
    """Anything above PUBLIC is categorically withheld across orgs — hard DENY."""
    requester = _prof("SEP-A-requester")
    owner = _prof("SEP-B-owner")
    for sens in (Sensitivity.INTERNAL, Sensitivity.CONFIDENTIAL, Sensitivity.RESTRICTED, Sensitivity.SECRET):
        it = _item(sens)
        decision = _share_decision(it)

        reviewed = ENGINE.review(decision, requester, owner, it, _intent(), cross_org=True)

        assert reviewed.outcome == DENY, f"{sens} should not cross the org boundary"
        assert reviewed.rule_id == "POLICY/CROSS-ORG-RESTRICT"
        assert reviewed.delivered_body is None


def test_same_internal_item_still_flows_inside_its_org():
    """The boundary is BETWEEN orgs only — intra-org, the org-scoped internal item
    is shared as normal need-to-know allows (the cross-org rule does not fire)."""
    requester = _prof("SEP-A-requester")
    owner = _prof("SEP-A-owner")
    it = _item(Sensitivity.INTERNAL, scope=Scope.ORG)  # whole-org need-to-know
    decision = _share_decision(it)

    reviewed = ENGINE.review(decision, requester, owner, it, _intent(), cross_org=False)

    assert reviewed.outcome == SHARE
    assert reviewed.rule_id != "POLICY/CROSS-ORG-RESTRICT"
    assert reviewed.delivered_body == "THE-BODY"


def test_explain_lists_cross_org_rule_only_when_crossing():
    """The audit trail names CROSS-ORG-RESTRICT exactly when the request crosses orgs."""
    requester = _prof("SEP-A-requester")
    owner = _prof("SEP-B-owner")
    it = _item(Sensitivity.CONFIDENTIAL)
    decision = _share_decision(it)

    crossing = ENGINE.explain(decision, requester, owner, it, _intent(), cross_org=True)
    intra = ENGINE.explain(decision, requester, owner, it, _intent(), cross_org=False)

    assert any(r[0] == "POLICY/CROSS-ORG-RESTRICT" for r in crossing)
    assert not any(r[0] == "POLICY/CROSS-ORG-RESTRICT" for r in intra)


# ── the generator tags each org and gives it distinct membership ─────────────────
def test_independent_orgs_are_distinctly_tagged_and_disjoint():
    """Two independently-seeded orgs carry their own id/name and disjoint agent ids,
    so a federation can tell members of one org from another."""
    atlas = generate_org(42, org_id="atlas", org_name="Atlas")
    globex = generate_org(43, org_id="globex", org_name="Globex")

    assert (atlas.org_id, atlas.org_name) == ("atlas", "Atlas")
    assert (globex.org_id, globex.org_name) == ("globex", "Globex")
    assert len(atlas.agents) == len(globex.agents) == 100

    atlas_ids = set(atlas.agents)
    globex_ids = set(globex.agents)
    assert atlas_ids.isdisjoint(globex_ids), "distinct seeds must yield disjoint agent ids"


def test_org_generation_is_deterministic_per_id():
    """Same (seed, org_id) ⇒ identical membership — federation stays reproducible."""
    a1 = generate_org(42, org_id="atlas", org_name="Atlas")
    a2 = generate_org(42, org_id="atlas", org_name="Atlas")
    assert list(a1.agents) == list(a2.agents)


# ── the gateway path: the federation boundary enforced end-to-end ────────────────
import pytest  # noqa: E402


@pytest.fixture
def fed(offline_llm):
    """A two-org federation (Atlas + Globex) wired through the real gateway, with the
    deterministic FakeLLM as every owner's judgement."""
    settings = Settings(seed=42, org_count=2, _env_file=None)
    return build_federation(settings, step_delay=0.0, llm=offline_llm)


def _foreign_pair(fed):
    """A requester in Atlas and an owner id in Globex — i.e. a genuine cross-org pair."""
    atlas = fed.orgs["atlas"]
    globex = fed.orgs["globex"]
    requester = next(iter(atlas.snapshot.agents.values()))
    owner_id = next(iter(globex.snapshot.agents))
    return requester, owner_id


async def test_gateway_denies_internal_across_orgs(fed):
    """Operator-directed crossing: an INTERNAL item is denied end-to-end at the boundary —
    through the TARGET org's own decision machinery (pre-gate → CROSS-ORG-RESTRICT)."""
    requester, owner_id = _foreign_pair(fed)
    it = _item(Sensitivity.INTERNAL, owner=owner_id)

    decision = await fed.gateway.request_across(
        requester=requester, target_org_id="globex", item=it, intent=_intent()
    )

    assert decision.outcome == DENY
    assert decision.rule_id == "POLICY/CROSS-ORG-RESTRICT"
    assert decision.delivered_body is None


async def test_gateway_shares_public_across_orgs(fed):
    """A PUBLIC item DOES cross — decided by Globex's owner agent + Globex's policy."""
    requester, owner_id = _foreign_pair(fed)
    it = _item(Sensitivity.PUBLIC, owner=owner_id)

    decision = await fed.gateway.request_across(
        requester=requester, target_org_id="globex", item=it, intent=_intent()
    )

    assert decision.outcome == SHARE
    assert decision.delivered_body == "THE-BODY"


async def test_auto_fallback_returns_public_only(fed):
    """Auto-fallback crossing: a foreign org asks a peer for a mix of items; only the PUBLIC
    one comes back — "only the necessary things leave the building"."""
    requester, owner_id = _foreign_pair(fed)
    items = [
        _item(Sensitivity.PUBLIC, owner=owner_id),
        _item(Sensitivity.INTERNAL, owner=owner_id),
        _item(Sensitivity.CONFIDENTIAL, owner=owner_id),
        _item(Sensitivity.SECRET, owner=owner_id),
    ]

    crossed = await fed.gateway.source_public_context(
        requester=requester, target_org_id="globex", items=items, intent=_intent()
    )

    assert len(crossed) == 1
    (item, decision), = crossed
    assert item.sensitivity == Sensitivity.PUBLIC
    assert decision.outcome == SHARE


def test_orgs_are_sealed_to_their_own_registry(fed):
    """Each org's Router knows ONLY its own agents — the structural guarantee that an org
    cannot reach a peer except through the gateway."""
    atlas = fed.orgs["atlas"]
    globex = fed.orgs["globex"]
    globex_id = next(iter(globex.snapshot.agents))

    assert atlas.router.registry is atlas.registry
    assert globex.router.registry is globex.registry
    assert globex_id not in atlas.registry.agents  # Atlas's bus can't see a Globex agent


def test_public_directory_strips_org_profile(fed):
    """Cross-org discovery sees a peer's PUBLIC cards only — never its internal hierarchy."""
    directory = fed.gateway.public_directory("globex")

    assert len(directory) == 100
    for card in directory:
        ext_uris = [e.get("uri") for e in card.get("capabilities", {}).get("extensions", [])]
        assert "urn:atlas:ext:org-profile:v1" not in ext_uris


# ── the API edge: operator-directed cross-org exchange, end-to-end over HTTP ─────
import asyncio  # noqa: E402

import httpx  # noqa: E402

from atlas.main import create_app, lifespan  # noqa: E402
from atlas.org.ext_models import Department  # noqa: E402


async def _resolve_first_hitl(hitl, *, approve: bool):
    """Wait for the cross-org gate to park a request, then resolve it as the operator would."""
    for _ in range(800):
        pending = hitl.list_pending()
        if pending:
            from atlas.org.ext_models import ShareOutcome as _SO
            hitl.resolve(pending[0].request_id, approved=approve,
                         outcome=_SO.SHARE if approve else _SO.DENY)
            return pending[0]
        await asyncio.sleep(0.01)
    return None


async def _await_terminal(task):
    for _ in range(800):
        if task.status.state.value in ("completed", "failed"):
            break
        await asyncio.sleep(0.01)
    return task.status.state.value


async def _fallback_fed(tmp_path, offline_llm, db_name):
    """A 2-org federation (DB on) where Atlas's Product team has NOT joined but Globex's has —
    so a product prompt to Atlas falls back across the boundary to Globex."""
    settings = Settings(seed=42, org_count=2, database_url=f"sqlite+aiosqlite:///{tmp_path}/{db_name}",
                        hitl_timeout_seconds=0.0, _env_file=None)
    fed = build_federation(settings, step_delay=0.0, llm=offline_llm)
    return fed


async def test_auto_fallback_hitl_gate_approve(tmp_path, offline_llm):
    """The cross-org AUTO-FALLBACK runs through the REAL pipeline: messages thread + persist, and
    each would-cross share PARKS for operator approval (HITL). On approve, the PUBLIC item crosses;
    a relevant confidential item is hard-denied by policy with no human."""
    fed = await _fallback_fed(tmp_path, offline_llm, "ap.db")
    app = create_app(federation=fed)
    async with lifespan(app):
        atlas, globex = fed.orgs["atlas"], fed.orgs["globex"]
        await atlas.network.authenticate_oneclick(atlas.snapshot.head_of(Department.SALES))
        for aid in globex.snapshot.departments[Department.PRODUCT.value]:
            await globex.network.authenticate_oneclick(aid)

        res = await atlas.orchestrator.run_user_prompt("plan the product roadmap", "Tester")
        assert res.get("cross_org") is True and res["routed_to_org"] == "globex"
        cid = res["context_id"]

        # the would-cross share PARKED for the operator → approve it (HITL integration)
        req = await _resolve_first_hitl(fed.shared.hitl, approve=True)
        assert req is not None
        assert await _await_terminal(atlas.router.tasks[res["task_id"]]) == "completed"

        # boundary worked both ways: PUBLIC crossed (after approval), confidential withheld
        evts = [e for e in fed.shared.broker.history if e.event == "federation.exchange" and e.context_id == cid]
        assert any(e.data["crossed"] and e.data["sensitivity"] == "public" for e in evts)
        assert any(not e.data["crossed"] for e in evts)
        # a thread was created (Conversation) and the messages PERSISTED (History) via the Router
        assert any(e.event == "thread.created" and e.context_id == cid for e in fed.shared.broker.history)
        from sqlalchemy import select

        from atlas.db.models import MessageRow
        for _ in range(200):
            async with fed.shared.db.session() as s:
                rows = (await s.execute(select(MessageRow).where(MessageRow.context_id == cid))).scalars().all()
            if rows:
                break
            await asyncio.sleep(0.01)
        assert rows, "cross-org messages must persist to History via the Router write-through"


async def test_auto_fallback_hitl_gate_deny(tmp_path, offline_llm):
    """The operator gate is real: if the operator DENIES the cross-org share, the PUBLIC item is
    withheld — nothing leaves the building without sign-off."""
    fed = await _fallback_fed(tmp_path, offline_llm, "dn.db")
    app = create_app(federation=fed)
    async with lifespan(app):
        atlas, globex = fed.orgs["atlas"], fed.orgs["globex"]
        await atlas.network.authenticate_oneclick(atlas.snapshot.head_of(Department.SALES))
        for aid in globex.snapshot.departments[Department.PRODUCT.value]:
            await globex.network.authenticate_oneclick(aid)

        res = await atlas.orchestrator.run_user_prompt("plan the product roadmap", "Tester")
        cid = res["context_id"]
        assert await _resolve_first_hitl(fed.shared.hitl, approve=False) is not None
        assert await _await_terminal(atlas.router.tasks[res["task_id"]]) == "completed"

        evts = [e for e in fed.shared.broker.history if e.event == "federation.exchange" and e.context_id == cid]
        # the public item did NOT cross — the operator withheld it
        assert evts and all(not e.data["crossed"] for e in evts)


async def test_auto_fallback_falls_through_to_rejection_when_no_peer_fits(tmp_path, offline_llm):
    """The fallback never invents a peer: if NO peer org has joined members that fit either, it
    falls through to the original 'no agent in the network can handle this' rejection."""
    settings = Settings(seed=42, org_count=2, database_url=f"sqlite+aiosqlite:///{tmp_path}/nf.db",
                        hitl_timeout_seconds=0.0, _env_file=None)
    fed = build_federation(settings, step_delay=0.0, llm=offline_llm)
    app = create_app(federation=fed)
    async with lifespan(app):
        atlas, globex = fed.orgs["atlas"], fed.orgs["globex"]
        # only Sales joins in BOTH orgs → an engineering prompt fits no one, locally OR in the peer
        await atlas.network.authenticate_oneclick(atlas.snapshot.head_of(Department.SALES))
        await globex.network.authenticate_oneclick(globex.snapshot.head_of(Department.SALES))

        res = await atlas.orchestrator.run_user_prompt(
            "plan the q3 engineering roadmap and strategy", "Tester")

        assert res.get("rejected") is True
        assert res.get("cross_org") is None


async def test_lifespan_boots_a_two_org_federation(offline_llm):
    """The REAL app lifespan starts a heartbeat for EVERY sealed org and shares one push
    service — the per-org/shared split that ``main.py`` does on boot."""
    settings = Settings(seed=42, org_count=2, hitl_timeout_seconds=0.0, _env_file=None)
    fed = build_federation(settings, step_delay=0.0, llm=offline_llm)
    app = create_app(federation=fed)
    async with lifespan(app):
        assert app.state.federation is fed
        assert app.state.runtime.snapshot.org_id == "atlas"  # primary flattened to app.state.runtime
        for org in fed.orgs.values():
            assert org.registry._hb_task is not None  # every org is alive
    for org in fed.orgs.values():
        assert org.registry._hb_task is None  # shutdown stopped every org's heartbeat


@pytest.fixture
async def api(offline_llm):
    settings = Settings(seed=42, org_count=2, hitl_timeout_seconds=0.05, _env_file=None)
    fed = build_federation(settings, step_delay=0.0, llm=offline_llm)
    app = create_app()
    app.state.federation = fed
    app.state.runtime = fed.runtime_for(fed.primary.org_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, fed


async def test_api_lists_the_federation(api):
    c, _fed = api
    body = (await c.get("/api/orgs")).json()
    assert body["count"] == 2
    by_id = {o["org_id"]: o for o in body["orgs"]}
    assert set(by_id) == {"atlas", "globex"}
    assert by_id["atlas"]["primary"] is True and by_id["globex"]["primary"] is False
    assert by_id["globex"]["agents"] == 100


async def test_api_cross_org_confidential_is_denied(api):
    """Operator-directed: Atlas asks Globex for a NON-PUBLIC item → denied at the boundary,
    and the federation.exchange event names both orgs."""
    c, fed = api
    items = (await c.get("/api/federation/items", params={"org_id": "globex"})).json()["items"]
    secret = next(it for it in items if it["sensitivity"] != "public")

    res = (await c.post("/api/federation/exchange", json={
        "source_org_id": "atlas", "target_org_id": "globex", "item_id": secret["item_id"],
    })).json()

    assert res["outcome"] == "deny"
    assert res["crossed"] is False
    assert res["rule_id"] == "POLICY/CROSS-ORG-RESTRICT"
    assert res["delivered_body"] is None
    # the exchange surfaced as an event carrying BOTH org ids
    evts = [e for e in fed.shared.broker.history if e.event == "federation.exchange"]
    assert evts and evts[-1].org_id == "globex"
    assert evts[-1].data["source_org_id"] == "atlas" and evts[-1].data["target_org_id"] == "globex"
    assert evts[-1].data["crossed"] is False


async def test_api_cross_org_public_is_shared(api):
    """A PUBLIC item DOES cross — "only the necessary things leave the building"."""
    c, fed = api
    items = (await c.get("/api/federation/items", params={"org_id": "globex"})).json()["items"]
    public = next(it for it in items if it["sensitivity"] == "public")

    res = (await c.post("/api/federation/exchange", json={
        "source_org_id": "atlas", "target_org_id": "globex", "item_id": public["item_id"],
    })).json()

    assert res["outcome"] == "share"
    assert res["crossed"] is True
    assert res["delivered_body"]  # the public body actually crossed
    evts = [e for e in fed.shared.broker.history if e.event == "federation.exchange"]
    assert evts[-1].data["crossed"] is True


async def test_api_org_scoping_by_query_param(api):
    """`?org_id=` scopes a request to a specific sealed org — the org switcher + the top chat-bar
    rely on this (read the chosen org's structure; dispatch to its orchestrator)."""
    c, fed = api
    # read: the selected org's own structure
    assert (await c.get("/api/org?org_id=globex")).json()["org_name"] == "Globex"
    assert (await c.get("/api/org?org_id=atlas")).json()["org_name"] == "Atlas"

    # dispatch: the chat-bar prompt opens the Task in the SELECTED org, not the primary
    res = (await c.post("/api/prompt?org_id=globex", json={"prompt": "plan the product roadmap"})).json()
    tid = res["task_id"]
    assert tid in fed.orgs["globex"].router.tasks
    assert tid not in fed.orgs["atlas"].router.tasks


async def test_api_operator_directed_runs_full_pipeline(api):
    """`/api/federation/request` opens a real Task and runs the cross-org scenario through the live
    pipeline (threads + HITL gate + finalize), unlike the synchronous `/exchange` probe."""
    c, fed = api
    res = (await c.post("/api/federation/request", json={
        "source_org_id": "atlas", "target_org_id": "globex", "prompt": "plan the product roadmap",
    })).json()
    assert res["cross_org"] is True and res["task_id"]

    tasks = fed.orgs["atlas"].router.tasks
    for _ in range(800):
        t = tasks.get(res["task_id"])
        if t and t.status.state.value in ("completed", "failed"):
            break
        await asyncio.sleep(0.01)
    t = tasks.get(res["task_id"])
    assert t is not None and t.status.state.value == "completed"
    # the cross-org exchange happened through the pipeline (gate auto-resolved by the short timeout)
    assert any(e.event == "federation.exchange" and e.context_id == res["context_id"]
               for e in fed.shared.broker.history)


async def test_api_network_membership_is_per_org(tmp_path, offline_llm):
    """Membership is per-org: joining an agent in Atlas does NOT make it (or the count) show up
    under Globex. `/api/network?org_id=` scopes to the chosen org — what the UI switcher relies on
    so a peer org's online-state never lingers when you switch."""
    settings = Settings(seed=42, org_count=2, database_url=f"sqlite+aiosqlite:///{tmp_path}/net.db",
                        hitl_timeout_seconds=0.0, _env_file=None)
    fed = build_federation(settings, step_delay=0.0, llm=offline_llm)
    app = create_app(federation=fed)
    async with lifespan(app):
        await fed.orgs["atlas"].network.authenticate_oneclick(fed.orgs["atlas"].snapshot.ceo_id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            atlas_net = (await c.get("/api/network?org_id=atlas")).json()
            globex_net = (await c.get("/api/network?org_id=globex")).json()
    assert atlas_net["count"] == 1
    assert globex_net["count"] == 0  # Globex membership is separate — no leakage from Atlas


async def test_db_federation_seeds_every_org_with_distinct_keys(tmp_path, offline_llm):
    """DB + federation: the REAL lifespan seeds EVERY org into the shared DB (per-org
    idempotency; the template-derived ``context_items.item_id`` is namespaced by org so the
    orgs coexist) and gives each its OWN signing key — so the orgs stay sealed: a token issued
    by one org never verifies in another."""
    settings = Settings(seed=42, org_count=2, database_url=f"sqlite+aiosqlite:///{tmp_path}/fed.db",
                        hitl_timeout_seconds=0.0, _env_file=None)
    fed = build_federation(settings, step_delay=0.0, llm=offline_llm)
    app = create_app(federation=fed)
    async with lifespan(app):
        atlas_net = fed.orgs["atlas"].network
        globex_net = fed.orgs["globex"].network
        # each org got its OWN signing key (not a shared singleton row)
        assert atlas_net._pub_pem and globex_net._pub_pem
        assert atlas_net._pub_pem != globex_net._pub_pem

        # BOTH orgs' credentials were seeded → an agent in each can authenticate
        a_join = await atlas_net.authenticate_oneclick(fed.orgs["atlas"].snapshot.ceo_id)
        g_join = await globex_net.authenticate_oneclick(fed.orgs["globex"].snapshot.ceo_id)
        assert a_join and g_join

        # sealed: a token minted by Atlas is valid in Atlas but NOT in Globex
        assert atlas_net.verify_token(a_join["token"]) is not None
        assert globex_net.verify_token(a_join["token"]) is None


def test_orgs_are_genuinely_different_companies(offline_llm):
    """Each federation org is a different COMPANY — disjoint projects + disjoint people, secrets
    reskinned to its own projects — while topic_tags + sensitivity stay canonical so the Policy
    Engine classifies/tiers every org's items identically (the cross-org behaviour is preserved)."""
    settings = Settings(seed=42, org_count=2, _env_file=None)
    fed = build_federation(settings, llm=offline_llm)
    atlas, globex = fed.orgs["atlas"].snapshot, fed.orgs["globex"].snapshot

    # different projects
    assert set(atlas.projects).isdisjoint(globex.projects)
    assert "atlas-core" in atlas.projects and "atlas-core" not in globex.projects

    # different PEOPLE — names are disjoint, not just the SEP ids
    a_names = {ag.name for ag in atlas.agents.values()}
    g_names = {ag.name for ag in globex.agents.values()}
    assert a_names.isdisjoint(g_names)
    assert all(ag.profile.human_email.endswith("@globex.dev") for ag in globex.agents.values())

    # secrets reskinned to the org's own projects, BUT tags + sensitivity stay canonical
    a_item, g_item = atlas.items["item-core-adr"], globex.items["item-core-adr"]
    assert a_item.title != g_item.title
    assert "Atlas Core" in a_item.title and "Atlas Core" not in g_item.title
    assert a_item.topic_tags == g_item.topic_tags  # policy classification is unperturbed
    assert a_item.sensitivity == g_item.sensitivity


def test_single_org_federation_matches_build_runtime(offline_llm):
    """A one-org federation's sole org is identical to the single-org demo — N=1 is the
    same company, so nothing about the existing demo changes."""
    settings = Settings(seed=42, org_count=1, _env_file=None)
    fed_one = build_federation(settings, llm=offline_llm)
    rt = build_runtime(settings, llm=offline_llm)

    assert list(fed_one.orgs) == ["atlas"]
    assert list(fed_one.orgs["atlas"].snapshot.agents) == list(rt.snapshot.agents)
