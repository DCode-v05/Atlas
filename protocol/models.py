"""
protocol/models.py — the A2A data models.

Field names are camelCase ON PURPOSE: they mirror the JSON that travels on the
wire, so what you read here is exactly what an A2A client sees. Anything optional
is dropped on serialisation (``dump``) so the protocol log stays clean.

This module is pure A2A — it knows nothing about roles, performatives or the
organisation. Those ride along inside ``metadata`` (see ``org/envelope.py``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

A2A_PROTOCOL_VERSION = "0.3.0"
AGENT_CARD_PATH = "/.well-known/agent-card.json"


def now_iso() -> str:
    """ISO-8601 UTC timestamp, e.g. 2026-06-17T10:30:00+00:00."""
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ===========================================================================
# Agent Card  (served at /.well-known/agent-card.json — the discovery surface)
# ===========================================================================
class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = []
    examples: list[str] = []


class AgentCapabilities(BaseModel):
    streaming: bool = True
    pushNotifications: bool = False
    extensions: list[str] = []          # URIs of A2A extensions this agent honours


class AgentProvider(BaseModel):
    organization: str
    url: str


class AgentCard(BaseModel):
    protocolVersion: str = A2A_PROTOCOL_VERSION
    name: str
    description: str
    url: str                            # base URL; the JSON-RPC endpoint is its root "/"
    version: str = "1.0.0"              # the AGENT's version (not the protocol's)
    preferredTransport: str = "JSONRPC"
    capabilities: AgentCapabilities = AgentCapabilities()
    defaultInputModes: list[str] = ["text/plain"]
    defaultOutputModes: list[str] = ["text/plain"]
    skills: list[AgentSkill] = []
    provider: Optional[AgentProvider] = None


# ===========================================================================
# Parts  (the content union — discriminated by `kind`)
# ===========================================================================
class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    metadata: Optional[dict] = None


class DataPart(BaseModel):
    """Structured payload (e.g. a Contract-Net bid {cost, eta})."""
    kind: Literal["data"] = "data"
    data: dict
    metadata: Optional[dict] = None


class FilePart(BaseModel):
    kind: Literal["file"] = "file"
    file: dict                          # {name, mimeType, uri | bytes}
    metadata: Optional[dict] = None


Part = Annotated[Union[TextPart, DataPart, FilePart], Field(discriminator="kind")]


# ===========================================================================
# Message  (what a client sends; what an agent replies inside a status update)
# ===========================================================================
class Message(BaseModel):
    kind: Literal["message"] = "message"
    role: Literal["user", "agent"]
    parts: list[Part]
    messageId: str = Field(default_factory=lambda: new_id("msg"))
    taskId: Optional[str] = None
    contextId: Optional[str] = None
    referenceTaskIds: Optional[list[str]] = None   # link to prior tasks (same context)
    extensions: Optional[list[str]] = None
    metadata: Optional[dict] = None                # org envelope rides here


class Artifact(BaseModel):
    artifactId: str = Field(default_factory=lambda: new_id("art"))
    name: Optional[str] = None
    description: Optional[str] = None
    parts: list[Part]
    metadata: Optional[dict] = None


class TaskStatus(BaseModel):
    state: str
    message: Optional[Message] = None
    timestamp: Optional[str] = None


class Task(BaseModel):
    kind: Literal["task"] = "task"
    id: str
    contextId: str
    status: TaskStatus
    artifacts: list[Artifact] = []
    history: list[Message] = []
    metadata: Optional[dict] = None


# ---- streaming events -----------------------------------------------------
class TaskStatusUpdateEvent(BaseModel):
    kind: Literal["status-update"] = "status-update"
    taskId: str
    contextId: str
    status: TaskStatus
    final: bool = False                 # the last event of a stream


class TaskArtifactUpdateEvent(BaseModel):
    kind: Literal["artifact-update"] = "artifact-update"
    taskId: str
    contextId: str
    artifact: Artifact
    lastChunk: bool = True


# ===========================================================================
# Builders & helpers
# ===========================================================================
def dump(model: BaseModel) -> dict:
    """Serialise to a plain JSON-able dict, dropping unset (None) fields."""
    return model.model_dump(exclude_none=True)


def user_text_message(text: str, *, task_id: Optional[str] = None,
                      context_id: Optional[str] = None,
                      reference_task_ids: Optional[list[str]] = None,
                      metadata: Optional[dict] = None) -> Message:
    return Message(role="user", parts=[TextPart(text=text)], taskId=task_id,
                   contextId=context_id, referenceTaskIds=reference_task_ids,
                   metadata=metadata)


def agent_text_message(text: str, *, task_id: str, context_id: str,
                       metadata: Optional[dict] = None) -> Message:
    return Message(role="agent", parts=[TextPart(text=text)], taskId=task_id,
                   contextId=context_id, metadata=metadata)


def text_of(message: Optional[dict]) -> str:
    """Concatenate every text part of an incoming message dict."""
    if not isinstance(message, dict):
        return ""
    out = [p.get("text", "") for p in message.get("parts", [])
           if isinstance(p, dict) and p.get("kind") == "text"]
    return "\n".join(t for t in out if t).strip()


def data_of(message: Optional[dict]) -> Optional[dict]:
    """Return the first data part's payload, if any."""
    if not isinstance(message, dict):
        return None
    for p in message.get("parts", []):
        if isinstance(p, dict) and p.get("kind") == "data":
            return p.get("data")
    return None


def artifact_from(value) -> Artifact:
    """Wrap a handler's return value as an Artifact: str -> text, dict -> data."""
    if isinstance(value, Artifact):
        return value
    if isinstance(value, dict):
        return Artifact(name="result", parts=[DataPart(data=value)])
    return Artifact(name="result", parts=[TextPart(text=str(value))])


# ---- pulling results back out of a finished Task --------------------------
def result_text(task: "Task") -> str:
    """First text artifact of a completed task."""
    for art in (task.artifacts or []):
        for p in art.parts:
            if isinstance(p, TextPart):
                return p.text
    return ""


def result_data(task: "Task") -> Optional[dict]:
    """First data artifact of a completed task (structured output)."""
    for art in (task.artifacts or []):
        for p in art.parts:
            if isinstance(p, DataPart):
                return p.data
    return None


# ---- reading streamed events (dicts) --------------------------------------
def event_text(event: dict) -> Optional[str]:
    """Text of an artifact-update event, or the status note of a status-update."""
    if event.get("kind") == "artifact-update":
        for p in event.get("artifact", {}).get("parts", []):
            if p.get("kind") == "text":
                return p.get("text")
    if event.get("kind") == "status-update":
        msg = (event.get("status") or {}).get("message")
        if msg:
            return text_of(msg)
    return None


def event_state(event: dict) -> Optional[str]:
    """Task state carried by a task or status-update event."""
    if event.get("kind") in ("task", "status-update"):
        return (event.get("status") or {}).get("state")
    return None
