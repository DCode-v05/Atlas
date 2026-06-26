"""A2A v1.0.0 edge features: card fields + extension relocation, DataPart/FilePart/referenceTaskIds,
GetTask/ListTasks, the /v1 HTTP+JSON binding (version + extension negotiation, named errors), and the
rejected / auth-required task states."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from atlas.config import Settings
from atlas.main import create_app, lifespan
from atlas.runtime import build_runtime

NEED_TO_KNOW = "urn:atlas:ext:need-to-know:v1"
ORG_PROFILE = "urn:atlas:ext:org-profile:v1"


@pytest.fixture
async def client(offline_llm):
    settings = Settings(seed=42, hitl_timeout_seconds=0.05, _env_file=None)  # in-memory; HITL auto-resolves
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    app = create_app()
    app.state.runtime = rt
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, rt


async def _run_to_terminal(c, rt, prompt: str) -> str:
    res = (await c.post("/api/prompt", json={"prompt": prompt})).json()
    tid = res["task_id"]
    for _ in range(300):
        t = rt.tasks.get(tid)
        if t and t.status.state.value in ("completed", "failed"):
            break
        await asyncio.sleep(0.01)
    return tid


# ── card fields + extension shape / relocation ────────────────────────────────
async def test_card_new_fields_and_extensions_under_capabilities(client):
    c, _ = client
    aid = (await c.get("/api/org")).json()["nodes"][0]["id"]
    card = (await c.get(f"/.well-known/agents/{aid}/agent-card.json")).json()
    assert card["iconUrl"] and card["documentationUrl"]
    assert card["defaultInputModes"] == ["text/plain"] and card["defaultOutputModes"] == ["text/plain"]
    assert "extensions" not in card  # no non-spec top-level array
    exts = card["capabilities"]["extensions"]
    ndk = next(e for e in exts if e["uri"] == NEED_TO_KNOW)
    assert ndk["required"] is True and ndk["description"]  # spec `description`/`required` populated
    assert ORG_PROFILE not in {e["uri"] for e in exts}  # withheld from the public card


# ── DataPart + FilePart + referenceTaskIds ────────────────────────────────────
async def test_finalized_artifact_carries_data_and_file_parts(client):
    c, rt = client
    tid = await _run_to_terminal(c, rt, "review the billing service architecture and code quality")
    t = rt.tasks[tid]
    assert t.artifacts, "a finalized task has an artifact"
    kinds = {p.kind for p in t.artifacts[0].parts}
    assert {"text", "data", "file"} <= kinds  # summary + structured DataPart + FilePart
    fp = next(p for p in t.artifacts[0].parts if p.kind == "file")
    assert fp.file.get("uri")  # the URL-only FilePart variant


async def test_reference_task_ids_threaded_onto_the_task(client):
    c, rt = client
    res = (await c.post(
        "/api/prompt", json={"prompt": "plan the q3 engineering roadmap", "reference_task_ids": ["task-prior-1"]}
    )).json()
    assert rt.tasks[res["task_id"]].history[0].referenceTaskIds == ["task-prior-1"]


# ── GetTask historyLength + ListTasks filters / pagination ────────────────────
async def test_list_tasks_filters_and_pagination(client):
    c, rt = client
    cids = []
    for i in range(3):
        cids.append((await c.post("/api/prompt", json={"prompt": f"plan the q{i} engineering roadmap"})).json()["context_id"])
    await asyncio.sleep(0.05)
    page = (await c.get("/api/tasks?limit=2")).json()
    assert page["total"] >= 3 and len(page["tasks"]) == 2 and page["nextCursor"] == 2
    assert [t["timestamp"] for t in page["tasks"]] == sorted((t["timestamp"] for t in page["tasks"]), reverse=True)
    one = (await c.get(f"/api/tasks?contextId={cids[0]}")).json()
    assert one["tasks"] and all(t["context_id"] == cids[0] for t in one["tasks"])


async def test_get_task_history_length(client):
    c, rt = client
    tid = await _run_to_terminal(c, rt, "review the billing service architecture and code quality")
    full = (await c.get(f"/api/tasks/{tid}")).json()
    trunc = (await c.get(f"/api/tasks/{tid}?historyLength=0")).json()
    assert trunc["history"] == [] and len(trunc["history"]) <= len(full["history"])


# ── /v1 HTTP+JSON binding: negotiation + named errors ─────────────────────────
async def test_v1_card_and_message_send_extension_negotiation(client):
    c, _ = client
    card = (await c.get("/v1/card")).json()
    assert card["name"] == "Atlas" and ORG_PROFILE not in {e["uri"] for e in card["capabilities"]["extensions"]}
    # required-extension enforcement: send without declaring need-to-know support → error
    r = await c.post("/v1/message:send", json={"message": {"parts": [{"kind": "text", "text": "plan the q3 roadmap"}]}})
    assert r.status_code == 400 and r.json()["error"]["type"] == "ExtensionSupportRequiredError"
    # declare it → a Task back, with the activated extension echoed in the response header
    r2 = await c.post("/v1/message:send", headers={"A2A-Extensions": NEED_TO_KNOW},
                      json={"message": {"parts": [{"kind": "text", "text": "plan the q3 roadmap"}]}})
    assert r2.status_code == 200 and r2.json()["id"].startswith("task-")
    assert NEED_TO_KNOW in r2.headers.get("A2A-Extensions", "")


async def test_v1_named_errors_and_version_negotiation(client):
    c, _ = client
    r = await c.get("/v1/tasks/NOPE")
    body = r.json()["error"]
    assert r.status_code == 404 and body["type"] == "TaskNotFoundError" and body["code"] == -32001
    r2 = await c.get("/v1/card", headers={"A2A-Version": "0.2.0"})
    assert r2.status_code == 400 and r2.json()["error"]["type"] == "VersionNotSupportedError"


async def test_v1_message_send_rejected_returns_rejected_task(client):
    c, _ = client
    r = await c.post("/v1/message:send", headers={"A2A-Extensions": NEED_TO_KNOW},
                     json={"message": {"parts": [{"kind": "text", "text": "what is the best pizza in town"}]}})
    assert r.status_code == 200 and r.json()["status"]["state"] == "rejected"  # server-side rejection as a Task


# ── auth-required: park-and-resume on network join (needs the DB + network) ────
async def test_auth_required_parks_and_resumes_on_join(tmp_path, offline_llm):
    settings = Settings(seed=42, database_url=f"sqlite+aiosqlite:///{tmp_path}/auth.db",
                        hitl_timeout_seconds=0.0, _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    app = create_app(runtime=rt)
    async with lifespan(app):
        member, actor = list(rt.snapshot.agents)[:2]
        await rt.network.authenticate_oneclick(member)  # network non-empty
        # prompt AS `actor`, who has NOT joined → the caller must authenticate first
        res = await rt.orchestrator.run_user_prompt(
            "plan the q3 engineering roadmap and strategy", "Tester", acting_agent_id=actor)
        assert res.get("auth_required") is True and res["state"] == "auth-required"
        task = rt.tasks[res["task_id"]]
        assert task.status.state.value == "auth-required"

        await rt.network.authenticate_oneclick(actor)  # actor joins → parked task resumes
        for _ in range(400):
            if task.status.state.value != "auth-required":
                break
            await asyncio.sleep(0.01)
        # it left auth-required → it resumed (now running, escalated, or done)
        assert task.status.state.value in ("working", "input-required", "completed", "failed")
