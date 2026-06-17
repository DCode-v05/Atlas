"""
launch.py — start the whole ATLAS organisation with one command.

It pre-warms the employee pool, starts the gateway (UI + telemetry + HR), opens
your browser, and shuts everything down cleanly on Ctrl+C.

    python launch.py
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from functools import partial

import uvicorn

import config
from gateway.app import create_app
from org.runtime import make_runtime

# Windows consoles default to cp1252; redirected stdout then crashes on non-ASCII.
# Force UTF-8 so the banner can never take the server down.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

print = partial(print, flush=True)


def main() -> int:
    print("=" * 60)
    print(f"  {config.COMPANY_NAME} - an organisation of communicating A2A agents")
    print("=" * 60)

    runtime = make_runtime()
    print(f"  pre-warming {config.POOL_SIZE} employees ({config.RUNTIME} runtime)...")
    runtime.start()
    app = create_app(runtime)

    url = config.gateway_url() + "/"
    print(f"  gateway live -> {url}")
    print(f"  caps: headcount <= {config.MAX_HEADCOUNT} | depth <= {config.MAX_DELEGATION_DEPTH} "
          f"| budget {config.TOKEN_BUDGET:,} tokens")
    print("  Ctrl+C to stop.")
    print("-" * 60)
    threading.Timer(1.2, lambda: _open(url)).start()

    try:
        uvicorn.run(app, host=config.HOST, port=config.GATEWAY_PORT, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        runtime.shutdown()
        print("\n  Stopped.")
    return 0


def _open(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
