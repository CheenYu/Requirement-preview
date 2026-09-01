"""Core API and task models for the backend."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentKind(str, Enum):
    intake = "intake"
    analyzer = "analyzer"
    reviewer = "reviewer"
    synthesizer = "synthesizer"


class AgentProfile(BaseModel):
    agent_id: str
    name: str
    kind: AgentKind
    description: str
    enabled: bool = True
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(BaseModel):
    input: str = Field(..., min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None


class AgentResponse(BaseModel):
    agent_id: str
    output: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    input: str = Field(..., min_length=1)
    agent_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    input: str
    agent_id: str
    status: TaskStatus = TaskStatus.pending
    output: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class TaskListResponse(BaseModel):
    tasks: list[TaskRecord]


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: datetime = Field(default_factory=datetime.now)


class AgentListResponse(BaseModel):
    agents: list[AgentProfile]
