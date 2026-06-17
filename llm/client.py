"""
llm/client.py — the language-model layer.

Two modes, chosen automatically:
  * REAL  — Groq, when GROQ_API_KEY is set and ATLAS_FORCE_MOCK != 1.
  * MOCK  — a DETERMINISTIC offline stand-in (no key needed). Determinism is a
            feature, not a fallback: the comparison mode replays the SAME mission
            under different topologies, so the org's reasoning must be identical
            run-to-run for the metric deltas to mean anything.

The org-level reasoning (decompose / do_work / synthesize) lives in
``org/cognition.py``; this module only exposes ``complete()`` plus a couple of
deterministic helpers it can lean on when offline.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
_FORCE_MOCK = os.getenv("ATLAS_FORCE_MOCK", "0") == "1"
_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
_OVERRIDE_MOCK = False

_client = None


def set_force_mock(on: bool) -> None:
    """Force the deterministic mock regardless of any key. The comparison mode
    flips this on so the three topology runs reason identically and the metric
    deltas are attributable to communication pattern, not to LLM variance."""
    global _OVERRIDE_MOCK
    _OVERRIDE_MOCK = on


def using_real_llm() -> bool:
    return bool(_API_KEY) and not _FORCE_MOCK and not _OVERRIDE_MOCK


def model_name() -> str:
    return _MODEL if using_real_llm() else "deterministic-mock"


@dataclass
class LLMResult:
    text: str
    tokens: int


def _groq():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=_API_KEY)
    return _client


def est_tokens(*chunks: str) -> int:
    """Rough token estimate (~4 chars/token) used to meter the mock + budget."""
    return max(1, sum(len(c or "") for c in chunks) // 4)


async def complete(system: str, user: str, *, temperature: float = 0.3,
                   max_tokens: int = 900) -> LLMResult:
    """One LLM turn. Returns the text and a token count (real usage or estimate)."""
    if using_real_llm():
        def call() -> LLMResult:
            resp = _groq().chat.completions.create(
                model=_MODEL, temperature=temperature, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}])
            txt = (resp.choices[0].message.content or "").strip()
            usage = getattr(resp, "usage", None)
            tok = getattr(usage, "total_tokens", 0) or est_tokens(system, user, txt)
            return LLMResult(txt, int(tok))
        return await asyncio.to_thread(call)
    txt = _mock(system, user)
    return LLMResult(txt, est_tokens(system, user, txt))


def _mock(system: str, user: str) -> str:
    """A deterministic, content-free stand-in. The org cognition layer rarely
    calls this directly (it has its own deterministic templates offline); it's
    here so any stray ``complete()`` call still returns stable text."""
    digest = hashlib.sha1((system + "\x1f" + user).encode("utf-8")).hexdigest()[:8]
    head = user.strip().splitlines()[0][:120] if user.strip() else "(empty)"
    return f"[mock:{digest}] {head}"
