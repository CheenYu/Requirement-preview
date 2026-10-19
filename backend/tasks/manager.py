"""In-memory task manager for early-stage workflow execution."""

from __future__ import annotations

from datetime import datetime
from threading import Lock

from backend.models import TaskCreateRequest, TaskRecord, TaskStatus


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = Lock()

    def create(self, request: TaskCreateRequest) -> TaskRecord:
        task = TaskRecord(
            title=request.title,
            input=request.input,
            agent_id=request.agent_id,
            metadata=request.metadata,
        )
        with self._lock:
            self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> TaskRecord:
        with self._lock:
            return self._tasks[task_id]

    def list(self) -> list[TaskRecord]:
        with self._lock:
            tasks = list(self._tasks.values())
        return sorted(tasks, key=lambda task: task.created_at, reverse=True)

    def update_status(self, task_id: str, status: TaskStatus, *, error: str | None = None) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            task.status = status
            task.error = error
            task.updated_at = datetime.now()
            return task

    def complete(
        self,
        task_id: str,
        *,
        output: str,
        artifacts: dict,
        metadata: dict | None = None,
    ) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            task.output = output
            task.artifacts = artifacts
            if metadata is not None:
                task.metadata.update(metadata)
            task.status = TaskStatus.completed
            task.error = None
            task.updated_at = datetime.now()
            return task

    def fail(self, task_id: str, error: str) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            task.status = TaskStatus.failed
            task.error = error
            task.updated_at = datetime.now()
            return task

    def update_artifacts(
        self,
        task_id: str,
        *,
        artifacts: dict,
        metadata: dict | None = None,
        output: str | None = None,
    ) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            task.artifacts.update(artifacts)
            if metadata is not None:
                task.metadata.update(metadata)
            if output is not None:
                task.output = output
            task.updated_at = datetime.now()
            return task


task_manager = TaskManager()
