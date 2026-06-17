"""
org/ceo.py — the "board" hires the first employee as CEO and hands over the mission.

This is the only privileged step in the whole system: the Board (the gateway,
on the user's behalf) onboards employee #1 as the CEO and sends it the mission.
From there everything is just agents talking to agents — the CEO decomposes,
hires, delegates, and finally returns the synthesised result.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from org.cognition import lead_title
from org.envelope import Performative, meta
from org.onboarding import offer_message
from protocol.client import A2AClient
from protocol.models import dump, result_text

EmitFn = Callable[[dict], Awaitable[None]]
AllocateFn = Callable[..., dict | None]


async def run_mission(allocate: AllocateFn, emit: EmitFn, *, run_id: str,
                      mission: str, context_id: str,
                      topology: str = "hierarchical") -> str:
    title = await lead_title(mission)            # mission-derived, e.g. "Festival Director"
    lead = await allocate(run_id, title, "Board", 0)
    if not lead:
        await emit({"type": "run", "phase": "error", "message": "No capacity to hire a leader."})
        return ""
    lid, client = lead["agentId"], A2AClient(lead["url"])
    await emit({"type": "hire", "agentId": lid, "role": title, "parentId": "Board", "depth": 0})

    # onboard the leader (propose -> accept)
    text, md = offer_message(role=title, goal=mission, backstory="the accountable leader",
                             scope="the whole mission", depth=0, run_id=run_id,
                             hirer_role="Board", hirer_id="Board", context_id=context_id)
    await emit({"type": "message", "from": "Board", "fromRole": "Board", "to": lid,
                "toRole": title, "performative": Performative.propose,
                "intent": f"onboard as {title}", "text": text, "depth": 0, "contextId": context_id})
    await client.send_text(text, context_id=context_id, metadata=md)
    try:                                  # discover the lead's Agent Card (now reflects the role)
        await emit({"type": "card", "agentId": lid, "role": title, "card": dump(await client.get_card())})
    except Exception:
        pass

    # hand over the mission (request -> ... -> inform)
    rmd = meta(Performative.request, role="Board", intent="execute the mission",
               motivation=mission, delegation_depth=0,
               extra={"runId": run_id, "contextId": context_id, "senderId": "Board",
                      "mission": mission, "topology": topology})
    await emit({"type": "message", "from": "Board", "fromRole": "Board", "to": lid,
                "toRole": title, "performative": Performative.request,
                "intent": "execute the mission", "text": mission, "depth": 0,
                "contextId": context_id})
    task = await client.send_text(mission, context_id=context_id, metadata=rmd)
    return result_text(task) or ""
