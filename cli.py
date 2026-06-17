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

from common import memory
from common.llm import model_name, using_real_llm
from orchestrator.orchestrator import plan_trip

console = Console()

COLORS = {"destination": "cyan", "itinerary": "yellow", "budget": "red",
          "weather": "magenta", "cuisine": "green", "host": "gold1"}


async def run_turn(request: str, context_id: str) -> None:
    console.print(f"\n[bold]You:[/] {request}")

    async def emit(ev: dict) -> None:
        t = ev["type"]
        if t == "recall":
            if not ev["isFirst"]:
                console.print(f"[gold1]host[/] continuing conversation (turn {ev['turnCount'] + 1})")
            if ev.get("preferences"):
                console.print(f"[dim]   recalled preferences: {', '.join(ev['preferences'])}[/]")
        elif t == "understood":
            b = ev["beliefs"]
            console.print(f"[gold1]host[/] beliefs -> [b]{b['destination']}[/], {b['days']} days, "
                          f"{', '.join(b['interests'])}, {b['travelStyle']}")
            console.print(f"[dim]   goal: {ev['intent']['goal']}"
                          + (f"  | changed: {', '.join(ev['changed'])}" if ev['changed'] else "") + "[/]")
        elif t == "memory_added":
            console.print(f"[green]   remembered for next time: {', '.join(ev['facts'])}[/]")
        elif t == "discovered":
            names = ", ".join(a["card"]["name"] for a in ev["agents"])
            console.print(f"[gold1]host[/] discovered agents via Agent Cards: {names}")
        elif t == "selection":
            line = f"[gold1]host[/] running: {', '.join(ev['selected']) or '(none — all cached)'}"
            if ev["reused"]:
                line += f"  ·  reusing cached: {', '.join(ev['reused'])}"
            console.print(line)
            console.print(Rule(style="grey30"))
        elif t == "delegate":
            c = COLORS.get(ev["agent"], "white")
            console.print(f"[{c}]-> {ev['agentName']}[/]  [dim]message/stream · intent:[/] {ev['intent']}")
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
        elif t == "agent_reused":
            console.print(f"   [dim]{ev['agent']} unchanged — reused cached result[/]")
        elif t == "agent_error":
            console.print(f"   [red]{ev['agent']} error: {ev['message']}[/]")
        elif t == "negotiate_start":
            console.print(Rule("Round-Table Negotiation", style="grey30"))
            console.print(f"[gold1]host[/] the specialists talk it over: "
                          f"{', '.join(p['name'] for p in ev['participants'])}")
        elif t == "negotiate_said":
            c = COLORS.get(ev["speaker"], "white")
            console.print(f"   [{c}]{ev['speakerName']}[/] [dim]({ev['performative']})[/]: {ev['text']}")
        elif t == "negotiate_end":
            console.print(Rule(style="grey30"))
        elif t == "synthesis_start":
            console.print(Rule(style="grey30"))
            console.print("[gold1]host[/] synthesizing final plan...")
        elif t == "final":
            console.print(Rule("Trip Plan", style="gold1"))
            console.print(Markdown(ev["text"]))

    await plan_trip(request, emit, context_id=context_id)


def main() -> int:
    if len(sys.argv) < 2:
        console.print("Usage: python cli.py \"<your trip request>\"")
        console.print("Example: python cli.py \"5-day food trip to Tokyo\"")
        return 1
    request = " ".join(sys.argv[1:])
    mode = f"Groq · {model_name()}" if using_real_llm() else "offline mock"
    console.print(Panel.fit(f"[bold]ATLAS[/] · A2A Trip Concierge (with memory)\nLLM: {mode}",
                            border_style="gold1"))
    context_id = memory.new_context_id()
    try:
        asyncio.run(run_turn(request, context_id))
        # Multi-turn: keep the same context so the orchestrator REMEMBERS.
        while True:
            try:
                follow = input("\nFollow-up (e.g. \"make it cheaper\"), or Enter to quit: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not follow:
                break
            asyncio.run(run_turn(follow, context_id))
    except Exception as exc:
        console.print(f"[red]Error:[/] {exc}")
        console.print("[dim]Are the agents running? Start them with: python launch.py[/]")
        return 1
    console.print("\n[dim]Conversation saved. Safe travels![/]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
