"""A2A standard error types (v1.0.0) — named errors carrying JSON-RPC codes.

Atlas runs agents in-process (no JSON-RPC envelope *between* agents — a by-design non-goal),
so these surface at the **external edge**: the HTTP+JSON binding (``atlas/api/binding.py``)
maps each to an HTTP status + a spec-shaped error body ``{"error": {"code", "message", "type",
"data"}}``. The JSON-RPC *code* is carried for clients that branch on it; no JSON-RPC transport
is introduced.
"""

from __future__ import annotations

from typing import Any, Optional


class A2AError(Exception):
    """Base A2A error. Subclasses set ``code`` (JSON-RPC), ``message``, and ``http_status``."""

    code: int = -32603
    message: str = "Internal error"
    http_status: int = 500

    def __init__(self, message: Optional[str] = None, *, data: Any = None) -> None:
        if message is not None:
            self.message = message
        self.data = data
        super().__init__(self.message)

    def to_body(self) -> dict:
        err: dict[str, Any] = {"code": self.code, "message": self.message, "type": type(self).__name__}
        if self.data is not None:
            err["data"] = self.data
        return {"error": err}


# ─── JSON-RPC standard errors ──────────────────────────────────────────────────
class JSONParseError(A2AError):
    code, message, http_status = -32700, "Invalid JSON payload", 400


class InvalidRequestError(A2AError):
    code, message, http_status = -32600, "Invalid request", 400


class MethodNotFoundError(A2AError):
    code, message, http_status = -32601, "Method not found", 404


class InvalidParamsError(A2AError):
    code, message, http_status = -32602, "Invalid parameters", 400


class InternalError(A2AError):
    code, message, http_status = -32603, "Internal error", 500


# ─── A2A-specific errors ───────────────────────────────────────────────────────
class TaskNotFoundError(A2AError):
    code, message, http_status = -32001, "Task not found", 404


class TaskNotCancelableError(A2AError):
    code, message, http_status = -32002, "Task is in a terminal state and cannot be canceled", 409


class PushNotificationNotSupportedError(A2AError):
    code, message, http_status = -32003, "Push notifications are not supported", 400


class UnsupportedOperationError(A2AError):
    code, message, http_status = -32004, "This operation is not supported", 400


class ContentTypeNotSupportedError(A2AError):
    code, message, http_status = -32005, "Incompatible content type", 415


class InvalidAgentResponseError(A2AError):
    code, message, http_status = -32006, "The agent returned an invalid response", 502


class AuthenticatedExtendedCardNotConfiguredError(A2AError):
    code, message, http_status = -32007, "The authenticated extended card is not configured", 404


class VersionNotSupportedError(A2AError):
    code, message, http_status = -32009, "The requested A2A protocol version is not supported", 400


class ExtensionSupportRequiredError(A2AError):
    code, message, http_status = -32010, "A required extension is not supported by the client", 400
