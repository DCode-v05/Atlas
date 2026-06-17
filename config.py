"""
config.py — central knobs for the ATLAS organisation-of-agents.

One place for: the caps that keep an emergent org bounded, the network ports,
which Runtime backs "hiring", and cosmetic company theming. Everything here is
read once at process start; nothing here is per-mission (mission state lives in
the ledgers, see memory/store.py).
"""
from __future__ import annotations

import os

# --- Identity / theming (cosmetic) ----------------------------------------
COMPANY_NAME = os.getenv("ATLAS_COMPANY", "ATLAS")
DEFAULT_MISSION = "Design and spec a privacy-first smart doorbell"

# --- Network --------------------------------------------------------------
HOST = "127.0.0.1"
GATEWAY_PORT = 8000
EMPLOYEE_PORT_BASE = 9001          # employees listen on 9001, 9002, ...

# --- The A2A org extension ------------------------------------------------
# Namespaced key placed under message.metadata. This is clearly an extension
# layered ON TOP of A2A — never part of the core protocol.
ORG_EXT_URI = "https://atlas.org/ext/org/v1"

# --- Caps that keep an emergent org bounded -------------------------------
# HARD-ENFORCED in code: MAX_HEADCOUNT (the runtime refuses to allocate past it),
# MAX_DELEGATION_DEPTH (managers stop recursing), MAX_REPORTS_PER_MANAGER, and
# MEETING_MAX_PARTICIPANTS. TOKEN_BUDGET is METERED and surfaced in the UI
# (spend vs budget) but is advisory — it does not halt a run.
MAX_HEADCOUNT = int(os.getenv("ATLAS_MAX_HEADCOUNT", "12"))     # total hires per run
MAX_DELEGATION_DEPTH = int(os.getenv("ATLAS_MAX_DEPTH", "3"))   # the CEO is depth 0
TOKEN_BUDGET = int(os.getenv("ATLAS_TOKEN_BUDGET", "150000"))   # advisory, shown in UI
MEETING_MAX_PARTICIPANTS = int(os.getenv("ATLAS_MEETING_MAX", "5"))
MEETING_ROUNDS = int(os.getenv("ATLAS_MEETING_ROUNDS", "3"))  # back-and-forth passes in a round-table

# Currency the agents should use for any costs/budgets in their output.
CURRENCY = os.getenv("ATLAS_CURRENCY", "Indian Rupees (₹)")
MAX_REPORTS_PER_MANAGER = int(os.getenv("ATLAS_MAX_REPORTS", "5"))  # 5 → fits the trip preset
CNP_CANDIDATES = int(os.getenv("ATLAS_CNP_CANDIDATES", "2"))   # employees that bid per role

# --- Runtime: how "hiring" is physically backed ---------------------------
#   "pooled"  -> pre-warm POOL_SIZE generic employee servers; hire = onboard a free one
#   "dynamic" -> spawn a real A2A server per hire on demand, up to MAX_HEADCOUNT
RUNTIME = os.getenv("ATLAS_RUNTIME", "pooled")
POOL_SIZE = int(os.getenv("ATLAS_POOL_SIZE", "12"))  # enough for the CEO + 5 parallel auctions


def employee_port(i: int) -> int:
    """TCP port for the i-th employee (0-based)."""
    return EMPLOYEE_PORT_BASE + i


def gateway_url() -> str:
    return f"http://{HOST}:{GATEWAY_PORT}"
