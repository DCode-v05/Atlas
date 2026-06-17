"""
org/runtime.py — the Runtime interface and the Phase-2 PooledRuntime.

"Hiring" needs a physical agent to hand a role to. We hide *how* that agent
comes to exist behind a Runtime interface, so the communication layer never has
to care:

  * PooledRuntime (here)      — pre-warm a fixed pool of real employee servers,
                                each on its own port in a background thread.
                                Allocate = hand a free one to a run. Fast, robust;
                                the right thing while we build the comms core.
  * DynamicRuntime (Phase 6)  — spawn a real OS process per hire, on demand.

Both speak real A2A on real TCP ports; only the provisioning differs.
"""
from __future__ import annotations

import socket
import threading
import time

import uvicorn

import config
from org.employee import Employee


class Runtime:
    def start(self) -> None: ...
    def allocate(self, run_id: str, role_hint: str = "", requester: str = "",
                 depth: int = 0) -> dict | None: ...
    def reserve_candidates(self, run_id: str, k: int) -> list[dict]: ...  # hold k for an auction
    def release(self, agent_id: str) -> None: ...
    def members(self) -> list[dict]: ...
    def shutdown(self) -> None: ...


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((config.HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


class PooledRuntime(Runtime):
    def __init__(self, size: int | None = None):
        self.size = size or config.POOL_SIZE
        self.pool: dict[str, dict] = {}     # agent_id -> {url,status,runId,emp,server}

    def start(self) -> None:
        for i in range(self.size):
            aid = f"E{i + 1}"
            port = config.employee_port(i)
            emp = Employee(aid, port, config.gateway_url())
            server = self._serve(emp.build_app(), port)
            self.pool[aid] = {"url": f"http://{config.HOST}:{port}/", "status": "free",
                              "runId": None, "emp": emp, "server": server}
        for i in range(self.size):
            _wait_port(config.employee_port(i))

    def _serve(self, app, port: int):
        cfg = uvicorn.Config(app, host=config.HOST, port=port, log_level="warning")
        server = uvicorn.Server(cfg)
        server.install_signal_handlers = lambda: None   # not on the main thread
        threading.Thread(target=server.run, daemon=True).start()
        return server

    def allocate(self, run_id, role_hint="", requester="", depth=0) -> dict | None:
        assigned = sum(1 for m in self.pool.values() if m["runId"] == run_id)
        if assigned >= config.MAX_HEADCOUNT:
            return None                                  # headcount cap (hard)
        for aid, m in self.pool.items():
            if m["status"] == "free":
                m["status"] = "assigned"
                m["runId"] = run_id
                m["emp"].reset_identity()
                return {"agentId": aid, "url": m["url"]}
        return None                                      # pool exhausted

    def reserve_candidates(self, run_id: str, k: int) -> list[dict]:
        """Atomically hold up to k free employees for an auction. Runs in the
        gateway's single event loop, so concurrent managers get DISJOINT sets
        (no two managers interview the same candidate). Losers are released; the
        winner stays held as the hire. Respects the per-run headcount cap."""
        out = []
        for aid, m in self.pool.items():
            if len(out) >= k:
                break
            if m["status"] != "free":
                continue
            if sum(1 for x in self.pool.values() if x["runId"] == run_id) >= config.MAX_HEADCOUNT:
                break
            m["status"] = "assigned"
            m["runId"] = run_id
            m["emp"].reset_identity()
            out.append({"agentId": aid, "url": m["url"]})
        return out

    def release(self, agent_id: str) -> None:
        m = self.pool.get(agent_id)
        if m:
            m.update(status="free", runId=None)
            m["emp"].reset_identity()

    def members(self) -> list[dict]:
        return [{"agentId": aid, "url": m["url"], "status": m["status"], "runId": m["runId"]}
                for aid, m in self.pool.items()]

    def shutdown(self) -> None:
        for m in self.pool.values():
            try:
                m["server"].should_exit = True
            except Exception:
                pass


def make_runtime() -> Runtime:
    """Pick a runtime from config. (DynamicRuntime arrives in Phase 6.)"""
    if config.RUNTIME == "dynamic":
        try:
            from org.dynamic_runtime import DynamicRuntime
            return DynamicRuntime()
        except Exception:
            pass
    return PooledRuntime()
