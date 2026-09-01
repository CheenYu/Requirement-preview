"""FastAPI backend entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.agents.registry import AgentRegistry, agent_registry
from backend.config import AppConfig, load_app_config
from backend.maintenance import ensure_runtime_dirs
from backend.models import AgentListResponse, HealthResponse, TaskCreateRequest, TaskRecord
from backend.tasks.manager import TaskManager, task_manager
from backend.tasks.runner import TaskRunner


class ErrorResponse(BaseModel):
    error: str
    code: str
    timestamp: datetime = Field(default_factory=datetime.now)


class TaskRunRequest(BaseModel):
    background: bool = True


@asynccontextmanager
async def _lifespan(app: FastAPI):
    config = app.state.app_config
    config.ensure_runtime_dirs()
    ensure_runtime_dirs()
    yield


def create_app(
    *,
    config: AppConfig | None = None,
    registry: AgentRegistry | None = None,
    manager: TaskManager | None = None,
    runner: TaskRunner | None = None,
) -> FastAPI:
    active_config = config or load_app_config()
    active_registry = registry or agent_registry
    active_manager = manager or task_manager
    active_runner = runner or TaskRunner(active_registry, active_manager)

    app = FastAPI(
        title="Requirement Pre-Review Agent API",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.state.app_config = active_config
    app.state.agent_registry = active_registry
    app.state.task_manager = active_manager
    app.state.task_runner = active_runner

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail), "code": "http_error"}
        payload = ErrorResponse(
            error=detail.get("error", "Request failed."),
            code=detail.get("code", "http_error"),
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        payload = ErrorResponse(error=str(exc), code="internal_error")
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload.model_dump(mode="json"))

    @app.get("/health", response_model=HealthResponse)
    def get_health() -> HealthResponse:
        return HealthResponse()

    @app.get("/agents", response_model=AgentListResponse)
    def list_agents() -> AgentListResponse:
        registry_obj: AgentRegistry = app.state.agent_registry
        return AgentListResponse(agents=registry_obj.list_profiles())

    @app.post("/tasks", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
    def create_task(request: TaskCreateRequest) -> TaskRecord:
        registry_obj: AgentRegistry = app.state.agent_registry
        if not registry_obj.has(request.agent_id):
            raise _not_found("agent_not_found", f"Unknown agent_id: {request.agent_id}")
        manager_obj: TaskManager = app.state.task_manager
        return manager_obj.create(request)

    @app.post("/tasks/{task_id}/run", response_model=TaskRecord)
    def run_task(task_id: str, request: TaskRunRequest | None = None) -> TaskRecord:
        request = request or TaskRunRequest()
        manager_obj: TaskManager = app.state.task_manager
        _get_task_or_404(manager_obj, task_id)
        runner_obj: TaskRunner = app.state.task_runner
        if request.background:
            return runner_obj.start_background(task_id)
        return runner_obj.run(task_id)

    @app.get("/tasks/{task_id}", response_model=TaskRecord)
    def get_task(task_id: str) -> TaskRecord:
        manager_obj: TaskManager = app.state.task_manager
        return _get_task_or_404(manager_obj, task_id)

    return app


def _get_task_or_404(manager: TaskManager, task_id: str) -> TaskRecord:
    try:
        return manager.get(task_id)
    except KeyError as exc:
        raise _not_found("task_not_found", f"Unknown task_id: {task_id}") from exc


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": message, "code": code})


app = create_app()


__all__ = ["ErrorResponse", "TaskRunRequest", "app", "create_app"]
