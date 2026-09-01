"""Task execution utilities for foreground and background runs."""

from __future__ import annotations

from threading import Thread
from time import perf_counter
from typing import Protocol

from backend.events import event_logger
from backend.maintenance import ensure_runtime_dirs, get_task_run_dir
from backend.models import AgentRequest, AgentResponse, TaskRecord, TaskStatus
from backend.tasks.manager import TaskManager


class AgentLike(Protocol):
    agent_id: str

    def run(self, request: AgentRequest) -> AgentResponse:
        ...


class AgentRegistryLike(Protocol):
    def get(self, agent_id: str) -> AgentLike:
        ...


class TaskRunner:
    def __init__(self, registry: AgentRegistryLike, manager: TaskManager) -> None:
        self.registry = registry
        self.manager = manager

    def run(self, task_id: str) -> TaskRecord:
        return self._run_now(task_id)

    def start_background(self, task_id: str) -> TaskRecord:
        task = self.manager.get(task_id)
        if task.status == TaskStatus.running:
            return task
        task = self.manager.update_status(task_id, TaskStatus.running)
        thread = Thread(target=self._run_now, args=(task_id,), daemon=True)
        thread.start()
        return task

    def _run_now(self, task_id: str) -> TaskRecord:
        ensure_runtime_dirs()
        task = self.manager.update_status(task_id, TaskStatus.running)
        run_dir = get_task_run_dir(task_id)
        event_logger.emit(
            "task_started",
            task_id=task_id,
            agent_id=task.agent_id,
            payload={"run_dir": str(run_dir)},
        )
        started = perf_counter()
        try:
            agent = self.registry.get(task.agent_id)
            response = agent.run(
                AgentRequest(
                    input=task.input,
                    context={"task_run_dir": str(run_dir)},
                    metadata=task.metadata,
                    task_id=task_id,
                )
            )
            elapsed_seconds = round(perf_counter() - started, 3)
            artifacts = dict(response.artifacts)
            artifacts.setdefault("run_dir", str(run_dir))
            artifacts["elapsed_seconds"] = elapsed_seconds
            metadata = dict(response.metadata)
            metadata.setdefault("event_count", len(response.events))
            completed_task = self.manager.complete(
                task_id,
                output=response.output,
                artifacts=artifacts,
                metadata=metadata,
            )
            event_logger.emit(
                "task_completed",
                task_id=task_id,
                agent_id=task.agent_id,
                payload={"elapsed_seconds": elapsed_seconds},
            )
            return completed_task
        except Exception as exc:
            elapsed_seconds = round(perf_counter() - started, 3)
            failed_task = self.manager.fail(task_id, str(exc))
            event_logger.emit(
                "task_failed",
                task_id=task_id,
                agent_id=task.agent_id,
                payload={"error": str(exc), "elapsed_seconds": elapsed_seconds},
            )
            return failed_task
