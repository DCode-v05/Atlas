"""
org/envelope.py — the ATLAS org extension that rides on top of A2A.

Core A2A has no notion of a *performative* ("is this a request or an answer?"),
a sender *role* ("VP Engineering"), or the *intent* / *motivation* behind a
message. Those are exactly what this project is about, so we carry them as a
namespaced object placed under ``message.metadata[ORG_EXT_URI]``.

This is the A2A-blessed way to extend messages: a plain A2A client that doesn't
understand the extension simply ignores the extra metadata and the message is
still valid. Everything organisation-specific is therefore *visibly* layered on
top of the protocol, never baked into it.
"""
from __future__ import annotations

from typing import Optional

from config import ORG_EXT_URI


class Performative:
    """The FIPA ACL communicative acts we use (a curated subset).

    The performative is the *speech act* — it tells the receiver what kind of
    message this is, independent of its text. It's the backbone of legible
    agent-to-agent communication.
    """
    request = "request"                  # please perform an action
    inform = "inform"                    # here is a result / a fact
    propose = "propose"                  # I offer to do X (role onboarding + CNP bids)
    cfp = "cfp"                          # call-for-proposal: who can do X?
    accept_proposal = "accept-proposal"  # I take your proposal
    refuse = "refuse"                    # I decline
    agree = "agree"                      # I commit to your request
    query_ref = "query-ref"              # what is X?
    failure = "failure"                  # the action failed

    ALL = {request, inform, propose, cfp, accept_proposal, refuse, agree,
           query_ref, failure}


def make_envelope(performative: str, *, role: Optional[str] = None,
                  intent: Optional[str] = None, motivation: Optional[str] = None,
                  beliefs: Optional[list[str]] = None, delegation_depth: int = 0,
                  scope: Optional[str] = None, extra: Optional[dict] = None) -> dict:
    """Build the org envelope. ``performative`` is required; the rest describe
    *who* is speaking and *why* (the role / intention / motivation layer)."""
    env: dict = {"performative": performative, "delegationDepth": delegation_depth}
    if role is not None:
        env["role"] = role
    if intent is not None:
        env["intent"] = intent
    if motivation is not None:
        env["motivation"] = motivation
    if beliefs:
        env["beliefs"] = list(beliefs)
    if scope is not None:
        env["scope"] = scope
    if extra:
        env.update(extra)
    return env


def wrap(envelope: dict, base: Optional[dict] = None) -> dict:
    """Return a ``message.metadata`` dict carrying the envelope under ORG_EXT_URI."""
    md = dict(base or {})
    md[ORG_EXT_URI] = envelope
    return md


def meta(performative: str, **kw) -> dict:
    """Convenience: build an envelope and wrap it into a metadata dict in one go."""
    return wrap(make_envelope(performative, **kw))


def read(metadata_or_message: Optional[dict]) -> Optional[dict]:
    """Pull the org envelope out of either a full message dict or a metadata dict."""
    if not isinstance(metadata_or_message, dict):
        return None
    md = metadata_or_message
    if isinstance(md.get("metadata"), dict):     # a full message was passed
        md = md["metadata"]
    env = md.get(ORG_EXT_URI)
    return env if isinstance(env, dict) else None


def performative_of(message_or_meta: Optional[dict]) -> Optional[str]:
    env = read(message_or_meta)
    return env.get("performative") if env else None


def role_of(message_or_meta: Optional[dict]) -> Optional[str]:
    env = read(message_or_meta)
    return env.get("role") if env else None
