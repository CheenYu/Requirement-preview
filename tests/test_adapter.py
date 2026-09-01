from pathlib import Path

import pytest

from backend.agents.adapters.requirement_pre_review import RequirementPreReviewAgent
from backend.agents.profiles import PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID, build_requirement_pre_review_profile
from backend.agents.registry import AgentRegistry
from backend.events import event_logger
from backend.models import AgentRequest, TaskCreateRequest, TaskStatus
from backend.tasks.manager import TaskManager
from backend.tasks.runner import TaskRunner


def test_requirement_pre_review_profile_contains_workflow_metadata(workflow_config) -> None:
    profile = build_requirement_pre_review_profile(config=workflow_config)

    assert profile.agent_id == PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID
    assert profile.metadata["workflow_entrypoint"].endswith("run_workflow")
    assert profile.metadata["provider_agnostic"] is True
    assert len(profile.metadata["child_agents"]) == 4


def test_adapter_returns_agent_response_with_workflow_artifacts(
    tmp_path: Path,
    requirement_agent: RequirementPreReviewAgent,
    clear_requirement_text: str,
) -> None:
    event_logger.clear()
    response = requirement_agent.run(
        AgentRequest(
            input=clear_requirement_text,
            context={"task_run_dir": str(tmp_path / "adapter-run")},
            metadata={
                "title": "订单导出预审",
                "target_users": ["运营", "客服"],
                "explicit_constraints": ["本月上线", "复用现有权限模型"],
            },
            task_id="adapter-task",
        )
    )

    assert response.agent_id == PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID
    assert "## 需求摘要" in response.output
    assert response.artifacts["gate_opened"] is True
    assert response.artifacts["artifact_paths"]["input_text"].endswith("input.txt")
    assert response.artifacts["metrics"]["tool_failure_count"] == 0
    assert Path(response.artifacts["artifact_paths"]["report_markdown"]).exists()
    assert response.metadata["workflow_status"] == "completed"
    assert response.metadata["quality_passed"] is True
    assert response.metadata["risk_count"] >= 1
    assert response.metadata["decision_count"] >= 1
    assert response.metadata["elapsed_ms"] >= 0
    assert any(event["type"] == "workflow_completed" for event in response.events)


def test_registry_and_task_runner_can_execute_agent_by_agent_id(
    workflow_config,
    ambiguous_requirement_text: str,
) -> None:
    event_logger.clear()
    registry = AgentRegistry()
    registry.register(RequirementPreReviewAgent(config=workflow_config))
    manager = TaskManager()
    runner = TaskRunner(registry, manager)

    task = manager.create(
        TaskCreateRequest(
            title="模糊需求预审",
            input=ambiguous_requirement_text,
            agent_id=PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID,
            metadata={"title": "模糊需求预审"},
        )
    )
    completed = runner.run(task.task_id)

    assert registry.has(PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID) is True
    assert completed.status == TaskStatus.completed
    assert completed.output is not None
    assert completed.artifacts["gate_opened"] is False
    assert Path(completed.artifacts["artifact_paths"]["report_json"]).exists()


def test_registry_raises_for_unknown_agent_id() -> None:
    registry = AgentRegistry()

    with pytest.raises(KeyError):
        registry.get("missing-agent")
