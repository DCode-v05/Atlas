"""
llm/client.py — the language-model layer (Groq). REAL LLM ONLY.

There is no offline mock: every reasoning step calls Groq. A GROQ_API_KEY is
therefore required (set it in .env). Without one, calls raise a clear error.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
_client = None


def using_real_llm() -> bool:
    """True when a Groq key is configured (the system needs one to run)."""
    return bool(_API_KEY)


def model_name() -> str:
    return _MODEL if _API_KEY else "no-key"


@dataclass
class LLMResult:
    text: str
    tokens: int


def est_tokens(*chunks: str) -> int:
    """Rough token estimate (~4 chars/token), used only if Groq omits usage."""
    return max(1, sum(len(c or "") for c in chunks) // 4)


def _groq():
    global _client
    if _client is None:
        if not _API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is required — this build uses a real LLM only (no mock). "
                "Add GROQ_API_KEY to your .env (see .env.example).")
        from groq import Groq
        _client = Groq(api_key=_API_KEY)
    return _client


async def complete(system: str, user: str, *, temperature: float = 0.3,
                   max_tokens: int = 900) -> LLMResult:
    """One LLM turn against Groq. Returns the text and a token count."""
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
