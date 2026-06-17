"""
memory/store.py — SQLite persistence for the organisation.

What we keep, per mission run:
  * runs        — the mission, chosen topology, status, final output
  * events      — the full telemetry stream (every message/hire/ledger update),
                  so a run can be replayed or restored after a refresh
  * ledgers     — the Task Ledger + Progress Ledger (the org's shared brain)

This is the "context persistence across agent conversations" layer. Everything
is keyed by ``run_id``; a run's conversation thread reuses the A2A ``contextId``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DB_PATH = os.path.join(_DB_DIR, "atlas.db")
_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None


def _conn() -> sqlite3.Connection:
    """One persistent connection for the process (telemetry is high-volume).
    Shared across our agent threads, guarded by _LOCK."""
    global _CONN
    if _CONN is None:
        os.makedirs(_DB_DIR, exist_ok=True)
        _CONN = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
    return _CONN


def _execute(sql: str, params: tuple = ()) -> None:
    with _LOCK:
        c = _conn()
        c.execute(sql, params)
        c.commit()


def _query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _LOCK:
        return _conn().execute(sql, params).fetchall()


def init_db() -> None:
    with _LOCK:
        _conn().executescript(
            """
                CREATE TABLE IF NOT EXISTS runs(
                    run_id   TEXT PRIMARY KEY,
                    mission  TEXT,
                    topology TEXT,
                    status   TEXT,
                    created  TEXT,
                    final    TEXT
                );
                CREATE TABLE IF NOT EXISTS events(
                    id     INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    seq    INTEGER,
                    ts     TEXT,
                    payload TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
                CREATE TABLE IF NOT EXISTS ledgers(
                    run_id          TEXT PRIMARY KEY,
                    task_ledger     TEXT,
                    progress_ledger TEXT
                );
                """
        )
        _conn().commit()


# ---- runs -----------------------------------------------------------------
def create_run(run_id: str, mission: str, topology: str, created: str) -> None:
    _execute("INSERT OR REPLACE INTO runs(run_id,mission,topology,status,created,final) "
             "VALUES(?,?,?,?,?,?)", (run_id, mission, topology, "running", created, None))


def finish_run(run_id: str, final: str, status: str = "done") -> None:
    _execute("UPDATE runs SET status=?, final=? WHERE run_id=?", (status, final, run_id))


def get_run(run_id: str) -> dict | None:
    rows = _query("SELECT * FROM runs WHERE run_id=?", (run_id,))
    return dict(rows[0]) if rows else None


def recent_runs(limit: int = 20) -> list[dict]:
    rows = _query("SELECT run_id,mission,topology,status,created FROM runs "
                  "ORDER BY created DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


# ---- events (telemetry) ---------------------------------------------------
def add_event(run_id: str, seq: int, ts: str, payload: dict) -> None:
    _execute("INSERT INTO events(run_id,seq,ts,payload) VALUES(?,?,?,?)",
             (run_id, seq, ts, json.dumps(payload)))


def load_events(run_id: str) -> list[dict]:
    rows = _query("SELECT payload FROM events WHERE run_id=? ORDER BY seq", (run_id,))
    return [json.loads(r["payload"]) for r in rows]


# ---- ledgers --------------------------------------------------------------
def save_ledgers(run_id: str, task_ledger: dict, progress_ledger: dict) -> None:
    _execute("INSERT OR REPLACE INTO ledgers(run_id,task_ledger,progress_ledger) VALUES(?,?,?)",
             (run_id, json.dumps(task_ledger), json.dumps(progress_ledger)))


def load_ledgers(run_id: str) -> dict | None:
    rows = _query("SELECT task_ledger,progress_ledger FROM ledgers WHERE run_id=?", (run_id,))
    if not rows:
        return None
    return {"taskLedger": json.loads(rows[0]["task_ledger"]),
            "progressLedger": json.loads(rows[0]["progress_ledger"])}
