from pathlib import Path

import pytest

from agents.requirement_pre_review.src import workflow as workflow_module
from agents.requirement_pre_review.src.providers import LLMCallRecord, StructuredGeneration
from agents.requirement_pre_review.src.tool_contracts import ToolInvocationResult
from agents.requirement_pre_review.src.workflow import WorkflowStageError, run_workflow


class FailingLLMProvider:
    def generate_structured(self, *, stage, system_prompt, payload, output_model):
        del system_prompt, payload, output_model
        return StructuredGeneration(
            output=None,
            record=LLMCallRecord(
                stage=stage,
                model="test-model",
                success=False,
                fallback_used=True,
                error="forced provider failure",
            ),
        )


def test_workflow_runs_end_to_end_and_persists_artifacts(
    tmp_path: Path,
    workflow_config,
    clear_requirement_text: str,
) -> None:
    result = run_workflow(
        {
            "title": "订单导出预审",
            "requirement_text": clear_requirement_text,
            "target_users": ["运营", "客服"],
            "explicit_constraints": ["本月上线", "复用现有权限模型"],
            "run_dir": str(tmp_path / "run-clear"),
            "task_id": "task-clear",
        },
        config=workflow_config,
    )

    assert result.status == "completed"
    assert result.gate_opened is True
    assert result.quality_check["passed"] is True
    assert "## 技术方案" in result.report_markdown
    assert len(result.report_json.risks) >= 1
    assert result.metrics["tool_call_count"] >= 4
    assert result.metrics["tool_failure_count"] == 0
    assert result.metrics["risk_count"] == len(result.report_json.risks)
    assert result.metrics["decision_count"] == len(result.report_json.decisions)
    assert result.metrics["elapsed_ms"] >= 0
    assert Path(result.artifact_paths["input_text"]).exists()
    assert Path(result.artifact_paths["meta"]).exists()
    assert Path(result.artifact_paths["report_markdown"]).exists()
    assert Path(result.artifact_paths["report_json"]).exists()
    assert Path(result.artifact_paths["tool_calls"]).exists()
    assert Path(result.artifact_paths["artifact_index"]).exists()
    assert (tmp_path / "run-clear" / "input.txt").read_text(encoding="utf-8").startswith("目标是降低客服处理订单导出的人工成本")


def test_workflow_blocks_solution_detail_when_gate_not_passed(
    tmp_path: Path,
    workflow_config,
    ambiguous_requirement_text: str,
) -> None:
    result = run_workflow(
        {
            "title": "模糊需求",
            "requirement_text": ambiguous_requirement_text,
            "run_dir": str(tmp_path / "run-blocked"),
            "task_id": "task-blocked",
        },
        config=workflow_config,
    )

    assert result.status == "completed"
    assert result.gate_opened is False
    assert "Clarification Gate" == result.report_json.solution_plan.modules[0].name
    assert any(stage.stage == "solution_design" and stage.status == "skipped" for stage in result.stage_results)
    assert "未通过方案预审门禁" in result.report_json.summary


def test_workflow_falls_back_to_rules_when_llm_provider_fails(
    tmp_path: Path,
    workflow_config,
    clear_requirement_text: str,
) -> None:
    result = run_workflow(
        {
            "title": "模型降级测试",
            "requirement_text": clear_requirement_text,
            "run_dir": str(tmp_path / "run-llm-fallback"),
            "task_id": "task-llm-fallback",
        },
        config=workflow_config,
        llm_provider=FailingLLMProvider(),
    )

    assert result.status == "completed"
    assert result.gate_opened is True
    assert result.metrics["llm_call_count"] == 3
    assert result.metrics["llm_failure_count"] == 3
    assert all(item["fallback_used"] for item in result.metadata["llm_calls"])


def test_workflow_rejects_empty_requirement_text(tmp_path: Path, workflow_config) -> None:
    with pytest.raises(WorkflowStageError):
        run_workflow(
            {
                "title": "空输入",
                "requirement_text": "   ",
                "run_dir": str(tmp_path / "run-empty"),
            },
            config=workflow_config,
        )


def test_workflow_wraps_report_schema_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    workflow_config,
    clear_requirement_text: str,
) -> None:
    original_invoke_tool = workflow_module.invoke_tool

    def fake_invoke_tool(tool_name, payload, *, context=None, runtime=None):
        result = original_invoke_tool(tool_name, payload, context=context, runtime=runtime)
        if tool_name == "report-export" and payload.get("format") == "json":
            invalid_output = dict(result.output or {})
            invalid_output["content"] = "not-json"
            result = ToolInvocationResult(
                tool_name=result.tool_name,
                success=result.success,
                output=invalid_output,
                error=result.error,
                record=result.record,
            )
        return result

    monkeypatch.setattr(workflow_module, "invoke_tool", fake_invoke_tool)

    with pytest.raises(WorkflowStageError) as exc_info:
        run_workflow(
            {
                "title": "schema failure",
                "requirement_text": clear_requirement_text,
                "run_dir": str(tmp_path / "run-schema-failure"),
                "task_id": "task-schema-failure",
            },
            config=workflow_config,
        )

    assert exc_info.value.stage == "report_validation"


def test_workflow_wraps_tool_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    workflow_config,
    clear_requirement_text: str,
) -> None:
    original_invoke_tool = workflow_module.invoke_tool

    def failing_invoke_tool(tool_name, payload, *, context=None, runtime=None):
        if tool_name == "risk-taxonomy-check":
            raise RuntimeError("forced tool failure")
        return original_invoke_tool(tool_name, payload, context=context, runtime=runtime)

    monkeypatch.setattr(workflow_module, "invoke_tool", failing_invoke_tool)

    with pytest.raises(WorkflowStageError) as exc_info:
        run_workflow(
            {
                "title": "tool failure",
                "requirement_text": clear_requirement_text,
                "run_dir": str(tmp_path / "run-tool-failure"),
                "task_id": "task-tool-failure",
            },
            config=workflow_config,
        )

    assert exc_info.value.stage == "risk_review"
