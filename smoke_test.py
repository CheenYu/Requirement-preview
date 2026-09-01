from __future__ import annotations

import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated; install `httpx2` instead\.",
)

from fastapi.testclient import TestClient

from agents.requirement_pre_review.src.config import WorkflowConfig, WorkflowLLMSettings
from agents.requirement_pre_review.src.workflow import run_workflow
from backend.agents.adapters.requirement_pre_review import RequirementPreReviewAgent
from backend.agents.profiles import PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID
from backend.agents.registry import AgentRegistry
from backend.config import AppConfig, LLMConfig
from backend.main import create_app
from backend.tasks.manager import TaskManager
from backend.tasks.runner import TaskRunner


REQUIRED_PATHS = [
    "backend",
    "backend/agents",
    "backend/agents/adapters",
    "backend/tasks",
    "frontend",
    "frontend/index.html",
    "frontend/app.js",
    "frontend/styles.css",
    "agents/requirement_pre_review/src",
    "docs",
    "evals",
    "tests",
    "data/.gitkeep",
]

SAMPLE_REQUIREMENT = (
    "目标是降低客服处理订单导出的人工成本。\n"
    "运营和客服需要在后台按时间范围筛选并导出订单。\n"
    "本期范围包括筛选、导出、失败重试和导出日志。\n"
    "需要复用现有权限模型，并在本月上线。\n"
    "依赖订单 API 和导出文件存储。\n"
    "性能要求是 1000 条订单 3 分钟内导出完成。\n"
    "验收标准是运营可以按订单状态筛选并成功下载导出结果。"
)


def build_workflow_config() -> WorkflowConfig:
    return WorkflowConfig(
        llm=WorkflowLLMSettings(
            model="smoke-test-model",
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


def verify_project_layout(root: Path) -> None:
    missing = [path for path in REQUIRED_PATHS if not (root / path).exists()]
    if missing:
        raise SystemExit(f"Missing paths: {missing}")


def run_workflow_smoke(root: Path) -> None:
    config = build_workflow_config()
    run_dir = root / "data" / "smoke_workflow_run"
    result = run_workflow(
        {
            "title": "smoke-workflow",
            "requirement_text": SAMPLE_REQUIREMENT,
            "target_users": ["运营", "客服"],
            "explicit_constraints": ["本月上线", "复用现有权限模型"],
            "run_dir": str(run_dir),
            "task_id": "smoke-workflow-task",
        },
        config=config,
    )
    if result.status != "completed":
        raise SystemExit("Workflow smoke test did not complete successfully.")
    if not result.gate_opened:
        raise SystemExit("Workflow smoke test unexpectedly failed the clarity gate.")
    if not (run_dir / "report.md").exists():
        raise SystemExit("Workflow smoke test did not persist report.md.")


def run_api_smoke() -> None:
    config = build_workflow_config()
    registry = AgentRegistry()
    registry.register(RequirementPreReviewAgent(config=config))
    manager = TaskManager()
    runner = TaskRunner(registry, manager)

    with tempfile.TemporaryDirectory(prefix="requirement-pre-review-smoke-") as tmp_dir:
        temp_root = Path(tmp_dir)
        app_config = AppConfig(
            host="127.0.0.1",
            port=8000,
            log_level="INFO",
            data_dir=temp_root / "data",
            evals_dir=temp_root / "evals",
            llm=LLMConfig(
                model="smoke-test-model",
                api_key="",
                base_url="https://example.com",
                temperature=0.0,
                timeout_seconds=30,
            ),
        )
        app = create_app(config=app_config, registry=registry, manager=manager, runner=runner)
        with TestClient(app) as client:
            response = client.post(
                "/tasks",
                json={
                    "title": "smoke-api",
                    "input": SAMPLE_REQUIREMENT,
                    "agent_id": PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID,
                    "metadata": {
                        "title": "smoke-api",
                        "target_users": ["运营", "客服"],
                        "explicit_constraints": ["本月上线", "复用现有权限模型"],
                    },
                },
            )
            if response.status_code != 201:
                raise SystemExit("API smoke test failed at task creation.")

            task_id = response.json()["task_id"]
            run_response = client.post(f"/tasks/{task_id}/run", json={"background": False})
            if run_response.status_code != 200 or run_response.json()["status"] != "completed":
                raise SystemExit("API smoke test failed at task execution.")


def main() -> None:
    root = Path(__file__).resolve().parent
    verify_project_layout(root)
    run_workflow_smoke(root)
    run_api_smoke()
    print("phase9 smoke test passed")


if __name__ == "__main__":
    main()
