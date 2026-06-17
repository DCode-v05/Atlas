"""
org/meeting.py — a group meeting, layered on top of A2A.

A2A is natively 1:1 (one client talks to one agent). A "meeting" is therefore an
EXTENSION we build on top — NOT part of the protocol: a coordinator owns one
shared ``contextId`` (the meeting room), gives each participant the floor in turn
(speaker selection), and shows every speaker what was said before. Because all
the turns share the meeting's contextId, the UI can group them into one room and
you can see a genuine multi-party conversation emerge from 1:1 A2A calls.
"""
from __future__ import annotations

from config import MEETING_MAX_PARTICIPANTS
from org.envelope import Performative, meta
from protocol.client import A2AClient
from protocol.models import result_text


async def run_meeting(employee, reporter, hired, *, run_id: str, mission: str,
                      child_depth: int) -> list[tuple[str, str]]:
    """Round-robin meeting: each report speaks once, seeing the prior transcript."""
    meet_ctx = f"meet-{run_id}-{employee.agent_id}"
    parts = [{"agentId": w["agentId"], "url": w["url"], "role": s["title"]}
             for s, w in hired][:MEETING_MAX_PARTICIPANTS]
    await reporter.emit("meeting", phase="open", meetingId=meet_ctx,
                        chair=employee.agent_id, participants=[p["role"] for p in parts],
                        topic=mission)

    transcript: list[tuple[str, str]] = []
    n = len(parts)
    for i, p in enumerate(parts):         # round-robin floor; each speaker consults a peer
        target = parts[(i + 1) % n] if n > 1 else None
        prior = "\n".join(f"- {r}: {t[:80]}" for r, t in transcript) or "(you have the floor first)"
        peer_note = f" After hearing from the {target['role']}," if target else ""
        prompt = (f"Meeting about '{mission}'. So far:\n{prior}\n\n"
                  f"As {p['role']},{peer_note} add your view.")
        md = meta(Performative.request, role=employee.identity.role, intent="share in meeting",
                  delegation_depth=child_depth,
                  extra={"runId": run_id, "contextId": meet_ctx, "senderId": employee.agent_id,
                         "mission": mission, "meeting": True, "topology": "group",
                         "consultTarget": target, "roster": [pp["role"] for pp in parts]})
        await reporter.message(to=p["agentId"], to_role=p["role"],
                               performative=Performative.request, intent=f"floor to {p['role']}",
                               depth=child_depth, context_id=meet_ctx,
                               text=f"(meeting) {p['role']}, your view?")
        task = await A2AClient(p["url"]).send_text(prompt, context_id=meet_ctx, metadata=md)
        transcript.append((p["role"], result_text(task) or ""))

    await reporter.emit("meeting", phase="close", meetingId=meet_ctx)
    return transcript
