"""Deterministic message templates.

These are the default words agents say. When Groq is enabled on the interactive
path the orchestrator may rephrase these into more natural prose, but the
structural behavior (who says what, and what's shared vs withheld) is identical
with or without an LLM — so the demo is fully meaningful offline.
"""

from __future__ import annotations


def request_text(requester_name: str, owner_name: str, item_title: str, motivation: str) -> str:
    return f"Hi {owner_name}, {requester_name} here. {motivation} Could you share '{item_title}'?"


def share_reply(item_title: str, body: str) -> str:
    return f"Sure — here's '{item_title}': {body}"


def redact_reply(item_title: str, summary: str) -> str:
    return f"I can't share the full '{item_title}', but here's the safe version: {summary}"


def deny_reply(item_title: str) -> str:
    return (
        f"Sorry, I can't share '{item_title}' — it's outside what you need for this, "
        f"so I'll keep it withheld."
    )


def escalate_notice(item_title: str) -> str:
    return f"'{item_title}' is sensitive, so I've asked the operator to approve before I share anything."


def hitl_approved_reply(item_title: str, body: str) -> str:
    return f"Operator approved — here's '{item_title}': {body}"


def hitl_approved_redact_reply(item_title: str, summary: str) -> str:
    return f"Operator approved a partial share of '{item_title}': {summary}"


def hitl_denied_reply(item_title: str) -> str:
    return f"The operator declined to release '{item_title}', so I can't share it."


def final_summary(agent_name: str, prompt: str, shared: int, redacted: int, denied: int, hitl: int) -> str:
    bits = []
    if shared:
        bits.append(f"{shared} shared")
    if redacted:
        bits.append(f"{redacted} redacted")
    if denied:
        bits.append(f"{denied} withheld")
    if hitl:
        bits.append(f"{hitl} sent for approval")
    detail = ", ".join(bits) if bits else "no sensitive context was needed"
    return (
        f"{agent_name}: I've gathered what I can for \"{prompt}\" — context sources contacted "
        f"({detail}). Proceeding with what was shared."
    )


def no_context_needed(agent_name: str, prompt: str) -> str:
    return f"{agent_name}: \"{prompt}\" is within my own remit — no extra context needed from others."


def group_opening(initiator_name: str, topic: str) -> str:
    return f"{initiator_name}: team, let's coordinate on {topic}. What's everyone's status and anything to flag?"


def group_reply(member_name: str, topic: str) -> str:
    return f"{member_name}: on it for {topic} — here's where I'm at, will sync details in-thread."


def manager_consult(requester_name: str, manager_name: str, topic: str) -> str:
    return f"Hi {manager_name}, {requester_name} here — checking in on {topic}; any guidance or context I should have?"
