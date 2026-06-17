"""
org/cognition.py — what an agent THINKS (as opposed to how it communicates).

Three reasoning steps a manager/worker needs:
  * decompose  — break a mission into roles + sub-tasks (manager)
  * do_work    — produce a deliverable in a given role (worker)
  * synthesize — merge contributions into one result (manager)

Each runs on Groq when a key is present, and on a DETERMINISTIC template when
offline. The offline path is intentionally reproducible so comparison runs vary
ONLY by communication topology, never by what the agents happened to think.

Every function returns ``(value, tokens)`` so the caller can meter the run.
"""
from __future__ import annotations

import json
import re

from config import MAX_DELEGATION_DEPTH
from llm.client import LLMResult, complete, est_tokens, using_real_llm
from org.onboarding import Identity

# A canonical product-company role catalogue. The offline planner draws from this
# deterministically; the online planner is free to invent its own roles.
CATALOG = [
    ("Product Manager", "Define what to build and why, with clear requirements"),
    ("Engineering Lead", "Design the technical architecture and implementation plan"),
    ("Design Lead", "Design the user experience, flows and visual language"),
    ("Marketing Lead", "Position the product and plan the go-to-market"),
    ("Quality Lead", "Define the quality bar, risks and a test strategy"),
]


# ---------------------------------------------------------------- decompose
_DECOMPOSE_SYS = (
    "You are a manager in a product company. Break the given mission into a small "
    "team (2-4 roles). Reply with ONLY JSON: {\"plan\": str, \"facts\": [str], "
    "\"roles\": [{\"title\": str, \"goal\": str, \"task\": str}]}. Keep it tight.")


def _wants_team(title: str) -> bool:
    return bool(re.search(r"lead|manager|head|director|chief|vp", title, re.I))


async def decompose(task_text: str, identity: Identity) -> tuple[dict, int]:
    child_depth = identity.depth + 1
    can_recurse = child_depth < MAX_DELEGATION_DEPTH      # is there depth budget below?

    if using_real_llm():
        user = f"MISSION: {task_text}\nYou are the {identity.role}. Decompose into 2-4 roles."
        res: LLMResult = await complete(_DECOMPOSE_SYS, user, temperature=0.2, max_tokens=600)
        data = _parse_json(res.text) or {}
        roles = [r for r in data.get("roles", []) if r.get("title")][:4]
        if roles:
            for r in roles:                              # a 'Lead/Manager' role gets a sub-team
                r["manage"] = _wants_team(r.get("title", "")) and can_recurse
            return ({"plan": data.get("plan", ""), "facts": data.get("facts", []),
                     "roles": roles}, res.tokens)

    # deterministic offline: a manager at depth 0 fields a small C-suite (one of
    # whom — the Engineering Lead — will itself build a sub-team); deeper managers
    # split their scope into two ICs.
    if identity.depth == 0:
        specs = [("Engineering Lead", "design the architecture and lead the build", True),
                 ("Design Lead", "design the experience, flows and visuals", False),
                 ("Marketing Lead", "position the product and plan go-to-market", False)]
    else:
        base = identity.role.replace(" Lead", "").replace(" Manager", "")
        specs = [(f"{base} Specialist A", f"own the first half of {base.lower()}", False),
                 (f"{base} Specialist B", f"own the second half of {base.lower()}", False)]

    roles = [{"title": t, "goal": g, "manage": bool(m) and can_recurse,
              "task": f"As {t} for the mission '{task_text}', deliver your part: {g}."}
             for (t, g, m) in specs]
    plan = (f"Deliver '{task_text}' via {len(roles)} reports: "
            + ", ".join(r["title"] for r in roles) + ".")
    return {"plan": plan, "facts": [f"Mission: {task_text}"], "roles": roles}, est_tokens(task_text, plan)


# ------------------------------------------------------------------ do_work
async def do_work(identity: Identity, task_text: str, mission: str) -> tuple[str, int]:
    if using_real_llm():
        sys = (f"You are the {identity.role}. Backstory: {identity.backstory or 'a seasoned expert'}. "
               f"Produce a concise, concrete deliverable (Markdown, < 180 words) for your part of "
               f"the mission. Do not restate the whole mission.")
        res = await complete(sys, f"OVERALL MISSION: {mission}\nYOUR TASK: {task_text}",
                             temperature=0.4, max_tokens=400)
        return res.text, res.tokens
    body = (f"## {identity.role} — deliverable\n\n"
            f"**Goal:** {identity.goal or 'contribute to the mission'}\n\n"
            f"- Key recommendation for *{mission}* from a {identity.role.lower()} view.\n"
            f"- Concrete next step owned by the {identity.role.lower()}.\n"
            f"- One risk to watch and how to mitigate it.\n")
    return body, est_tokens(task_text, body)


# ---------------------------------------------------------------- synthesize
async def synthesize(mission: str, contributions: list[tuple[str, str]]) -> tuple[str, int]:
    """contributions: list of (role, text)."""
    if using_real_llm():
        sys = ("You are the manager. Merge the team's contributions into ONE coherent, "
               "well-structured Markdown result that fulfils the mission. No duplication; "
               "do not mention that inputs came separately.")
        joined = "\n\n".join(f"### From {role}\n{text}" for role, text in contributions)
        res = await complete(sys, f"MISSION: {mission}\n\nCONTRIBUTIONS:\n{joined}",
                             temperature=0.3, max_tokens=1200)
        return res.text, res.tokens
    parts = [f"# {mission}\n", "_Synthesised by the manager from the team's contributions._\n"]
    for role, text in contributions:
        parts.append(text if text.strip().startswith("#") else f"## {role}\n{text}")
    out = "\n\n".join(parts)
    return out, est_tokens(mission, out)


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
