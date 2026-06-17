"""
memory.py — the prototype's persistent memory (SQLite, standard library only).
==============================================================================

This is the "stateful agent layer" the base A2A demo deliberately left out. It
gives the orchestrator three kinds of memory, all durable across restarts:

1. CONVERSATION state (per A2A `contextId`):
   - beliefs  : the current trip understanding {destination, days, interests, style}
   - intent   : the goal/motivation behind the conversation {goal, constraints, ...}
   - results  : each specialist's last answer (used as a cache for follow-ups)
2. TURN history (per contextId): every user request + the plan we produced.
3. USER memory (per user): durable preferences learned across conversations
   (e.g. "prefers budget travel", "loves food markets").

We use only Python's built-in `sqlite3` — no extra dependency, one small file at
`data/atlas.db`. Calls are synchronous and fast; async callers wrap them in
`asyncio.to_thread` so the event loop never blocks.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "atlas.db"
DEFAULT_USER = "local"   # single demo user; real apps would key this per account


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the tables once (safe to call repeatedly)."""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                context_id   TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                beliefs_json TEXT,
                intent_json  TEXT,
                results_json TEXT,
                updated_at   TEXT
            );
            CREATE TABLE IF NOT EXISTS turns (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                context_id   TEXT NOT NULL,
                user_request TEXT,
                plan_md      TEXT,
                created_at   TEXT
            );
            CREATE TABLE IF NOT EXISTS user_memory (
                user_id    TEXT NOT NULL,
                fact       TEXT NOT NULL,
                created_at TEXT,
                PRIMARY KEY (user_id, fact)
            );
            """
        )


def new_context_id() -> str:
    return "ctx-" + uuid.uuid4().hex[:12]


# --- conversation state ----------------------------------------------------

def load_conversation(context_id: str) -> dict | None:
    """Return {beliefs, intent, results} for a context, or None if unknown."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT beliefs_json, intent_json, results_json FROM conversations "
            "WHERE context_id = ?", (context_id,)).fetchone()
    if not row:
        return None
    return {
        "beliefs": json.loads(row["beliefs_json"] or "null"),
        "intent": json.loads(row["intent_json"] or "null"),
        "results": json.loads(row["results_json"] or "{}"),
    }


def save_conversation(context_id: str, beliefs: dict, intent: dict,
                      results: dict, user_id: str = DEFAULT_USER) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO conversations
                 (context_id, user_id, beliefs_json, intent_json, results_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(context_id) DO UPDATE SET
                 beliefs_json=excluded.beliefs_json,
                 intent_json=excluded.intent_json,
                 results_json=excluded.results_json,
                 updated_at=excluded.updated_at""",
            (context_id, user_id, json.dumps(beliefs), json.dumps(intent),
             json.dumps(results), _now()))


# --- turn history ----------------------------------------------------------

def add_turn(context_id: str, user_request: str, plan_md: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO turns (context_id, user_request, plan_md, created_at) "
            "VALUES (?, ?, ?, ?)", (context_id, user_request, plan_md, _now()))


def load_turns(context_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_request, plan_md, created_at FROM turns "
            "WHERE context_id = ? ORDER BY id", (context_id,)).fetchall()
    return [{"request": r["user_request"], "plan": r["plan_md"],
             "createdAt": r["created_at"]} for r in rows]


# --- long-term user memory -------------------------------------------------

def load_user_memory(user_id: str = DEFAULT_USER) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT fact FROM user_memory WHERE user_id = ? ORDER BY created_at",
            (user_id,)).fetchall()
    return [r["fact"] for r in rows]


def add_user_memory(facts: list[str], user_id: str = DEFAULT_USER) -> list[str]:
    """Store new durable facts (deduplicated). Returns the facts actually added."""
    added = []
    with _connect() as conn:
        for fact in facts:
            fact = (fact or "").strip()
            if not fact:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO user_memory (user_id, fact, created_at) "
                "VALUES (?, ?, ?)", (user_id, fact, _now()))
            if cur.rowcount:
                added.append(fact)
    return added


def reset_conversation(context_id: str) -> None:
    """Forget one conversation (its state + turns). User memory is kept."""
    with _connect() as conn:
        conn.execute("DELETE FROM conversations WHERE context_id = ?", (context_id,))
        conn.execute("DELETE FROM turns WHERE context_id = ?", (context_id,))
