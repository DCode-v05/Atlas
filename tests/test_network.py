"""Authenticated-network tests (SQLite — no Postgres needed).

Covers the Ed25519 challenge/response, scoped-JWT issuance + verification,
single-use nonces, revocable sessions, session survival across a restart, the
`/api/network` endpoints, and the no-DB 503.
"""

from __future__ import annotations

import httpx
from sqlalchemy import select

from atlas.config import Settings
from atlas.db import Database, seed_org
from atlas.db.models import AgentCredentialRow
from atlas.events import EventBroker
from atlas.main import create_app, lifespan
from atlas.network.auth import NetworkService
from atlas.network.keys import sign
from atlas.org.generator import generate_org
from atlas.runtime import build_runtime


async def _service(tmp_path, name="n"):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/{name}.db")
    await db.create_all()
    snap = generate_org(42)
    await seed_org(db, snap)
    net = NetworkService(db, EventBroker(), snap)
    await net.init()
    return db, net, snap


async def _privkey(db, agent_id):
    async with db.session() as s:
        return (await s.execute(
            select(AgentCredentialRow.private_key).where(AgentCredentialRow.agent_id == agent_id)
        )).scalar_one()


async def test_challenge_response_join_and_scoped_token(tmp_path):
    db, net, snap = await _service(tmp_path)
    aid = next(iter(snap.agents))
    assert not net.is_member(aid)  # network starts empty

    ch = await net.create_challenge(aid)
    res = await net.authenticate(aid, ch["nonce"], sign(await _privkey(db, aid), ch["nonce"].encode()))

    assert res and res["token"] and res["token_type"] == "Bearer"
    assert net.is_member(aid)
    claims = net.verify_token(res["token"])
    assert claims and claims["sub"] == aid and "network:communicate" in claims["scopes"]
    assert claims["department"] == snap.agents[aid].profile.department.value
    assert claims["clearance"] == snap.agents[aid].profile.clearance
    assert any(e.event == "network.joined" for e in net.broker.recent(20))
    await db.dispose()


async def test_nonce_single_use_and_bad_signature_rejected(tmp_path):
    db, net, snap = await _service(tmp_path)
    aid = next(iter(snap.agents))
    priv = await _privkey(db, aid)

    ch = await net.create_challenge(aid)
    assert await net.authenticate(aid, ch["nonce"], b"garbage") is None       # bad signature
    # the nonce was consumed — a correct signature on the SAME nonce now fails (single-use)
    assert await net.authenticate(aid, ch["nonce"], sign(priv, ch["nonce"].encode())) is None
    assert not net.is_member(aid)
    # a fresh challenge works
    ch2 = await net.create_challenge(aid)
    assert await net.authenticate(aid, ch2["nonce"], sign(priv, ch2["nonce"].encode())) is not None
    await db.dispose()


async def test_oneclick_join_disconnect_and_revocation(tmp_path):
    db, net, snap = await _service(tmp_path)
    aid = next(iter(snap.agents))
    res = await net.authenticate_oneclick(aid)
    assert res and net.is_member(aid) and net.verify_token(res["token"])

    assert await net.disconnect(aid) is True
    assert not net.is_member(aid)
    assert net.verify_token(res["token"]) is None  # revoked session → token no longer valid
    assert any(e.event == "network.left" for e in net.broker.recent(50))
    await db.dispose()


