"""
show_protocol.py — see the ACTUAL A2A messages on the wire.
===========================================================

This is the best file to read if you want to understand what A2A *is*. It makes
three raw HTTP calls to one agent and prints the exact JSON each time:

    1. GET  /.well-known/agent-card.json   (discovery)
    2. POST /  with method "message/send"   (one-shot request/response)
    3. POST /  with method "message/stream" (streamed Server-Sent Events)

It will start the Destination Expert agent automatically if it isn't running.

    python show_protocol.py
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx

PORT = 8101
BASE = f"http://127.0.0.1:{PORT}"


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def pretty(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


async def demo() -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        # ---- 1. DISCOVERY ------------------------------------------------
        banner("1) DISCOVERY  ·  GET /.well-known/agent-card.json")
        print("This public 'business card' tells a client who the agent is and")
        print("what skills it offers, so the client knows how to use it.\n")
        card = (await client.get(BASE + "/.well-known/agent-card.json")).json()
        print(pretty(card))

        # ---- 2. message/send --------------------------------------------
        banner("2) message/send  ·  POST /  (one request, one finished Task)")
        send_req = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "message/send",
            "params": {
                "message": {
                    "kind": "message",
                    "role": "user",
                    "messageId": "m-1",
                    "parts": [{"kind": "text", "text": "Tell me about Kyoto in 2 lines."}],
                }
            },
        }
        print("---> REQUEST we POST:")
        print(pretty(send_req))
        resp = (await client.post(BASE + "/", json=send_req)).json()
        print("\n<--- RESPONSE (a JSON-RPC result containing a Task):")
        print(pretty(resp))

        # ---- 3. message/stream ------------------------------------------
        banner("3) message/stream  ·  POST /  (live Server-Sent Events)")
        print("Same idea, but the agent streams its progress. Each 'data:' line")
        print("is a JSON-RPC response whose result is one A2A event.\n")
        stream_req = {
            "jsonrpc": "2.0",
            "id": "req-2",
            "method": "message/stream",
            "params": {
                "message": {
                    "kind": "message",
                    "role": "user",
                    "messageId": "m-2",
                    "parts": [{"kind": "text", "text": "Best time to visit Kyoto?"}],
                }
            },
        }
        async with client.stream("POST", BASE + "/", json=stream_req) as resp:
            n = 0
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                n += 1
                frame = json.loads(line[len("data:"):].strip())
                event = frame["result"]
                kind = event.get("kind")
                print(f"  SSE frame #{n}  ->  kind = {kind}")
                print("  " + pretty(event).replace("\n", "\n  "))
                print()
        banner("Done. That is the entire A2A protocol surface for this demo.")


def main() -> int:
    proc = None
    if not is_listening(PORT):
        print(f"(Destination Expert not running — starting it on :{PORT} ...)")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen([sys.executable, "-m", "agents.destination_expert"],
                                creationflags=flags)
        for _ in range(40):
            if is_listening(PORT):
                break
            time.sleep(0.3)

    try:
        asyncio.run(demo())
    finally:
        if proc is not None:
            proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
