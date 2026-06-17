"""
org/meeting.py — a multi-round round-table, layered on top of A2A.

A2A is natively 1:1 (one client talks to one agent). A "meeting" is therefore an
EXTENSION we build on top — NOT part of the protocol: a coordinator owns one
shared ``contextId`` (the meeting room) and gives each participant the floor.

Unlike a single round-robin, this runs SEVERAL rounds: the team goes back and
forth — raising concerns, countering, proposing, and finally converging — each
speaker seeing the full transcript so far and refining the plan a little more
each pass. Every spoken turn is emitted as a ``say`` event so the UI can render
the conversation as a dedicated round-table, and the transcript feeds synthesis.
"""
from __future__ import annotations

from config import MEETING_MAX_PARTICIPANTS, MEETING_ROUNDS
from org.envelope import Performative, meta
from protocol.client import A2AClient
from protocol.models import result_text

# Human first names so each role gets a person (keeps the round-table readable).
_PERSONA_NAMES = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vikram", "Sara"]


def _performative_for(round_idx: int, total: int, pos: int) -> str:
    """Shape the speech act so the discussion has an arc: open with concerns/facts,
    debate in the middle, converge at the end."""
    if round_idx >= total:
        return "agree"                       # final pass: lock it in
    if round_idx == 1:
        return "concern" if pos == 0 else "inform"
    return "propose" if pos % 2 == 0 else "counter"


async def run_meeting(employee, reporter, hired, *, run_id: str, mission: str,
                      child_depth: int) -> list[tuple[str, str]]:
    """Multi-round meeting: each report speaks once PER ROUND, seeing the prior
    transcript, until the plan is refined. Returns (persona·role, line) turns."""
    meet_ctx = f"meet-{run_id}-{employee.agent_id}"
    parts = [{"agentId": w["agentId"], "url": w["url"], "role": s["title"]}
             for s, w in hired][:MEETING_MAX_PARTICIPANTS]
    for i, p in enumerate(parts):
        p["persona"] = _PERSONA_NAMES[i % len(_PERSONA_NAMES)]

    rounds = max(1, MEETING_ROUNDS)
    await reporter.emit("meeting", phase="open", meetingId=meet_ctx,
                        chair=employee.agent_id,
                        participants=[f"{p['persona']} · {p['role']}" for p in parts],
                        rounds=rounds, topic=mission)

    transcript: list[tuple[str, str]] = []      # (label, text) for synthesis
    for rnd in range(1, rounds + 1):
        await reporter.emit("round", meetingId=meet_ctx, round=rnd, of=rounds)
        for pos, p in enumerate(parts):
            perf = _performative_for(rnd, rounds, pos)
            prior = "\n".join(f"{lbl}: {txt[:160]}" for lbl, txt in transcript) \
                or "(you open the round-table)"
            md = meta(Performative.request, role=employee.identity.role,
                      intent=f"round {rnd}: {perf} from {p['role']}",
                      delegation_depth=child_depth,
                      extra={"runId": run_id, "contextId": meet_ctx,
                             "senderId": employee.agent_id, "mission": mission,
                             "meeting": True, "topology": "group",
                             "persona": p["persona"], "turnPerformative": perf, "round": rnd})
            await reporter.message(to=p["agentId"], to_role=p["role"],
                                   performative=Performative.request,
                                   intent=f"round {rnd} · floor to {p['persona']}",
                                   depth=child_depth, context_id=meet_ctx,
                                   text=f"(round {rnd}) {p['persona']}, your {perf}?")
            task = await A2AClient(p["url"]).send_text(prior, context_id=meet_ctx, metadata=md)
            line = result_text(task) or ""
            label = f"{p['persona']} · {p['role']}"
            transcript.append((label, line))
            await reporter.emit("say", meetingId=meet_ctx, round=rnd, speakerId=p["agentId"],
                                role=p["role"], persona=p["persona"], performative=perf, text=line)

    # Final pass: after the back-and-forth, each specialist states their CONCLUSION
    # — a concise final takeaway for their part, reflecting what the team agreed.
    full = "\n".join(f"{lbl}: {txt[:160]}" for lbl, txt in transcript) or "(no discussion)"
    for p in parts:
        md = meta(Performative.inform, role=employee.identity.role,
                  intent=f"final summary from {p['role']}", delegation_depth=child_depth,
                  extra={"runId": run_id, "contextId": meet_ctx, "senderId": employee.agent_id,
                         "mission": mission, "meeting": True, "topology": "group",
                         "persona": p["persona"], "turnPerformative": "conclude", "round": "final"})
        await reporter.message(to=p["agentId"], to_role=p["role"],
                               performative=Performative.inform,
                               intent=f"final takeaway · {p['persona']}",
                               depth=child_depth, context_id=meet_ctx,
                               text=f"(conclusion) {p['persona']}, your final takeaway?")
        task = await A2AClient(p["url"]).send_text(full, context_id=meet_ctx, metadata=md)
        line = result_text(task) or ""
        transcript.append((f"{p['persona']} · {p['role']} (final)", line))
        await reporter.emit("summary", meetingId=meet_ctx, speakerId=p["agentId"],
                            role=p["role"], persona=p["persona"], text=line)

    await reporter.emit("meeting", phase="close", meetingId=meet_ctx)
    return transcript
