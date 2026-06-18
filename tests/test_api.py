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
    settings = Settings(seed=42, hitl_timeout_seconds=0.0)
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
    assert data["llm"] == "offline"  # the injected test provider (prod = "groq")


async def test_agent_card_endpoint(client):
    c, _ = client
    r = await c.get("/api/agents/AGT-001/card")
    assert r.status_code == 200
    assert r.json()["card"]["id"] == "AGT-001"
    assert (await c.get("/api/agents/NOPE/card")).status_code == 404


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


async def test_cron_toggle_via_api(client):
    c, rt = client
    rt.cron.burst_seconds = 0.4
    rt.cron.tick_seconds = 0.1
    r = await c.post("/api/cron", json={"on": True})
    assert r.json()["running"] is True
    await asyncio.sleep(0.9)
    assert rt.cron.running is False


async def test_snapshot_export(client):
    c, _ = client
    snap = (await c.get("/api/snapshot")).json()
    assert snap["agent_count"] == 100
    assert "metrics" in snap and "events_recent" in snap
