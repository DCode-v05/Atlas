"""Cron simulator tests — while on, agents continuously launch goals balanced
across departments, driving real inter-agent activity through the same
orchestrator/policy pipeline as the user path, until toggled off."""

from __future__ import annotations

import asyncio

from atlas.config import Settings
from atlas.runtime import build_runtime


async def test_cron_runs_continuously_until_stopped(offline_llm):
    settings = Settings(seed=42, cron_goal_seconds=0.3, cron_tick_seconds=0.1,
                        hitl_timeout_seconds=0.3, cron_max_inflight=4)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)

    status = await rt.cron.toggle(True)
    assert status["running"] is True
    await asyncio.sleep(1.0)  # several goal intervals

    assert rt.cron.running is True  # continuous — does NOT auto-stop
    events = [e.event for e in rt.broker.recent(10_000)]
    assert "cron.state" in events
    assert "cron.tick" in events
    assert "message.sent" in events  # agents actually communicated
    assert any(t.contextId.startswith("cron-") for t in rt.tasks.values())

    await rt.cron.toggle(False)
    assert rt.cron.running is False  # clean cancel


async def test_cron_spreads_goals_across_departments(offline_llm):
    settings = Settings(seed=42, cron_goal_seconds=0.08, cron_tick_seconds=0.04, cron_max_inflight=12)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)

    await rt.cron.toggle(True)
    await asyncio.sleep(1.2)
    await rt.cron.toggle(False)

    depts = set()
    for e in rt.broker.recent(10_000):
        if e.event == "prompt.accepted" and str(e.context_id).startswith("cron-"):
            aid = e.data.get("routed_to")
            if aid in rt.snapshot.agents:
                depts.add(rt.snapshot.agents[aid].profile.department)
    # round-robin over departments → several distinct ones initiate, not just Eng
    assert len(depts) >= 4


async def test_cron_toggle_off_stops_immediately(offline_llm):
    settings = Settings(seed=7, cron_goal_seconds=10.0, cron_tick_seconds=0.1, hitl_timeout_seconds=0.2)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    await rt.cron.toggle(True)
    await asyncio.sleep(0.3)
    assert rt.cron.running is True
    await rt.cron.toggle(False)
    assert rt.cron.running is False
