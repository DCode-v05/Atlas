"""API integration tests — drive the FastAPI app over ASGI (no network).

Forces the simulated provider so it's deterministic and offline.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from atlas.config import Settings
from atlas.main import create_app
from atlas.runtime import build_runtime


@pytest.fixture
async def client(offline_llm):
    # hermetic: _env_file=None so the dev's real .env (e.g. ATLAS_API_KEY) can't leak in and
    # silently switch on the edge auth gate, which would 401 every request in these tests.
    settings = Settings(seed=42, hitl_timeout_seconds=0.0, _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    app = create_app()
    app.state.runtime = rt
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, rt


async def test_org_endpoint_has_100_agents(client):
    c, _ = client
    data = (await c.get("/api/org")).json()
    assert data["node_count"] == 100
    assert len(data["reporting_edges"]) == 99  # everyone but the CEO reports to someone
    assert data["llm"] == "fake"  # the injected test double (prod = real "bedrock")


async def test_org_endpoint_exposes_per_agent_goal(client):
    c, _ = client
    nodes = (await c.get("/api/org")).json()["nodes"]
    assert all(n["goal"] for n in nodes), "every agent node carries a goal"
    assert all(n["user_id"] for n in nodes), "every agent node is linked to a user"


async def test_agent_card_endpoint(client):
    c, _ = client
    aid = (await c.get("/api/org")).json()["nodes"][0]["id"]
    assert aid.startswith("SEP-")  # opaque SEP-<16 digits> id
    r = await c.get(f"/api/agents/{aid}/card")
    assert r.status_code == 200
    body = r.json()
    assert body["card"]["id"] == aid
    assert body["goal"]  # standing responsibility surfaced on the card
    assert body["user"]["agent_id"] == aid  # associated 1:1 user
    assert (await c.get("/api/agents/NOPE/card")).status_code == 404


_ORG_PROFILE_EXT = "urn:atlas:ext:org-profile:v1"


async def test_well_known_service_card_and_catalog(client):
    c, _ = client
    # A2A discovery entry point — the Atlas service's public card.
    card = (await c.get("/.well-known/agent-card.json")).json()
    assert card["name"] == "Atlas"
    assert card["capabilities"]["extendedAgentCard"] is True
    assert card["securitySchemes"]  # carries the A2A security schemes
    assert card["protocolVersion"] == "1.0.0"
    assert card["x-atlas-agent-catalog"] == "/.well-known/agents.json"
    # the catalog enumerates every agent + its public-card URL
    cat = (await c.get("/.well-known/agents.json")).json()
    assert cat["count"] == 100
    assert cat["agents"][0]["card_url"].startswith("/.well-known/agents/")


async def test_public_card_hides_org_profile_but_extended_reveals_it(client):
    c, _ = client
    aid = (await c.get("/api/org")).json()["nodes"][0]["id"]

    # PUBLIC card (well-known, no auth) — internal org profile is withheld.
    pub = (await c.get(f"/.well-known/agents/{aid}/agent-card.json")).json()
    pub_uris = {e["uri"] for e in pub["extensions"]}
    assert _ORG_PROFILE_EXT not in pub_uris
    assert pub["capabilities"]["extendedAgentCard"] is True  # advertises the richer card
    assert (await c.get("/.well-known/agents/NOPE/agent-card.json")).status_code == 404

    # EXTENDED card (authenticated) — the full org profile is present.
    ext = (await c.get(f"/api/agents/{aid}/card/extended")).json()
    ext_uris = {e["uri"] for e in ext["extensions"]}
    assert _ORG_PROFILE_EXT in ext_uris
    prof = next(e for e in ext["extensions"] if e["uri"] == _ORG_PROFILE_EXT)
    assert prof["metadata"]["clearance"] >= 1  # real internal detail
    assert (await c.get("/api/agents/NOPE/card/extended")).status_code == 404


async def test_extended_card_is_auth_gated_while_discovery_stays_public(offline_llm):
    settings = Settings(seed=42, hitl_timeout_seconds=0.0, api_key="secret-key", _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    app = create_app()
    app.state.runtime = rt
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        aid = (await c.get("/api/org", headers={"X-API-Key": "secret-key"})).json()["nodes"][0]["id"]
        # public discovery works WITHOUT a key
        assert (await c.get("/.well-known/agent-card.json")).status_code == 200
        assert (await c.get(f"/.well-known/agents/{aid}/agent-card.json")).status_code == 200
        # the extended card REQUIRES the key (A2A: authenticated tier)
        assert (await c.get(f"/api/agents/{aid}/card/extended")).status_code == 401
        ok = await c.get(f"/api/agents/{aid}/card/extended", headers={"X-API-Key": "secret-key"})
        assert ok.status_code == 200


async def test_users_endpoint_is_1to1_with_agents(client):
    c, _ = client
    data = (await c.get("/api/users")).json()
    assert data["count"] == 100
    org_ids = {n["id"] for n in (await c.get("/api/org")).json()["nodes"]}
    assert {u["agent_id"] for u in data["users"]} == org_ids  # 1:1 bijection with the org
    assert all(u["agent_id"].startswith("SEP-") for u in data["users"])


async def test_prompt_attributed_to_user(client):
    c, _ = client
    u = (await c.get("/api/users")).json()["users"][0]
    r = await c.post(
        "/api/prompt",
        json={"prompt": "what is the engineering API style guide?", "user_id": u["user_id"]},
    )
    data = r.json()
    if not data.get("rejected"):
        assert data["submitted_by"]["user_id"] == u["user_id"]
        assert data["submitted_by"]["agent_id"] == u["agent_id"]
    assert (await c.post("/api/prompt", json={"prompt": "hi", "user_id": "nope"})).status_code == 404
async def test_projects_list_endpoint(client):
    c, _ = client
    data = (await c.get("/api/projects")).json()
    assert data["count"] == 3
    ids = {p["project_id"] for p in data["projects"]}
    assert ids == {"atlas-core", "billing", "mobile"}
    for p in data["projects"]:
        assert p["members"] > 0 and p["departments"] >= 1


async def test_project_detail_is_cross_department_and_scoped(client):
    c, _ = client
    r = await c.get("/api/projects/atlas-core")
    assert r.status_code == 200
    view = r.json()
    # cross-department by construction (Eng + Product + QA + Design + Data touch atlas-core)
    assert view["stats"]["departments"] >= 4
    assert view["stats"]["members"] == len(view["members"])
    # every surfaced secret is actually scoped to this project — and bodies are never exposed
    for s in view["secrets"]:
        assert "body" not in s
    assert (await c.get("/api/projects/nope")).status_code == 404


async def test_out_of_scope_prompt_is_gated(client):
    c, _ = client
    r = await c.post("/api/prompt", json={"prompt": "what's the weather in Paris and a pasta recipe"})
    assert r.json()["rejected"] is True


async def test_prompt_completes_with_hitl_approval_and_metrics(client):
    c, rt = client
    r = await c.post(
        "/api/prompt",
        json={"prompt": "help wire the billing stripe payment integration and get the credentials"},
    )
    data = r.json()
    assert data["rejected"] is False
    cid = data["context_id"]

    completed = False
    for _ in range(400):
        await asyncio.sleep(0.01)
        for p in (await c.get("/api/hitl")).json()["pending"]:
            await c.post(f"/api/hitl/{p['request_id']}/approve")
        tasks = (await c.get("/api/tasks")).json()["tasks"]
        if any(t["context_id"] == cid and t["state"] == "completed" for t in tasks):
            completed = True
            break
    assert completed, "task did not complete"

    totals = (await c.get("/api/metrics")).json()["totals"]
    assert totals["messages"] > 0
    assert totals["distinct_agents_contacted"] > 0


async def _open_inflight_task(c) -> str:
    """Open a task that escalates to HITL and park it there (in-flight). Returns task_id."""
    r = await c.post("/api/prompt", json={
        "prompt": "help wire the billing stripe payment integration and get the credentials"})
    data = r.json()
    assert data["rejected"] is False
    tid = data["task_id"]
    for _ in range(400):
        await asyncio.sleep(0.01)
        st = (await c.get(f"/api/tasks/{tid}")).json()["status"]["state"]
        if st in ("input-required", "working"):
            return tid
    raise AssertionError("task never went in-flight")


async def test_cancel_task_aborts_inflight_and_is_terminal(client):
    c, _ = client
    tid = await _open_inflight_task(c)

    rc = await c.post(f"/api/tasks/{tid}/cancel")
    assert rc.status_code == 200
    assert rc.json()["status"]["state"] == "canceled"

    # stays canceled (terminal — a racing scenario can't flip it to completed)…
    await asyncio.sleep(0.2)
    assert (await c.get(f"/api/tasks/{tid}")).json()["status"]["state"] == "canceled"
    # …and any pending HITL for it is cleared
    assert (await c.get("/api/hitl")).json()["pending"] == []
    # unknown task → 404; cancelling an already-terminal task is idempotent
    assert (await c.post("/api/tasks/NOPE/cancel")).status_code == 404
    assert (await c.post(f"/api/tasks/{tid}/cancel")).json()["status"]["state"] == "canceled"


async def test_subscribe_streams_a2a_frames_and_closes_on_terminal(client):
    c, _ = client
    tid = await _open_inflight_task(c)
    await c.post(f"/api/tasks/{tid}/cancel")  # make it terminal so the stream closes

    events, saw_final = [], False
    async with c.stream("GET", f"/api/tasks/{tid}/subscribe") as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if line.startswith("data:") and '"final":true' in line.replace(" ", ""):
                saw_final = True
            if saw_final:
                break
    assert "task" in events           # A2A: current Task snapshot on attach
    assert "status-update" in events  # spec-shaped TaskStatusUpdateEvent
    assert saw_final                  # terminal frame carries final=true (stream closes)

    assert (await c.get("/api/tasks/NOPE/subscribe")).status_code == 404


async def test_cron_toggle_via_api(client):
    c, rt = client
    rt.cron.tick_seconds = 0.05
    r = await c.post("/api/cron", json={"on": True})
    body = r.json()
    assert body["running"] is True
    assert body["mode"] == "burst"  # default 15s burst
    await asyncio.sleep(0.5)
    assert rt.cron.running is True  # still inside the 15s burst window
    r = await c.post("/api/cron", json={"on": False})
    assert r.json()["running"] is False
    assert rt.cron.running is False


async def test_snapshot_export(client):
    c, _ = client
    snap = (await c.get("/api/snapshot")).json()
    assert snap["agent_count"] == 100
    assert "metrics" in snap and "events_recent" in snap


async def test_push_notification_config_crud(client):
    c, _ = client
    data = (await c.post("/api/prompt", json={"prompt": "what is the engineering API style guide?"})).json()
    assert not data.get("rejected")
    task_id = data["task_id"]

    # set a webhook config for the task
    r = await c.post(
        f"/api/tasks/{task_id}/push-notification-configs",
        json={"url": "https://example.test/hook", "token": "t1"},
    )
    assert r.status_code == 200
    cfg = r.json()["pushNotificationConfig"]
    cid = cfg["id"]
    assert cfg["url"] == "https://example.test/hook" and cfg["token"] == "t1"

    # list + get
    listed = (await c.get(f"/api/tasks/{task_id}/push-notification-configs")).json()["configs"]
    assert any(x["id"] == cid for x in listed)
    assert (await c.get(f"/api/tasks/{task_id}/push-notification-configs/{cid}")).status_code == 200

    # delete → then it's gone
    assert (await c.delete(f"/api/tasks/{task_id}/push-notification-configs/{cid}")).status_code == 200
    assert (await c.get(f"/api/tasks/{task_id}/push-notification-configs/{cid}")).status_code == 404

    # a config for an unknown task is rejected, and the card advertises push
    assert (await c.post("/api/tasks/UNKNOWN/push-notification-configs", json={"url": "x"})).status_code == 404
    aid = (await c.get("/api/org")).json()["nodes"][0]["id"]
    card = (await c.get(f"/api/agents/{aid}/card")).json()["card"]
    assert card["capabilities"]["pushNotifications"] is True
