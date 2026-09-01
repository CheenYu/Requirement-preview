"""Structured in-memory event logging for backend task execution."""

from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any
from uuid import uuid4


class EventLogger:
    """Collects development-time runtime events in memory."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = Lock()

    def emit(
        self,
        event_type: str,
        *,
        task_id: str | None = None,
        agent_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": uuid4().hex,
            "type": event_type,
            "task_id": task_id,
            "agent_id": agent_id,
            "timestamp": datetime.now().isoformat(),
            "payload": payload or {},
        }
        with self._lock:
            self._events.append(event)
        return event

    def list_events(self, *, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if task_id is not None:
            events = [event for event in events if event["task_id"] == task_id]
        return events[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


event_logger = EventLogger()
