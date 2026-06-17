"""
org/cognition.py — what an agent THINKS (as opposed to how it communicates).

Four reasoning steps, all on Groq (real LLM only — no offline mock):
  * lead_title  — a mission-appropriate title for the top agent
  * decompose   — break a mission into roles + sub-tasks (manager)
  * do_work     — produce a deliverable in a given role (worker)
  * synthesize  — merge contributions into one result (manager)

Each LLM-backed step returns ``(value, tokens)`` so the caller can meter the run.
"""
from __future__ import annotations

import json
import re

from config import MAX_DELEGATION_DEPTH
from llm.client import complete
from org.onboarding import Identity


def _wants_team(title: str) -> bool:
    return bool(re.search(r"lead|manager|head|director|chief|vp|officer", title, re.I))


# ------------------------------------------------------------------ lead_title
_LEAD_STOP = {"a", "an", "the", "for", "to", "of", "and", "with", "plan", "design",
              "build", "write", "create", "produce", "develop", "spec", "make",
              "launch", "new", "weekend", "minimal", "tiny", "complete", "full"}
_LEAD_SYS = ("You name organisational roles. Reply with ONLY a 2-3 word job TITLE "
             "(no quotes, no punctuation) for the single accountable leader who would "
             "own this mission end to end. E.g. a coffee festival -> Festival Director.")


def _derive_lead_title(mission: str) -> str:
    """A title derived straight from the mission text — used only if the model
    call fails. Still mission-specific, not canned."""
    words = re.findall(r"[A-Za-z][A-Za-z\-]+", mission.lower())
    kept = [w for w in words if w not in _LEAD_STOP]
    subject = " ".join(kept[:2]).title() if kept else "Program"
    return f"{subject} Lead"


async def lead_title(mission: str) -> str:
    try:
        res = await complete(_LEAD_SYS, f"MISSION: {mission}", temperature=0.3, max_tokens=12)
        t = res.text.strip().strip('".').splitlines()[0][:40].strip()
        if 2 <= len(t) <= 40:
            return t
    except Exception:
        pass
    return _derive_lead_title(mission)


# ------------------------------------------------------------------ decompose
_DECOMPOSE_SYS = (
    "You are a manager in a product company. Break the given mission into a small "
    "team (2-4 roles). Reply with ONLY JSON: {\"plan\": str, \"facts\": [str], "
    "\"roles\": [{\"title\": str, \"goal\": str, \"task\": str}]}. Keep it tight.")


async def decompose(task_text: str, identity: Identity) -> tuple[dict, int]:
    child_depth = identity.depth + 1
    can_recurse = child_depth < MAX_DELEGATION_DEPTH

    user = f"MISSION: {task_text}\nYou are the {identity.role}. Decompose into 2-4 roles."
    res = await complete(_DECOMPOSE_SYS, user, temperature=0.2, max_tokens=600)
    data = _parse_json(res.text) or {}
    roles = [r for r in data.get("roles", []) if r.get("title")][:4]
    if not roles:
        # resilient fallback if the model returns no usable roles (not a domain mock)
        roles = [{"title": "Lead Contributor", "goal": "own the core of the mission"},
                 {"title": "Support Contributor", "goal": "own the remaining scope"}]
    for r in roles:
        r.setdefault("goal", "")
        r.setdefault("task", f"As {r['title']} for the mission '{task_text}', deliver your part.")
        r["manage"] = _wants_team(r.get("title", "")) and can_recurse
    return {"plan": data.get("plan", ""), "facts": data.get("facts", []), "roles": roles}, res.tokens


# ------------------------------------------------------------------ do_work
async def do_work(identity: Identity, task_text: str, mission: str) -> tuple[str, int]:
    sys = (f"You are the {identity.role}. Backstory: {identity.backstory or 'a seasoned expert'}. "
           f"Produce a concise, concrete deliverable (Markdown, < 180 words) for your part of the "
           f"mission. Do not restate the whole mission.")
    res = await complete(sys, f"OVERALL MISSION: {mission}\nYOUR TASK: {task_text}",
                         temperature=0.4, max_tokens=400)
    return res.text, res.tokens


# ------------------------------------------------------------------ synthesize
async def synthesize(mission: str, contributions: list[tuple[str, str]]) -> tuple[str, int]:
    """contributions: list of (role, text)."""
    sys = ("You are the manager. Merge the team's contributions into ONE coherent, well-structured "
           "Markdown result that fulfils the mission. No duplication; do not mention that inputs "
           "came separately.")
    joined = "\n\n".join(f"### From {role}\n{text}" for role, text in contributions)
    res = await complete(sys, f"MISSION: {mission}\n\nCONTRIBUTIONS:\n{joined}",
                         temperature=0.3, max_tokens=1200)
    return res.text, res.tokens


# ------------------------------------------------------------------ helpers
def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                return None
    return None
