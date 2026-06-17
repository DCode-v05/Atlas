"""
org/topology.py — the three communication patterns over the SAME hired team.

Who got hired (by auction) is identical across topologies; only HOW the team
coordinates to do the work changes — which is exactly what the comparison mode
measures.

  hierarchical : the manager delegates 1:1; reports work in isolation, in parallel.
  mesh         : reports ALSO consult each other directly (peer-to-peer A2A),
                 not only the manager — more chatter, more resilience.
  group        : the manager convenes a meeting (one shared contextId); speakers
                 take turns and each sees what was said before.
"""
from __future__ import annotations

import asyncio

from org.envelope import Performative, meta
from org.meeting import run_meeting
from protocol.client import A2AClient
from protocol.models import result_text


async def coordinate(topology, employee, reporter, hired, *, run_id, context_id,
                     mission, child_depth) -> list[tuple[str, str]]:
    if not hired:
        return []
    if topology == "group":
        return await run_meeting(employee, reporter, hired, run_id=run_id,
                                 mission=mission, child_depth=child_depth)

    peers = None
    if topology == "mesh":
        peers = [{"agentId": w["agentId"], "url": w["url"], "role": s["title"]}
                 for s, w in hired]

    results = await asyncio.gather(*[
        _delegate(employee, reporter, spec, worker, run_id=run_id, context_id=context_id,
                  mission=mission, child_depth=child_depth, topology=topology,
                  peers=([p for p in peers if p["agentId"] != worker["agentId"]]
                         if peers else None))
        for spec, worker in hired])
    return [r for r in results if r]


async def _delegate(employee, reporter, spec, worker, *, run_id, context_id, mission,
                    child_depth, topology, peers=None) -> tuple[str, str]:
    title = spec.get("title", "Specialist")
    subtask = spec.get("task", mission)
    client = A2AClient(worker["url"])
    extra = {"runId": run_id, "contextId": context_id, "senderId": employee.agent_id,
             "mission": mission, "topology": topology}
    if peers:
        extra["peers"] = peers                    # mesh: who this worker may consult
    req_md = meta(Performative.request, role=employee.identity.role, intent=subtask[:80],
                  motivation=spec.get("goal", ""), delegation_depth=child_depth,
                  scope=title, extra=extra)
    await reporter.message(to=worker["agentId"], to_role=title, performative=Performative.request,
                           intent=subtask[:80], scope=title, depth=child_depth,
                           context_id=context_id, text=subtask)
    task = await client.send_text(subtask, context_id=context_id, metadata=req_md)
    await reporter.ledger(progressStep={"agentId": worker["agentId"], "role": title,
                                        "task": subtask, "status": "done"})
    return (title, result_text(task) or "")
