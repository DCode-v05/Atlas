"""Faithful A2A protocol data models (Pydantic v2).

This module is pure protocol — no business logic. Every Atlas-specific concept
attaches through :class:`AgentExtension` (see ``a2a/extensions.py``), never by
adding fields here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from atlas.a2a.ids import new_id, utcnow

# ─── Task lifecycle ───────────────────────────────────────────────────────────


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INPUT_REQUIRED = "input-required"
    AUTH_REQUIRED = "auth-required"
    REJECTED = "rejected"


TERMINAL_STATES = frozenset(
    {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED, TaskState.REJECTED}
)


# ─── Parts (discriminated union on ``kind``) ──────────────────────────────────


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataPart(BaseModel):
    kind: Literal["data"] = "data"
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FileWithUri(BaseModel):
    """A2A v1.0.0 ``FileWithUri`` — a file referenced by URI (not inline bytes)."""

    uri: str
    mimeType: Optional[str] = None
    name: Optional[str] = None


class FilePart(BaseModel):
    kind: Literal["file"] = "file"
    file: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_uri(cls, uri: str, *, mimeType: Optional[str] = None, name: Optional[str] = None) -> "FilePart":
        """A spec-shaped file part referencing a file by URI (the URL-only variant)."""
        return cls(file=FileWithUri(uri=uri, mimeType=mimeType, name=name).model_dump(exclude_none=True))


Part = Annotated[Union[TextPart, DataPart, FilePart], Field(discriminator="kind")]


# ─── Agent Card ───────────────────────────────────────────────────────────────


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class AgentExtension(BaseModel):
    uri: str
    description: Optional[str] = None  # spec: human-readable purpose of the extension
    required: bool = False
    params: dict[str, Any] = Field(default_factory=dict)  # spec: extension config / payload
    version: str = "1"  # non-spec convenience (the version is also encoded in the URI)


class AgentCapabilities(BaseModel):
    streaming: bool = True
    pushNotifications: bool = False
    extendedAgentCard: bool = False  # an authenticated client can fetch a richer card
    extensions: list[AgentExtension] = Field(default_factory=list)


class AgentProvider(BaseModel):
    organization: str
    url: str = ""


class AgentInterface(BaseModel):
    transport: str = "in-process"
    url: str = ""


class AgentCard(BaseModel):
    id: str
    name: str
    description: str
    provider: AgentProvider
    version: str = "1.0.0"
    protocolVersion: str = "1.0.0"  # A2A protocol version this card speaks
    url: str = ""                   # the service URL an external client connects to
    preferredTransport: str = "in-process"
    iconUrl: Optional[str] = None
    documentationUrl: Optional[str] = None
    defaultInputModes: list[str] = Field(default_factory=lambda: ["text/plain"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text/plain"])
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = Field(default_factory=list)
    securitySchemes: dict[str, Any] = Field(default_factory=dict)
    securityRequirements: list[dict[str, Any]] = Field(default_factory=list)
    interfaces: list[AgentInterface] = Field(default_factory=list)
    signature: Optional[str] = None

    def extension(self, uri: str) -> Optional[AgentExtension]:
        """Return the declared extension with ``uri`` — spec-located under ``capabilities.extensions``."""
        for ext in self.capabilities.extensions:
            if ext.uri == uri:
                return ext
        return None

    @property
    def skill_tags(self) -> set[str]:
        tags: set[str] = set()
        for skill in self.skills:
            tags.update(t.lower() for t in skill.tags)
        return tags


# ─── Message ──────────────────────────────────────────────────────────────────


class Message(BaseModel):
    messageId: str = Field(default_factory=lambda: new_id("msg-"))
    role: Literal["user", "agent"]
    parts: list[Part] = Field(default_factory=list)
    contextId: Optional[str] = None
    taskId: Optional[str] = None
    extensions: list[str] = Field(default_factory=list)
    referenceTaskIds: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def text_message(
        cls, role: Literal["user", "agent"], text: str, **kw: Any
    ) -> "Message":
        return cls(role=role, parts=[TextPart(text=text)], **kw)

    @property
    def text_content(self) -> str:
        return " ".join(p.text for p in self.parts if isinstance(p, TextPart))


# ─── Task ─────────────────────────────────────────────────────────────────────


class TaskStatus(BaseModel):
    state: TaskState
    message: Optional[Message] = None
    timestamp: datetime = Field(default_factory=utcnow)


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art-"))
    name: Optional[str] = None
    parts: list[Part] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task-"))
    contextId: str
    status: TaskStatus
    artifacts: list[Artifact] = Field(default_factory=list)
    history: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def state(self) -> TaskState:
        return self.status.state


# ─── A2A streaming events (SubscribeToTask / SendStreamingMessage) ────────────


class TaskStatusUpdateEvent(BaseModel):
    """A2A status-update event — a task's state changed. ``final`` is True on a
    terminal state, at which point the stream closes (the A2A terminal-close
    contract). This is the spec shape an external streaming client receives."""

    kind: Literal["status-update"] = "status-update"
    taskId: str
    contextId: str
    status: TaskStatus
    final: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskArtifactUpdateEvent(BaseModel):
    """A2A artifact-update event — a new/updated artifact produced by a task.
    ``lastChunk`` marks the final piece of a (possibly chunked) artifact."""

    kind: Literal["artifact-update"] = "artifact-update"
    taskId: str
    contextId: str
    artifact: Artifact
    append: bool = False
    lastChunk: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamResponse(BaseModel):
    """The A2A streaming envelope (a oneof): each streamed frame carries exactly
    one of a full Task snapshot, a Message, a status-update, or an artifact-update.
    This is what ``SubscribeToTask`` / ``SendStreamingMessage`` yield per event."""

    task: Optional[Task] = None
    message: Optional[Message] = None
    statusUpdate: Optional[TaskStatusUpdateEvent] = None
    artifactUpdate: Optional[TaskArtifactUpdateEvent] = None


# ─── Push notification (webhook) config ───────────────────────────────────────


class PushNotificationAuthentication(BaseModel):
    """How a webhook receiver authenticates an inbound call.

    A2A ``PushNotificationAuthenticationInfo``: the auth ``schemes`` the receiver
    expects and (opaque per the spec) the ``credentials`` to present.
    """

    schemes: list[str] = Field(default_factory=list)  # e.g. ["Bearer", "ApiKey"]
    credentials: Optional[str] = None


class PushNotificationConfig(BaseModel):
    """A client-registered webhook for a task's status updates (A2A ``PushNotificationConfig``)."""

    id: str = Field(default_factory=lambda: new_id("pnc-"))
    url: str
    token: Optional[str] = None  # echoed back so the receiver can validate the call is genuine
    authentication: Optional[PushNotificationAuthentication] = None


class TaskPushNotificationConfig(BaseModel):
    """Binds a :class:`PushNotificationConfig` to a task (A2A ``TaskPushNotificationConfig``)."""

    taskId: str
    pushNotificationConfig: PushNotificationConfig
