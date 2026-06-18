"""Cron simulator tests — a short burst drives real inter-agent activity and
auto-stops, using the same orchestrator/policy pipeline as the user path."""

from __future__ import annotations

import asyncio

from atlas.config import Settings
from atlas.runtime import build_runtime


async def test_cron_burst_emits_activity_and_stops(offline_llm):
    settings = Settings(seed=42, cron_burst_seconds=0.6, cron_tick_seconds=0.12, hitl_timeout_seconds=0.3)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)

    status = await rt.cron.toggle(True)
    assert status["running"] is True
    await asyncio.sleep(1.2)  # burst (0.6s) + drain

    assert rt.cron.running is False  # auto-stopped after the burst
    events = [e.event for e in rt.broker.recent(10_000)]
    assert "cron.state" in events
    assert "cron.tick" in events
    assert "message.sent" in events  # agents actually communicated
    assert any(t.contextId.startswith("cron-") for t in rt.tasks.values())


async def test_cron_toggle_off_stops_immediately(offline_llm):
    settings = Settings(seed=7, cron_burst_seconds=10.0, cron_tick_seconds=0.1, hitl_timeout_seconds=0.2)
    rt = build_runtime(settings, step_delay=0.0, llm=offline_llm)
    await rt.cron.toggle(True)
    await asyncio.sleep(0.3)
    assert rt.cron.running is True
    await rt.cron.toggle(False)
    assert rt.cron.running is False
