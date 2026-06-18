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


class FilePart(BaseModel):
    kind: Literal["file"] = "file"
    file: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    version: str = "1"
    required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCapabilities(BaseModel):
    streaming: bool = True
    pushNotifications: bool = False
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
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = Field(default_factory=list)
    securitySchemes: dict[str, Any] = Field(default_factory=dict)
    interfaces: list[AgentInterface] = Field(default_factory=list)
    extensions: list[AgentExtension] = Field(default_factory=list)
    signature: Optional[str] = None

    def extension(self, uri: str) -> Optional[AgentExtension]:
        """Return the declared extension with ``uri``, if any."""
        for ext in self.extensions:
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
