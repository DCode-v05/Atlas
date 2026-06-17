"""
protocol/states.py — the A2A task lifecycle states.

These literal strings travel on the wire. They are lowercase and hyphenated
exactly as the A2A JSON-RPC binding requires (e.g. ``input-required``, NOT
``INPUT_REQUIRED`` — that SCREAMING_CASE form is the protobuf/gRPC binding, a
different surface of the same spec).
"""
from __future__ import annotations


class TaskState:
    submitted = "submitted"            # accepted, not started yet
    working = "working"                # in progress
    input_required = "input-required"  # paused: needs more input from the caller
    auth_required = "auth-required"    # paused: needs authentication
    completed = "completed"            # finished successfully (terminal)
    canceled = "canceled"              # the caller cancelled (terminal)
    failed = "failed"                  # finished with an error (terminal)
    rejected = "rejected"              # the agent declined the task (terminal)
    unknown = "unknown"


TERMINAL_STATES = frozenset({
    TaskState.completed,
    TaskState.canceled,
    TaskState.failed,
    TaskState.rejected,
})

PAUSED_STATES = frozenset({
    TaskState.input_required,
    TaskState.auth_required,
})


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES
