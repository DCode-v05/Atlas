"""
cli.py — run a trip plan from the terminal (no browser needed).
===============================================================

This is a headless A2A client: it drives the same orchestrator the web UI uses
and prints every agent-to-agent step as it happens. The 3 specialist agents
must be running first (use `python launch.py`, or start them individually).

    python cli.py "Plan a 4-day art and food trip to Florence"
"""
from __future__ import annotations

import asyncio
import sys

try:  # make Unicode (arrows, bullets) print correctly on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule

from common.llm import model_name, using_real_llm
from orchestrator.orchestrator import plan_trip

console = Console()

COLORS = {"destination": "cyan", "itinerary": "yellow", "budget": "red",
          "weather": "magenta", "host": "gold1"}


async def run(request: str) -> None:
    mode = f"Groq · {model_name()}" if using_real_llm() else "offline mock"
    console.print(Panel.fit(f"[bold]ATLAS[/] · A2A Trip Concierge\nLLM: {mode}",
                            border_style="gold1"))
    console.print(f"[dim]Request:[/] {request}\n")

    async def emit(ev: dict) -> None:
        t = ev["type"]
        if t == "parsed":
            p = ev["parsed"]
            console.print(f"[gold1]host[/] parsed -> [b]{p['destination']}[/], "
                          f"{p['days']} days, {', '.join(p['interests'])}, {p['travelStyle']}")
        elif t == "discovered":
            names = ", ".join(a["card"]["name"] for a in ev["agents"])
            console.print(f"[gold1]host[/] discovered agents via Agent Cards: {names}")
            console.print(Rule(style="grey30"))
        elif t == "delegate":
            c = COLORS.get(ev["agent"], "white")
            console.print(f"[{c}]-> {ev['agentName']}[/]  [dim]message/stream[/]  \"{ev['request']}\"")
        elif t == "a2a_event":
            e = ev["event"]
            c = COLORS.get(ev["agent"], "white")
            if e["kind"] == "status-update":
                note = ""
                if e["status"].get("message"):
                    note = " · " + " ".join(p["text"] for p in e["status"]["message"]["parts"])
                final = " (final)" if e.get("final") else ""
                console.print(f"   [{c}]{ev['agent']}[/] [dim]status-update[/] "
                              f"state={e['status']['state']}{final}{note}")
            elif e["kind"] == "artifact-update":
                n = len(e["artifact"]["parts"][0]["text"])
                console.print(f"   [{c}]{ev['agent']}[/] [dim]artifact-update[/] {n} chars")
        elif t == "agent_error":
            console.print(f"   [red]{ev['agent']} error: {ev['message']}[/]")
        elif t == "synthesis_start":
            console.print(Rule(style="grey30"))
            console.print("[gold1]host[/] synthesizing final plan...")
        elif t == "final":
            console.print(Rule("Your Trip Plan", style="gold1"))
            console.print(Markdown(ev["text"]))

    await plan_trip(request, emit)


def main() -> int:
    if len(sys.argv) < 2:
        console.print("Usage: python cli.py \"<your trip request>\"")
        console.print("Example: python cli.py \"5-day food trip to Tokyo\"")
        return 1
    request = " ".join(sys.argv[1:])
    try:
        asyncio.run(run(request))
    except Exception as exc:
        console.print(f"[red]Error:[/] {exc}")
        console.print("[dim]Are the agents running? Start them with: python launch.py[/]")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
