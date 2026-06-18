"""Deterministic message templates.

These are the default words agents say. When the LLM is enabled the orchestrator
rephrases them into more natural prose; these are the safety-net fallback used
when a live call is paced/throttled. To keep that fallback from reading like
obvious boilerplate, each kind has several phrasings and one is chosen by a
**stable hash of the message's participants/topic** — so it varies from message
to message yet stays fully reproducible for a given seed/run.
"""

from __future__ import annotations

import zlib


def _pick(variants: list[str], *keys: str) -> str:
    """Deterministically select a variant from a stable hash of ``keys``."""
    seed = "".join(k for k in keys if k)
    return variants[zlib.crc32(seed.encode("utf-8")) % len(variants)]


def request_text(requester_name: str, owner_name: str, item_title: str, motivation: str) -> str:
    return _pick(
        [
            f"Hi {owner_name}, {requester_name} here. {motivation} Could you share '{item_title}'?",
            f"{owner_name} — quick one from {requester_name}. {motivation} Would you be able to pass me '{item_title}'?",
            f"Hey {owner_name}, it's {requester_name}. {motivation} Do you have '{item_title}' I could use?",
            f"{requester_name} here, {owner_name}. {motivation} Mind sharing '{item_title}' with me?",
            f"Hi {owner_name} — {motivation} {requester_name} would appreciate access to '{item_title}' if that's alright.",
        ],
        requester_name, owner_name, item_title,
    )


def share_reply(item_title: str, body: str) -> str:
    return _pick(
        [
            f"Sure — here's '{item_title}': {body}",
            f"Happy to help. '{item_title}': {body}",
            f"No problem, sending '{item_title}' over — {body}",
            f"Here you go, '{item_title}': {body}",
        ],
        item_title, body,
    )


def redact_reply(item_title: str, summary: str) -> str:
    return _pick(
        [
            f"I can't share the full '{item_title}', but here's the safe version: {summary}",
            f"I'll keep the sensitive parts of '{item_title}' back, but this much is fine to share: {summary}",
            f"Most of '{item_title}' is need-to-know — here's what I can pass along: {summary}",
            f"Only a redacted view of '{item_title}' for now: {summary}",
        ],
        item_title, summary,
    )


def deny_reply(item_title: str) -> str:
    return _pick(
        [
            f"Sorry, I can't share '{item_title}' — it's outside what you need for this, so I'll keep it withheld.",
            f"I'll have to withhold '{item_title}' — it isn't within your need-to-know here.",
            f"Can't pass '{item_title}' along on this one; it's outside scope for the request.",
            f"'{item_title}' stays withheld — not something I can release for this purpose.",
        ],
        item_title,
    )


def escalate_notice(item_title: str) -> str:
    return _pick(
        [
            f"'{item_title}' is sensitive, so I've asked the operator to approve before I share anything.",
            f"Because '{item_title}' is sensitive, I've routed it to the operator for sign-off first.",
            f"I've escalated '{item_title}' to the operator — I need approval before releasing it.",
        ],
        item_title,
    )


def hitl_approved_reply(item_title: str, body: str) -> str:
    return _pick(
        [
            f"Operator approved — here's '{item_title}': {body}",
            f"Got the go-ahead from the operator. '{item_title}': {body}",
            f"Approved — sharing '{item_title}' now: {body}",
        ],
        item_title, body,
    )


def hitl_approved_redact_reply(item_title: str, summary: str) -> str:
    return _pick(
        [
            f"Operator approved a partial share of '{item_title}': {summary}",
            f"Operator signed off on a redacted share of '{item_title}': {summary}",
            f"Cleared for a partial release of '{item_title}': {summary}",
        ],
        item_title, summary,
    )


def hitl_denied_reply(item_title: str) -> str:
    return _pick(
        [
            f"The operator declined to release '{item_title}', so I can't share it.",
            f"Operator said no on '{item_title}' — it stays withheld.",
            f"That one's blocked — the operator declined releasing '{item_title}'.",
        ],
        item_title,
    )


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
    return _pick(
        [
            f"{agent_name}: I've gathered what I can for \"{prompt}\" — context sources contacted ({detail}). Proceeding with what was shared.",
            f"{agent_name}: done sourcing for \"{prompt}\" ({detail}). Moving ahead with what I have.",
            f"{agent_name}: wrapped up \"{prompt}\" — {detail}. Proceeding on that basis.",
        ],
        agent_name, prompt,
    )


def no_context_needed(agent_name: str, prompt: str) -> str:
    return _pick(
        [
            f"{agent_name}: \"{prompt}\" is within my own remit — no extra context needed from others.",
            f"{agent_name}: I can handle \"{prompt}\" myself — nothing to source from the team.",
            f"{agent_name}: \"{prompt}\" sits inside my own scope; no need to pull context from anyone.",
        ],
        agent_name, prompt,
    )


def group_opening(initiator_name: str, topic: str) -> str:
    return _pick(
        [
            f"{initiator_name}: team, let's coordinate on {topic}. What's everyone's status and anything to flag?",
            f"{initiator_name}: kicking off {topic} — where is everyone, and any blockers?",
            f"{initiator_name}: team sync on {topic}. Share status and call out risks.",
            f"{initiator_name}: let's align on {topic}. Quick round — status plus anything blocking?",
        ],
        initiator_name, topic,
    )


def group_reply(member_name: str, topic: str) -> str:
    return _pick(
        [
            f"{member_name}: on it for {topic} — here's where I'm at, will sync details in-thread.",
            f"{member_name}: making progress on {topic}; one item to flag, will follow up.",
            f"{member_name}: {topic} is on track from my side — no blockers right now.",
            f"{member_name}: handling my part of {topic}; could use a quick input from the team.",
        ],
        member_name, topic,
    )


def manager_consult(requester_name: str, manager_name: str, topic: str) -> str:
    return _pick(
        [
            f"Hi {manager_name}, {requester_name} here — checking in on {topic}; any guidance or context I should have?",
            f"{manager_name} — {requester_name} here. Could you steer me on {topic}?",
            f"Hey {manager_name}, quick guidance on {topic}? {requester_name} wants to make sure I'm aligned.",
        ],
        requester_name, manager_name, topic,
    )
