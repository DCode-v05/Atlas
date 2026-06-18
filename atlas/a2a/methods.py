"""A2A JSON-RPC method names.

Atlas runs agents in-process, so these are never sent over a socket — but the
Router dispatches against exactly these method *semantics*, so naming them keeps
the in-process bus honest to the protocol.
"""

from __future__ import annotations

from enum import Enum


class A2AMethod(str, Enum):
    MESSAGE_SEND = "message/send"
    MESSAGE_STREAM = "message/stream"
    TASKS_GET = "tasks/get"
    TASKS_CANCEL = "tasks/cancel"
    TASKS_LIST = "tasks/list"
    AGENT_CARD = "agent/card"
