"""
org/ledger.py — the org's shared brain (Magentic-One style).

Two ledgers, persisted per run and shown live in the UI:

  * Task Ledger     — the mission, the facts gathered, and the plan. Written by
                      a manager right after it decomposes a problem.
  * Progress Ledger — a row per delegated step (who, doing what, status). Updated
                      as the org works, so anyone can see where things stand.

Both are plain dicts so they serialise straight to JSON for the UI and SQLite.
"""
from __future__ import annotations


def blank() -> dict:
    return {"task": {"mission": "", "facts": [], "plan": ""},
            "progress": {"steps": []}}


def apply(ledgers: dict, ev: dict) -> None:
    """Fold a `ledger` telemetry event into the stored ledgers in place.

    A ledger event may carry:
      * task         — a full Task Ledger dict (replaces the current one)
      * progressStep — one step {agentId, role, task, status} (upsert by agentId)
    """
    if ev.get("type") != "ledger":
        return
    if isinstance(ev.get("task"), dict):
        ledgers["task"] = ev["task"]
    step = ev.get("progressStep")
    if isinstance(step, dict):
        steps = ledgers["progress"]["steps"]
        for existing in steps:
            if existing.get("agentId") == step.get("agentId") and \
               existing.get("role") == step.get("role"):
                existing.update(step)
                return
        steps.append(step)
