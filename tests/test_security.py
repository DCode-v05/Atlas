"""Edge-authentication + security-scheme tests (offline, ASGI — no network).

Auth is opt-in: with ``ATLAS_API_KEY`` unset the edge is open (today's behaviour);
set it and ``/api/*`` (except ``/api/healthz``) requires the key via the X-API-Key
header, an Authorization: Bearer token, or a ``?key=`` query param (the SSE path,
since EventSource can't set headers). The agent card declares the five A2A
security schemes regardless of whether auth is enabled.
"""

from __future__ import annotations

import httpx
import pytest

from atlas.config import Settings
from atlas.main import WEB_DIST, create_app
from atlas.runtime import build_runtime


def _client(offline_llm, api_key=None) -> httpx.AsyncClient:
    settings = Settings(seed=42, hitl_timeout_seconds=0.0, api_key=api_key, _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    app = create_app()
    app.state.runtime = rt
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_edge_is_open_by_default(offline_llm):
    async with _client(offline_llm, api_key=None) as c:
        assert (await c.get("/api/org")).status_code == 200


async def test_edge_requires_key_when_configured(offline_llm):
    async with _client(offline_llm, api_key="s3cret") as c:
        assert (await c.get("/api/org")).status_code == 401                                    # missing
        assert (await c.get("/api/org", headers={"X-API-Key": "wrong"})).status_code == 403    # bad key
        assert (await c.get("/api/org", headers={"X-API-Key": "s3cret"})).status_code == 200    # header
        assert (await c.get("/api/org", headers={"Authorization": "Bearer s3cret"})).status_code == 200  # bearer
        assert (await c.get("/api/org?key=s3cret")).status_code == 200                           # query param (SSE-style)
        assert (await c.get("/api/healthz")).status_code == 200                                  # health is exempt


async def test_card_declares_the_five_security_schemes(offline_llm):
    async with _client(offline_llm, api_key=None) as c:
        aid = (await c.get("/api/org")).json()["nodes"][0]["id"]
        card = (await c.get(f"/api/agents/{aid}/card")).json()["card"]
        assert set(card["securitySchemes"]) == {"apiKey", "bearer", "oauth2", "openIdConnect", "mutualTLS"}
        assert card["securitySchemes"]["apiKey"]["type"] == "apiKey"
        assert card["securityRequirements"] == [{"apiKey": []}]


async def test_bundled_ui_is_served_the_key_only_when_auth_on(offline_llm):
    if not WEB_DIST.exists():
        pytest.skip("frontend not built")
    async with _client(offline_llm, api_key="s3cret") as c:
        html = (await c.get("/")).text
        assert "__ATLAS_API_KEY__" in html and "s3cret" in html
    async with _client(offline_llm, api_key=None) as c:
        assert "__ATLAS_API_KEY__" not in (await c.get("/")).text
