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


#: Human-readable catalog: what each A2A method means and where Atlas exercises
#: its semantics on the in-process bus. Surfaced via ``GET /api/a2a/methods`` so
#: the UI can explain the protocol calls behind every hop.
A2A_METHOD_CATALOG: tuple[dict[str, str], ...] = (
    {
        "method": A2AMethod.MESSAGE_SEND.value,
        "summary": "Send a message to an agent and get its reply.",
        "atlas": "Every agent→agent hop on the bus (requests, replies, group turns) — the Router's send_message.",
        "active": "yes",
    },
    {
        "method": A2AMethod.MESSAGE_STREAM.value,
        "summary": "Send a message and stream incremental updates back.",
        "atlas": "The browser↔backend SSE stream (/api/events) plays the same streaming role.",
        "active": "yes",
    },
    {
        "method": A2AMethod.TASKS_GET.value,
        "summary": "Fetch a task's current status, history and artifacts.",
        "atlas": "GET /api/tasks/{id}; the orchestrator reads/advances task state per scenario.",
        "active": "yes",
    },
    {
        "method": A2AMethod.TASKS_LIST.value,
        "summary": "List the tasks known to the server.",
        "atlas": "GET /api/tasks — the live task roster.",
        "active": "yes",
    },
    {
        "method": A2AMethod.AGENT_CARD.value,
        "summary": "Retrieve an agent's Agent Card (skills, profile, clearance).",
        "atlas": "Discovery ranks cards to route, and GET /api/agents/{id}/card serves them.",
        "active": "yes",
    },
    {
        "method": A2AMethod.TASKS_CANCEL.value,
        "summary": "Cancel an in-flight task.",
        "atlas": "Protocol-complete; not triggered by the current scenarios.",
        "active": "no",
    },
)
