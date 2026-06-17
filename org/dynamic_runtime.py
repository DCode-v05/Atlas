"""
org/dynamic_runtime.py — spawn a REAL OS process per hire, on demand.

This is the "authentic" capped-dynamic runtime: hiring an agent literally starts
a new ``python -m org.employee`` process on its own port. A small pool is
pre-warmed to hide startup latency; beyond that, processes are spawned on demand
up to the headcount cap and then RECYCLED (kept warm, re-onboarded) rather than
killed. Enable with ``ATLAS_RUNTIME=dynamic``.

It implements the same Runtime interface as PooledRuntime, so nothing above it
changes — only how an agent comes to exist. The blocking spawn is deliberately
offloaded by the gateway (asyncio.to_thread) so it never stalls the event loop.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time

import config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((config.HOST, port)) == 0


def _wait_port(port: int, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if _port_open(port):
            return True
        time.sleep(0.1)
    return False


class DynamicRuntime:
    def __init__(self, prewarm: int = 3, max_procs: int | None = None):
        self.prewarm = prewarm
        self.max_procs = max_procs or config.MAX_HEADCOUNT
        self.lock = threading.Lock()
        self.procs: dict[str, dict] = {}     # agentId -> {proc,port,url,status,runId}
        self._n = 0

    def start(self) -> None:
        for _ in range(min(self.prewarm, self.max_procs)):
            self._spawn()

    # -- internals (call under self.lock) ----------------------------------
    def _free_port(self) -> int:
        used = {m["port"] for m in self.procs.values()}
        p = config.EMPLOYEE_PORT_BASE
        while p in used or _port_open(p):
            p += 1
        return p

    def _spawn(self) -> str | None:
        if len(self.procs) >= self.max_procs:
            return None
        self._n += 1
        aid = f"D{self._n}"
        port = self._free_port()
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen(
            [sys.executable, "-m", "org.employee", "--id", aid, "--port", str(port),
             "--gateway", config.gateway_url()],
            cwd=_ROOT, creationflags=flags)
        if not _wait_port(port):
            try:
                proc.terminate()
            except Exception:
                pass
            return None
        self.procs[aid] = {"proc": proc, "port": port, "status": "free", "runId": None,
                           "url": f"http://{config.HOST}:{port}/"}
        return aid

    def _take_free(self, run_id: str) -> dict | None:
        for aid, m in self.procs.items():
            if m["status"] == "free":
                m["status"], m["runId"] = "assigned", run_id
                return {"agentId": aid, "url": m["url"]}
        return None

    def _hire_one(self, run_id: str) -> dict | None:
        if sum(1 for m in self.procs.values() if m["runId"] == run_id) >= config.MAX_HEADCOUNT:
            return None
        got = self._take_free(run_id)
        if got:
            return got
        aid = self._spawn()
        if not aid:
            return None
        self.procs[aid].update(status="assigned", runId=run_id)
        return {"agentId": aid, "url": self.procs[aid]["url"]}

    # -- Runtime interface --------------------------------------------------
    def allocate(self, run_id, role_hint="", requester="", depth=0) -> dict | None:
        with self.lock:
            return self._hire_one(run_id)

    def reserve_candidates(self, run_id: str, k: int) -> list[dict]:
        out = []
        with self.lock:
            for _ in range(k):
                got = self._hire_one(run_id)
                if not got:
                    break
                out.append(got)
        return out

    def release(self, agent_id: str) -> None:
        with self.lock:
            m = self.procs.get(agent_id)
            if m:
                m.update(status="free", runId=None)     # recycle: keep the process warm

    def members(self) -> list[dict]:
        with self.lock:
            return [{"agentId": a, "url": m["url"], "status": m["status"], "runId": m["runId"]}
                    for a, m in self.procs.items()]

    def shutdown(self) -> None:
        for m in self.procs.values():
            try:
                m["proc"].terminate()
            except Exception:
                pass
