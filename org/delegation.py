"""
org/delegation.py — how a manager turns a task into a team.

Two clean stages, so topology is a pure swap:
  1. decompose + hire+onboard every report (via Contract-Net auctions). This is
     IDENTICAL across topologies, which keeps the comparison honest.
  2. coordinate the work per the chosen topology (see org/topology.py).

A report that was onboarded with the ``manage`` flag (and has depth budget) will
itself run this same routine on its sub-task — that's the recursion that turns an
"expertising" agent into a sub-orchestrator.
"""
from __future__ import annotations

import asyncio

from config import MAX_DELEGATION_DEPTH, MAX_REPORTS_PER_MANAGER
from org import cognition
from org.contract_net import hire_via_cnp
from org.envelope import Performative, read
from org.onboarding import offer_message
from org.topology import coordinate
from protocol.client import A2AClient
from protocol.models import dump


def should_manage(identity) -> bool:
    """A manager if onboarded, within the depth cap, and either the CEO (depth 0)
    or explicitly hired to lead a sub-team (``manage`` flag set at onboarding)."""
    return (identity.onboarded and identity.depth < MAX_DELEGATION_DEPTH
            and (identity.depth == 0 or identity.manage))


async def run_as_manager(employee, ctx, task_text: str, reporter, *,
                         run_id: str, context_id: str, mission: str) -> str:
    identity = employee.identity
    child_depth = identity.depth + 1
    topology = (read(ctx.metadata) or {}).get("topology", "hierarchical")

    # 1) decompose into roles + sub-tasks
    plan, tok = await cognition.decompose(task_text, identity)
    await reporter.llm(tok, "decompose")
    await reporter.ledger(task={"mission": mission, "facts": plan.get("facts", []),
                                "plan": plan.get("plan", "")})

    roles = plan.get("roles", [])[:MAX_REPORTS_PER_MANAGER]
    if child_depth > MAX_DELEGATION_DEPTH:
        await reporter.cap("depth", f"Max delegation depth {MAX_DELEGATION_DEPTH} reached")
        roles = []

    # 2) hire + onboard every report (same for every topology)
    hired = await asyncio.gather(*[
        _hire_and_onboard(employee, reporter, spec, run_id=run_id,
                          context_id=context_id, child_depth=child_depth)
        for spec in roles])
    hired = [h for h in hired if h]

    # 3) coordinate the work the chosen way
    contributions = await coordinate(topology, employee, reporter, hired,
                                     run_id=run_id, context_id=context_id,
                                     mission=mission, child_depth=child_depth)

    # 4) merge into one result
    final, tok2 = await cognition.synthesize(task_text, contributions)
    await reporter.llm(tok2, "synthesize")
    return final


async def _hire_and_onboard(employee, reporter, spec, *, run_id, context_id, child_depth):
    """Win a worker for this role (auction) and onboard it. Returns (spec, worker)."""
    identity = employee.identity
    title = spec.get("title", "Specialist")
    goal = spec.get("goal", "")
    manage = bool(spec.get("manage")) and child_depth < MAX_DELEGATION_DEPTH

    worker = await hire_via_cnp(employee, reporter, title, run_id=run_id,
                                context_id=context_id, child_depth=child_depth)
    if not worker:
        return None
    client = A2AClient(worker["url"])

    text, md = offer_message(role=title, goal=goal, backstory="", scope=title,
                             depth=child_depth, run_id=run_id, hirer_role=identity.role,
                             hirer_id=employee.agent_id, context_id=context_id, manage=manage)
    await reporter.message(to=worker["agentId"], to_role=title, performative=Performative.propose,
                           intent=f"onboard as {title}", depth=child_depth,
                           context_id=context_id, text=text)
    await client.send_text(text, context_id=context_id, metadata=md)
    try:                                  # A2A discovery: fetch the now role-aware Agent Card
        await reporter.emit("card", agentId=worker["agentId"], role=title,
                            card=dump(await client.get_card()))
    except Exception:
        pass
    await reporter.ledger(progressStep={"agentId": worker["agentId"], "role": title,
                                        "task": spec.get("task", ""), "status": "assigned"})
    return (spec, worker)
