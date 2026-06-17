"""
org/metrics.py — coordination-efficiency metrics, derived from telemetry.

These are the numbers the comparison mode puts side-by-side: how much *talking*
a topology needed to coordinate the SAME mission. The gateway feeds every event
through ``apply`` and reads ``snapshot`` for the dashboard.
"""
from __future__ import annotations


class Metrics:
    def __init__(self) -> None:
        self.messages = 0
        self.tokens = 0
        self.max_depth = 0
        self.headcount = 0
        self.by_performative: dict[str, int] = {}
        self.elapsed_ms = 0

    def apply(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "message":
            self.messages += 1
            p = ev.get("performative", "?")
            self.by_performative[p] = self.by_performative.get(p, 0) + 1
            self.max_depth = max(self.max_depth, int(ev.get("depth", 0) or 0))
        elif t == "llm":
            self.tokens += int(ev.get("tokens", 0) or 0)
        elif t == "hire":
            self.headcount += 1

    def set_elapsed(self, ms: int) -> None:
        self.elapsed_ms = int(ms)

    def snapshot(self) -> dict:
        return {"messages": self.messages, "tokens": self.tokens,
                "maxDepth": self.max_depth, "headcount": self.headcount,
                "byPerformative": dict(self.by_performative),
                "elapsedMs": self.elapsed_ms}
