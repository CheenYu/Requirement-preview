from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.requirement_pre_review.src.config import WorkflowConfig, WorkflowLLMSettings
from backend.agents.adapters.requirement_pre_review import RequirementPreReviewAgent
from backend.agents.registry import AgentRegistry
from backend.config import AppConfig, LLMConfig
from backend.main import create_app
from backend.tasks.manager import TaskManager
from backend.tasks.runner import TaskRunner


@pytest.fixture
def workflow_config() -> WorkflowConfig:
    return WorkflowConfig(
        llm=WorkflowLLMSettings(
            model="test-model",
            api_key="",
            base_url="https://example.com",
            temperature=0.0,
            timeout_seconds=30,
        ),
        max_requirement_length=5000,
        clarity_gate_threshold=65,
        max_open_questions=8,
        max_risks_per_run=8,
    )


@pytest.fixture
def clear_requirement_text() -> str:
    return (
        "目标是降低客服处理订单导出的人工成本。\n"
        "运营和客服需要在后台按时间范围筛选并导出订单。\n"
        "本期范围包括筛选、导出、失败重试和导出日志。\n"
        "需要复用现有权限模型，并在本月上线。\n"
        "依赖订单 API 和导出文件存储。\n"
        "性能要求是 1000 条订单 3 分钟内导出完成。\n"
        "验收标准是运营可以按订单状态筛选并成功下载导出结果。"
    )


@pytest.fixture
def ambiguous_requirement_text() -> str:
    return "做一个管理页面，尽快上线。"


@pytest.fixture
def tool_runtime(workflow_config: WorkflowConfig):
    from agents.requirement_pre_review.src.tools import ToolRuntime

    return ToolRuntime(config=workflow_config)


@pytest.fixture
def requirement_agent(workflow_config: WorkflowConfig) -> RequirementPreReviewAgent:
    return RequirementPreReviewAgent(config=workflow_config)


@pytest.fixture
def api_client(tmp_path: Path, workflow_config: WorkflowConfig) -> TestClient:
    registry = AgentRegistry()
    registry.register(RequirementPreReviewAgent(config=workflow_config))
    manager = TaskManager()
    runner = TaskRunner(registry, manager)
    app_config = AppConfig(
        host="127.0.0.1",
        port=8000,
        log_level="INFO",
        data_dir=tmp_path / "data",
        evals_dir=tmp_path / "evals",
        llm=LLMConfig(
            model="test-model",
            api_key="",
            base_url="https://example.com",
            temperature=0.0,
            timeout_seconds=30,
        ),
    )
    app = create_app(config=app_config, registry=registry, manager=manager, runner=runner)
    return TestClient(app)