async def test_session_survives_restart(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/restart.db"
    db = Database(url)
    await db.create_all()
    snap = generate_org(42)
    await seed_org(db, snap)
    net = NetworkService(db, EventBroker(), snap)
    await net.init()
    aid = next(iter(snap.agents))
    await net.authenticate_oneclick(aid)
    await db.dispose()

    db2 = Database(url)  # "restart" over the same file
    net2 = NetworkService(db2, EventBroker(), snap)
    await net2.init()
    assert net2.is_member(aid)  # the session persisted — no re-auth needed
    await db2.dispose()


async def test_network_endpoints_join_flow(tmp_path, offline_llm):
    settings = Settings(seed=42, database_url=f"sqlite+aiosqlite:///{tmp_path}/api.db", _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    await rt.db.create_all()
    await seed_org(rt.db, rt.snapshot)
    await rt.network.init()
    app = create_app()
    app.state.runtime = rt
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        aid = (await c.get("/api/org")).json()["nodes"][0]["id"]
        assert (await c.get("/api/network")).json()["count"] == 0  # empty network
        res = (await c.post(f"/api/network/agents/{aid}/join")).json()
        assert res["agent_id"] == aid and res["token"]
        assert (await c.get("/api/network")).json()["count"] == 1
        assert (await c.post("/api/network/verify", json={"token": res["token"]})).json()["valid"] is True
        assert (await c.post(f"/api/network/agents/{aid}/disconnect")).json()["ok"] is True
        assert (await c.get("/api/network")).json()["count"] == 0
        assert (await c.post("/api/network/verify", json={"token": res["token"]})).status_code == 401
    await rt.db.dispose()


async def test_network_requires_db(offline_llm):
    rt = build_runtime(Settings(seed=42, _env_file=None), step_delay=0.0, llm=offline_llm)
    app = create_app()
    app.state.runtime = rt
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/network")).status_code == 503


async def test_membership_gating_routes_only_to_joined_agents(tmp_path, offline_llm):
    settings = Settings(seed=42, database_url=f"sqlite+aiosqlite:///{tmp_path}/gate.db", _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    await rt.db.create_all()
    await seed_org(rt.db, rt.snapshot)
    await rt.network.init()
    orch = rt.orchestrator

    # empty network → nobody to route to → the prompt is rejected
    res = await orch.run_user_prompt("help me fix the deployment pipeline incident on prod")
    assert res["rejected"] is True and "network" in res["reason"].lower()

    # join only two senior agents → a DevOps task has no plausible owner in the network → out of scope
    for aid in list(rt.snapshot.agents)[:2]:
        await rt.network.authenticate_oneclick(aid)
    res_off = await orch.run_user_prompt("help me fix the deployment pipeline incident on prod")
    assert res_off["rejected"] is True  # network-scope gate: the team it needs hasn't joined

    # join everyone → the relevant owner is now in the network → it routes to a joined member
    for aid in rt.snapshot.agents:
        await rt.network.authenticate_oneclick(aid)
    assert len(orch._agent_directory(orch._pool_ids()).splitlines()) == 100  # directory = full network
    res_on = await orch.run_user_prompt("help me fix the deployment pipeline incident on prod")
    assert res_on["rejected"] is False and res_on["routed_to"] in set(rt.snapshot.agents)
    await rt.db.dispose()


async def test_writethrough_persists_runtime_record(tmp_path, offline_llm):
    """Tasks + messages are persisted at the point of record (the Router chokepoint)."""
    import asyncio

    from sqlalchemy import func

    from atlas.a2a.models import TaskState
    from atlas.db.models import MessageRow, TaskRow

    settings = Settings(seed=42, database_url=f"sqlite+aiosqlite:///{tmp_path}/wt.db", _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    await rt.db.create_all()
    await seed_org(rt.db, rt.snapshot)
    await rt.network.init()
    await rt.dbwriter.start(rt.broker)

    aid = next(iter(rt.snapshot.agents))
    await rt.network.authenticate_oneclick(aid)  # a member, so the Router lets it speak

    task = rt.router.new_task("ctx-wt", message="kick off")
    rt.router.send_message(context_id="ctx-wt", sender=aid, recipients=["operator"], text="on it", task=task)
    rt.router.set_task_state(task, TaskState.COMPLETED, message="all done")

    for _ in range(200):  # let the write-through worker drain its queue
        if rt.dbwriter.written >= 3:
            break
        await asyncio.sleep(0.005)

    async with rt.db.session() as s:
        ntasks = (await s.execute(select(func.count()).select_from(TaskRow))).scalar_one()
        nmsgs = (await s.execute(select(func.count()).select_from(MessageRow))).scalar_one()
        trow = await s.get(TaskRow, task.id)
    assert ntasks >= 1 and nmsgs >= 1
    assert trow.state == "completed" and trow.summary == "all done"  # summary preserved across state ticks

    await rt.dbwriter.stop()
    await rt.db.dispose()


async def test_lifespan_boots_db_network_and_writer(tmp_path, offline_llm):
    """The REAL app lifespan (what Docker runs) wires DB + network + write-through end-to-end."""
    settings = Settings(seed=42, database_url=f"sqlite+aiosqlite:///{tmp_path}/life.db",
                        hitl_timeout_seconds=0.0, _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    app = create_app(runtime=rt)  # the lifespan picks this up instead of building one

    async with lifespan(app):  # startup: create_all + seed + network.init + dbwriter.start + heartbeat/push
        assert rt.network.active and rt.dbwriter._worker is not None  # boot wiring ran
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/api/network")).json()["count"] == 0  # DB-on default ⇒ network starts empty
            aid = (await c.get("/api/org")).json()["nodes"][0]["id"]
            assert (await c.post(f"/api/network/agents/{aid}/join")).json()["token"]
            assert (await c.get("/api/network")).json()["count"] == 1
    assert rt.dbwriter._worker is None  # shutdown: the write-through worker was stopped cleanly


async def test_history_replays_conversation_in_seq_order(tmp_path, offline_llm):
    """The persisted record replays via /api/history — messages in true write order (seq, not
    second-granularity ts), timestamps normalized to milliseconds for the UI timeline."""
    import asyncio

    settings = Settings(seed=42, database_url=f"sqlite+aiosqlite:///{tmp_path}/hist.db", _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    app = create_app(runtime=rt)
    async with lifespan(app):
        rt.dbwriter.record("conversation", {"context_id": "ctx-h", "prompt": "the billing question",
                                            "kind": "user", "routed_to": "SEP-x", "routed_to_name": "Ada", "task_id": "t1"})
        for i, txt in enumerate(["first", "second", "third"]):  # all in the same second → order must come from seq
            rt.dbwriter.record("message", {"id": f"m{i}", "context_id": "ctx-h", "sender": "SEP-x",
                                           "recipients": ["operator"], "mode": "individual", "role": "agent", "text": txt})
        for _ in range(300):
            if rt.dbwriter.written >= 4:
                break
            await asyncio.sleep(0.005)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            data = (await c.get("/api/history")).json()

    convos = data["conversations"]
    assert len(convos) == 1
    conv = convos[0]
    assert conv["prompt"] == "the billing question" and conv["kind"] == "user"
    assert [m["text"] for m in conv["messages"]] == ["first", "second", "third"]  # seq order
    assert conv["messages"][0]["ts"] > 1_000_000_000_000  # milliseconds, not seconds


async def test_history_clear_wipes_record_but_keeps_org(tmp_path, offline_llm):
    """POST /api/history/clear deletes the conversation record; the org + network stay."""
    import asyncio

    from sqlalchemy import func, select

    from atlas.db.models import AgentRow

    settings = Settings(seed=42, database_url=f"sqlite+aiosqlite:///{tmp_path}/clr.db", _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    app = create_app(runtime=rt)
    async with lifespan(app):
        rt.dbwriter.record("conversation", {"context_id": "ctx-c", "prompt": "p", "kind": "user",
                                            "routed_to": "SEP-x", "routed_to_name": "Ada", "task_id": "t"})
        rt.dbwriter.record("message", {"id": "m0", "context_id": "ctx-c", "sender": "SEP-x",
                                       "recipients": ["operator"], "mode": "individual", "role": "agent", "text": "hi"})
        for _ in range(300):
            if rt.dbwriter.written >= 2:
                break
            await asyncio.sleep(0.005)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            assert len((await c.get("/api/history")).json()["conversations"]) == 1
            assert (await c.post("/api/history/clear")).json()["ok"] is True
            assert (await c.get("/api/history")).json()["conversations"] == []
        async with rt.db.session() as s:  # the org survives the wipe
            assert (await s.execute(select(func.count()).select_from(AgentRow))).scalar_one() == 100


async def test_router_backstop_blocks_non_members(tmp_path, offline_llm):
    """send_message's own membership invariant — the chokepoint backstop, independent of routing."""
    settings = Settings(seed=42, database_url=f"sqlite+aiosqlite:///{tmp_path}/bs.db", _env_file=None)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    await rt.db.create_all()
    await seed_org(rt.db, rt.snapshot)
    await rt.network.init()
    member, outsider = list(rt.snapshot.agents)[:2]
    await rt.network.authenticate_oneclick(member)

    # non-member sender → dropped
    assert rt.router.send_message(context_id="c", sender=outsider, recipients=[member], text="hi") is None
    # member → non-member recipient is filtered out, leaving nobody → dropped
    assert rt.router.send_message(context_id="c", sender=member, recipients=[outsider], text="hi") is None
    # member → the operator edge is always allowed → delivered
    assert rt.router.send_message(context_id="c", sender=member, recipients=["operator"], text="hi") is not None
    await rt.db.dispose()
