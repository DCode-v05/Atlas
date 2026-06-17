"""
org/ceo.py — the "board" hires the first employee as CEO and hands over the mission.

This is the only privileged step in the whole system: the Board (the gateway,
on the user's behalf) onboards employee #1 as the CEO and sends it the mission.
From there everything is just agents talking to agents — the CEO decomposes,
hires, delegates, and finally returns the synthesised result.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from org.envelope import Performative, meta
from org.onboarding import offer_message
from protocol.client import A2AClient
from protocol.models import result_text

EmitFn = Callable[[dict], Awaitable[None]]
AllocateFn = Callable[..., dict | None]


async def run_mission(allocate: AllocateFn, emit: EmitFn, *, run_id: str,
                      mission: str, context_id: str,
                      topology: str = "hierarchical") -> str:
    ceo = await allocate(run_id, "CEO", "Board", 0)
    if not ceo:
        await emit({"type": "run", "phase": "error", "message": "No capacity to hire a CEO."})
        return ""
    cid, client = ceo["agentId"], A2AClient(ceo["url"])
    await emit({"type": "hire", "agentId": cid, "role": "CEO", "parentId": "Board", "depth": 0})

    # onboard the CEO (propose -> accept)
    text, md = offer_message(role="CEO", goal=mission, backstory="the founder",
                             scope="the whole mission", depth=0, run_id=run_id,
                             hirer_role="Board", hirer_id="Board", context_id=context_id)
    await emit({"type": "message", "from": "Board", "fromRole": "Board", "to": cid,
                "toRole": "CEO", "performative": Performative.propose,
                "intent": "onboard as CEO", "text": text, "depth": 0, "contextId": context_id})
    await client.send_text(text, context_id=context_id, metadata=md)

    # hand over the mission (request -> ... -> inform)
    rmd = meta(Performative.request, role="Board", intent="execute the mission",
               motivation=mission, delegation_depth=0,
               extra={"runId": run_id, "contextId": context_id, "senderId": "Board",
                      "mission": mission, "topology": topology})
    await emit({"type": "message", "from": "Board", "fromRole": "Board", "to": cid,
                "toRole": "CEO", "performative": Performative.request,
                "intent": "execute the mission", "text": mission, "depth": 0,
                "contextId": context_id})
    task = await client.send_text(mission, context_id=context_id, metadata=rmd)
    return result_text(task) or ""
