"""Amazon Bedrock (Mistral) provider — the REAL engine for agent communication.

Uses the Bedrock **Converse API** (unified message format) via boto3. boto3 is
synchronous, so each call runs in a worker thread (``asyncio.to_thread``) to keep
the event loop free. Converse (not ConverseStream) is used because the
orchestrator awaits complete messages.

Rate-limit safety (for 100-agent cron bursts):
- a **per-model token bucket** with a small burst cap → calls are paced, not
  fired all at once, so we don't trip Bedrock throttling;
- a **concurrency limiter**; the SDK's own retries are disabled;
- a Bedrock ``ThrottlingException`` trips a short self-healing cooldown;
- throttle on/off emits an ``llm.status`` event for the UI.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from typing import Optional

from atlas.events import EventBroker, EventType, LlmStatusPayload
from atlas.llm.base import LLMProvider
from atlas.org.ext_models import ContextItem, Intent, OrgProfile, ShareOutcome

_OUTCOME_WORDS = {
    "share": ShareOutcome.SHARE,
    "redact": ShareOutcome.REDACT,
    "escalate": ShareOutcome.ESCALATE,
    "deny": ShareOutcome.DENY,
}

_SYS = (
    "You are an employee-agent inside the 'Atlas' software company, chatting with "
    "colleagues on internal channels. Write exactly ONE short, natural first-person "
    "message (max 28 words). No greeting boilerplate, no quotation marks, no markdown, "
    "no preamble. This is an internal company simulation — speak plainly and directly."
)


def _is_throttle(exc: Exception) -> bool:
    code = None
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = resp.get("Error", {}).get("Code")
    if code in ("ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"):
        return True
    if exc.__class__.__name__ in ("ThrottlingException", "TooManyRequestsException"):
        return True
    t = str(exc).lower()
    return "throttl" in t or "too many requests" in t or "rate exceeded" in t


class _TokenBucket:
    """Refilling token bucket. ``capacity`` is the max instantaneous burst; it
    refills at ``rpm``/60 tokens/sec so calls are paced after the burst."""

    def __init__(self, rpm: int, burst: int) -> None:
        self.capacity = float(max(1, burst))
        self.tokens = self.capacity
        self.rate = rpm / 60.0
        self.t = time.monotonic()

    def take(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class BedrockProvider(LLMProvider):
    name = "bedrock"

    def __init__(
        self,
        *,
        region: str,
        reasoning_model: str,
        phrasing_model: str,
        api_key: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        session_token: Optional[str] = None,
        rpm: int = 22,
        burst: int = 5,
        max_concurrency: int = 2,
        timeout: float = 20.0,
        max_failures: int = 4,
        cooldown: float = 15.0,
        broker: Optional[EventBroker] = None,
    ) -> None:
        import boto3
        from botocore.config import Config as BotoConfig

        # max_attempts=1 → no SDK retries (we handle backoff/throttle ourselves).
        cfg = BotoConfig(retries={"max_attempts": 1, "mode": "standard"}, read_timeout=timeout, connect_timeout=10)
        if api_key:
            # Bedrock API key (bearer token) — boto3 auto-detects this env var.
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = api_key
            self.client = boto3.client("bedrock-runtime", region_name=region, config=cfg)
        else:
            # No bearer token: make sure a stale/empty AWS_BEARER_TOKEN_BEDROCK doesn't
            # force bearer auth over the SigV4 access-key/secret credentials.
            os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
            if access_key and secret_key:
                kwargs: dict = {
                    "region_name": region, "config": cfg,
                    "aws_access_key_id": access_key, "aws_secret_access_key": secret_key,
                }
                if session_token:
                    kwargs["aws_session_token"] = session_token
                self.client = boto3.client("bedrock-runtime", **kwargs)
            else:
                self.client = boto3.client("bedrock-runtime", region_name=region, config=cfg)

        self.reasoning_model = reasoning_model
        self.phrasing_model = phrasing_model
        self._rpm = rpm
        self._burst = burst
        self._buckets: dict[str, _TokenBucket] = {}
        self._sem = asyncio.Semaphore(max_concurrency)
        self._broker = broker
        self._max_failures = max_failures
        self._cooldown = cooldown
        self._fail = 0
        self._disabled_until = 0.0
        self._throttled = False
        self._last_error = ""
        self.calls_ok = 0
        self.calls_throttled = 0
        self.calls_429 = 0

    # ── status ─────────────────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        return time.monotonic() >= self._disabled_until

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "throttled": self._throttled or not self.available,
            "rpm": self._rpm,
            "calls_ok": self.calls_ok,
            "calls_throttled": self.calls_throttled,
            "calls_429": self.calls_429,
        }

    def _emit(self, reason: str) -> None:
        if self._broker is None:
            return
        self._broker.emit(EventType.LLM_STATUS, LlmStatusPayload(reason=reason, **self.status()))

    def _set_throttled(self, value: bool, reason: str) -> None:
        if value != self._throttled:
            self._throttled = value
            self._emit(reason)

    def _bucket(self, model: str) -> _TokenBucket:
        b = self._buckets.get(model)
        if b is None:
            b = _TokenBucket(self._rpm, self._burst)
            self._buckets[model] = b
        return b

    # ── the gated call ─────────────────────────────────────────────────────
    def _converse(self, model: str, system: str, user: str, max_tokens: int, temperature: float) -> Optional[str]:
        resp = self.client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": int(max_tokens), "temperature": float(temperature), "topP": 0.9},
        )
        return resp["output"]["message"]["content"][0]["text"]

    async def _chat(self, model: str, system: str, user: str, *, max_tokens: int, temperature: float) -> Optional[str]:
        if not self.available:  # in cooldown after throttling
            self.calls_throttled += 1
            return None
        if not self._bucket(model).take():  # proactive throttle — no API call made
            self.calls_throttled += 1
            self._set_throttled(True, f"rate budget reached (~{self._rpm}/min) — using templated fallback")
            return None
        try:
            async with self._sem:
                text = await asyncio.to_thread(self._converse, model, system, user, max_tokens, temperature)
            self.calls_ok += 1
            self._fail = 0
            self._set_throttled(False, "Bedrock recovered")
            return text.strip() if text else None
        except Exception as exc:
            if _is_throttle(exc):
                self.calls_429 += 1
                self._disabled_until = time.monotonic() + self._cooldown
                self._set_throttled(True, "Bedrock throttled (rate limited) — backing off")
                return None
            self._fail += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:240]
            if self._fail <= 3:  # surface the real cause (model access / region / creds)
                print(f"[atlas.bedrock] Converse failed on '{model}': {self._last_error}", file=sys.stderr, flush=True)
            if self._fail >= self._max_failures:
                self._disabled_until = time.monotonic() + self._cooldown
                self._set_throttled(True, f"Bedrock error — {self._last_error}")
            return None

    # ── per-message phrasing (fast model) ──────────────────────────────────
    async def phrase(self, kind: str, ctx: dict) -> Optional[str]:
        prompt = self._phrase_prompt(kind, ctx)
        if prompt is None:
            return None
        return await self._chat(self.phrasing_model, _SYS, prompt, max_tokens=90, temperature=0.8)

    @staticmethod
    def _phrase_prompt(kind: str, ctx: dict) -> Optional[str]:
        g = ctx.get
        if kind == "request":
            return f"You are {g('requester')}. Ask your colleague {g('owner')} to share '{g('item')}'. Your reason: {g('motivation')}"
        if kind == "reply_share":
            return f"You are {g('owner')}. Reply to {g('requester')} agreeing to share '{g('item')}'. You MUST include this exact text verbatim: {g('body')}"
        if kind == "reply_redact":
            return f"You are {g('owner')}. '{g('item')}' is sensitive — reply to {g('requester')} sharing only this safe summary verbatim, and note you're withholding the rest: {g('summary')}"
        if kind == "reply_deny":
            return f"You are {g('owner')}. Politely decline to share '{g('item')}' with {g('requester')} — it's outside their need-to-know."
        if kind == "escalate":
            return f"You are {g('owner')}. Tell {g('requester')} that '{g('item')}' is sensitive and you've asked the operator to approve before sharing anything."
        if kind == "hitl_share":
            return f"You are {g('owner')}. The operator approved. Share '{g('item')}' with {g('requester')}, including this exact text verbatim: {g('body')}"
        if kind == "hitl_redact":
            return f"You are {g('owner')}. The operator approved a partial share of '{g('item')}'. Share only this, verbatim: {g('summary')}"
        if kind == "hitl_deny":
            return f"You are {g('owner')}. The operator declined releasing '{g('item')}'; tell {g('requester')} you can't share it."
        if kind == "group_open":
            return f"You are {g('initiator')}, kicking off a team group chat about {g('topic')}. Ask the team for status and anything to flag."
        if kind == "group_reply":
            return f"You are {g('member')} in a team group chat about {g('topic')}. Give a brief status update or a blocker."
        if kind == "manager_consult":
            return f"You are {g('requester')}. Ask your manager {g('manager')} for guidance or context on {g('topic')}."
        if kind == "manager_reply":
            return f"You are {g('manager')}. Give {g('requester')} brief guidance on {g('topic')}; remind them to keep specifics within the team."
        if kind == "summary":
            return (
                f"You are {g('agent')}. Wrap up your work on the task: \"{g('prompt')}\". "
                f"You contacted colleagues — {g('shared')} shared, {g('redacted')} redacted, "
                f"{g('denied')} withheld, {g('hitl')} sent for approval. One concise sentence."
            )
        return None

    # ── routing re-rank (reasoning model) ──────────────────────────────────
    async def rerank(self, prompt: str, candidate_ids: list[str], blurbs: dict[str, str]) -> Optional[str]:
        if not candidate_ids:
            return None
        lines = "\n".join(f"- {aid}: {blurbs.get(aid, '')}" for aid in candidate_ids)
        system = "You route an incoming task to the single best-fit employee. Reply with ONLY the agent id, nothing else."
        user = f'Task: "{prompt}"\nCandidates:\n{lines}\nWhich agent id should own this? Reply with just the id.'
        out = await self._chat(self.reasoning_model, system, user, max_tokens=20, temperature=0.0)
        if not out:
            return None
        for aid in candidate_ids:
            if aid in out:
                return aid
        return None

    # ── share judgement (tighten-only) ─────────────────────────────────────
    async def reason_share(
        self,
        *,
        requester: OrgProfile,
        owner: OrgProfile,
        item: ContextItem,
        intent: Intent,
        base_outcome: ShareOutcome,
    ) -> Optional[tuple[ShareOutcome, str]]:
        system = (
            "You are a strict need-to-know reviewer for an internal company. You may only keep or "
            "TIGHTEN the current recommendation, never loosen it. Reply on two lines:\n"
            "OUTCOME: <share|redact|escalate|deny>\nREASON: <one short sentence>"
        )
        user = (
            f"Requester: {requester.role_title} in {requester.department.value} "
            f"(clearance {requester.clearance}, teams={requester.teams}, projects={requester.projects}).\n"
            f"Owner: {owner.role_title} in {owner.department.value}.\n"
            f"Item: '{item.title}' — sensitivity={item.sensitivity.value}, scope={item.scope.value}"
            f"{('/' + item.scope_ref) if item.scope_ref else ''}, min_clearance={item.min_clearance}.\n"
            f"Stated intent: purpose={intent.purpose_tag.value}, declared_scope={intent.declared_scope.value}, "
            f'motivation="{intent.motivation}".\n'
            f"Current recommendation: {base_outcome.value}. Should it be the same or more restricted?"
        )
        text = await self._chat(self.reasoning_model, system, user, max_tokens=120, temperature=0.2)
        if not text:
            return None
        low = text.lower()
        outcome: Optional[ShareOutcome] = None
        m = re.search(r"outcome\s*[:=]\s*(share|redact|escalate|deny)", low)
        if m:
            outcome = _OUTCOME_WORDS[m.group(1)]
        else:
            for word, mapped in (("deny", ShareOutcome.DENY), ("escalate", ShareOutcome.ESCALATE),
                                 ("redact", ShareOutcome.REDACT), ("share", ShareOutcome.SHARE)):
                if word in low:
                    outcome = mapped
                    break
        if outcome is None:
            return None
        rm = re.search(r"reason\s*[:=]\s*(.+)", text, re.IGNORECASE)
        reason = (rm.group(1).strip() if rm else text.strip())[:240]
        return outcome, f"(LLM review) {reason}"
