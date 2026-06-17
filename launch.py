"""
launch.py — start the whole Smart Trip Planner with one command.
================================================================

It launches the 3 specialist A2A agents and the web gateway, waits until each
is reachable, opens your browser, and shuts everything down cleanly on Ctrl+C.

    python launch.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from functools import partial

from common.config import (GATEWAY_PORT, ORCHESTRATOR_AGENT, SPECIALISTS,
                           WEATHER_MCP)

# Flush every print immediately so status lines show up even when output is
# piped/redirected (Python block-buffers stdout when it isn't a terminal).
print = partial(print, flush=True)

PROCS: list[subprocess.Popen] = []


def is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_until_up(port: int, timeout: float = 30.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if is_listening(port):
            return True
        time.sleep(0.3)
    return False


def spawn(module: str) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen([sys.executable, "-m", module], creationflags=flags)
    PROCS.append(proc)
    return proc


def shutdown() -> None:
    print("\nShutting down agents and gateway...")
    for p in PROCS:
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(1.0)
    for p in PROCS:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    print("All stopped. Safe travels!")


def _start(label: str, module: str, port: int) -> bool:
    print(f"  starting {label:<16}: {module:<28} :{port}")
    spawn(module)
    if not wait_until_up(port):
        print(f"[!] {module} on port {port} did not start. Aborting.")
        shutdown()
        return False
    return True


def main() -> int:
    # Everything we run, in startup order. The MCP weather tool server goes
    # first (the Weather agent calls it); then all A2A agents; then the gateway.
    all_ports = ([WEATHER_MCP["port"], ORCHESTRATOR_AGENT["port"]]
                 + [s["port"] for s in SPECIALISTS] + [GATEWAY_PORT])
    busy = [p for p in all_ports if is_listening(p)]
    if busy:
        print(f"[!] These ports are already in use: {busy}")
        print("    Close whatever is using them (or a previous run) and retry.")
        return 1

    print("=" * 64)
    print(" ATLAS - Smart Trip Planner (A2A + MCP prototype)")
    print("=" * 64)

    # 1) the MCP weather tool server (NOT an A2A agent)
    if not _start("MCP tool server", WEATHER_MCP["module"], WEATHER_MCP["port"]):
        return 1
    # 2) the specialist A2A agents + the orchestrator A2A agent
    if not _start("orchestrator", ORCHESTRATOR_AGENT["module"], ORCHESTRATOR_AGENT["port"]):
        return 1
    for s in SPECIALISTS:
        if not _start("agent", s["module"], s["port"]):
            return 1
    # 3) the web gateway
    if not _start("gateway", "gateway.app", GATEWAY_PORT):
        return 1

    url = f"http://127.0.0.1:{GATEWAY_PORT}/"
    print("-" * 64)
    print(f"  Everything is running. Open:  {url}")
    print(f"  Orchestrator agent card: http://127.0.0.1:{ORCHESTRATOR_AGENT['port']}/.well-known/agent-card.json")
    print("  Specialist Agent Cards:")
    for s in SPECIALISTS:
        print(f"    http://127.0.0.1:{s['port']}/.well-known/agent-card.json")
    print(f"  Weather MCP tool server: http://127.0.0.1:{WEATHER_MCP['port']}/mcp")
    print("-" * 64)
    print("  Press Ctrl+C here to stop everything.")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    warned: set[int] = set()
    try:
        while True:
            time.sleep(1)
            # If a child dies, warn once but keep the others running — that's
            # what lets you try the "stop one agent" experiment and watch the
            # orchestrator degrade gracefully. Press Ctrl+C to stop everything.
            for p in PROCS:
                if p.poll() is not None and p.pid not in warned:
                    warned.add(p.pid)
                    print(f"[!] a child process (pid {p.pid}) exited. The rest keep "
                          f"running; press Ctrl+C to stop all.")
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
