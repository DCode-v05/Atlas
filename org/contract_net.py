"""
org/contract_net.py — hiring as a FIPA Contract-Net auction.

Instead of grabbing the first free employee, a manager runs a real auction:

    cfp ──────────▶ candidates        "who can be the Design Lead?"
    propose ◀────── each candidate    a bid (a confidence score)
    accept-proposal ▶ the winner      "you're hired"
    refuse ────────▶ the losers       "thanks, not this time"

This is the concrete mechanism behind "agents assign roles to each other": the
role is decided by a negotiation on the wire, not by a central scheduler. HR only
provides the candidate pool (it reserves them so two managers never interview the
same person); the *choice* is the manager's.
"""
from __future__ import annotations

import asyncio
import hashlib

from config import CNP_CANDIDATES
from org.envelope import Performative, meta
from protocol.client import A2AClient, post_json
from protocol.models import result_data


def bid_score(agent_id: str, role: str) -> int:
    """A candidate's deterministic 'fit' for a role (0-99). Stable per (agent,role)
    so auctions reproduce — which the comparison mode relies on."""
    h = hashlib.sha1(f"{agent_id}:{role}".encode("utf-8")).hexdigest()
    return int(h, 16) % 100


async def hire_via_cnp(employee, reporter, role: str, *, run_id: str,
                       context_id: str, child_depth: int) -> dict | None:
    """Run the auction; return the winning {agentId, url} (already reserved) or None."""
    identity = employee.identity
    gw = employee.gateway_url

    # 1) HR reserves a few candidates to interview
    data = await post_json(gw + "/hr/candidates", {"runId": run_id, "k": CNP_CANDIDATES})
    candidates = data.get("candidates", [])
    if not candidates:
        await reporter.cap("headcount", f"No one free to interview for {role}")
        return None

    # 2) cfp -> each candidate bids (propose)
    async def interview(cand: dict) -> tuple[dict, int]:
        await reporter.message(to=cand["agentId"], to_role="candidate",
                               performative=Performative.cfp, intent=f"who can be {role}?",
                               depth=child_depth, context_id=context_id, text=f"CFP: {role}")
        md = meta(Performative.cfp, role=identity.role, intent=f"cfp for {role}",
                  delegation_depth=child_depth,
                  extra={"runId": run_id, "contextId": context_id,
                         "senderId": employee.agent_id, "cfpRole": role})
        task = await A2AClient(cand["url"]).send_text(f"Call for proposals: {role}",
                                                      context_id=context_id, metadata=md)
        bid = result_data(task) or {}
        return cand, int(bid.get("score", 0))

    bids = await asyncio.gather(*[interview(c) for c in candidates])
    bids.sort(key=lambda cb: cb[1], reverse=True)

    # 3) award the winner, refuse + release the losers
    winner, win_score = bids[0]
    await reporter.message(to=winner["agentId"], to_role=role,
                           performative=Performative.accept_proposal,
                           intent=f"award {role} (best bid {win_score})",
                           depth=child_depth, context_id=context_id)
    for cand, score in bids[1:]:
        await reporter.message(to=cand["agentId"], to_role="candidate",
                               performative=Performative.refuse,
                               intent=f"not selected for {role}",
                               depth=child_depth, context_id=context_id)
        await post_json(gw + "/hr/release", {"agentId": cand["agentId"]})

    # 4) the manager records the hire (decentralised — the manager hired them)
    await reporter.emit("hire", agentId=winner["agentId"], role=role,
                        parentId=employee.agent_id, depth=child_depth)
    return winner
