"""Platform adapter for the requirement pre-review workflow."""

from __future__ import annotations

from typing import Any

from agents.requirement_pre_review.src.config import WorkflowConfig, load_workflow_config
from agents.requirement_pre_review.src.workflow import RequirementPreReviewWorkflow, WorkflowStageError
from backend.agents.base import BasePlatformAgent
from backend.agents.profiles import build_requirement_pre_review_profile
from backend.events import event_logger
from backend.models import AgentRequest, AgentResponse


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [item.strip() for item in value.splitlines() if item.strip()]
        if items:
            return items
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


class RequirementPreReviewAgent(BasePlatformAgent):
    def __init__(
        self,
        *,
        config: WorkflowConfig | None = None,
        workflow: RequirementPreReviewWorkflow | None = None,
    ) -> None:
        self.config = config or load_workflow_config()
        self.workflow = workflow or RequirementPreReviewWorkflow(config=self.config)
        super().__init__(build_requirement_pre_review_profile(config=self.config))

    def run(self, request: AgentRequest) -> AgentResponse:
        validated_request = self.validate_request(request)
        adapter_start_event = event_logger.emit(
            "adapter_started",
            task_id=validated_request.task_id,
            agent_id=self.agent_id,
            payload={"has_task_run_dir": bool(validated_request.context.get("task_run_dir"))},
        )
        try:
            workflow_result = self.workflow.run(
                {
                    "title": str(validated_request.metadata.get("title", "")).strip(),
                    "requirement_text": validated_request.input,
                    "supplemental_context": _coerce_string_list(validated_request.metadata.get("supplemental_context")),
                    "target_users": _coerce_string_list(validated_request.metadata.get("target_users")),
                    "explicit_constraints": _coerce_string_list(validated_request.metadata.get("explicit_constraints")),
                    "metadata": validated_request.metadata,
                    "task_id": validated_request.task_id,
                    "run_dir": validated_request.context.get("task_run_dir"),
                }
            )
        except WorkflowStageError as exc:
            event_logger.emit(
                "adapter_failed",
                task_id=validated_request.task_id,
                agent_id=self.agent_id,
                payload={"stage": exc.stage, "error": exc.message},
            )
            raise RuntimeError(f"Workflow failed at stage `{exc.stage}`: {exc.message}") from exc

        adapter_complete_event = event_logger.emit(
            "adapter_completed",
            task_id=validated_request.task_id,
            agent_id=self.agent_id,
            payload={
                "workflow_id": workflow_result.workflow_id,
                "gate_opened": workflow_result.gate_opened,
                "quality_passed": workflow_result.quality_check.get("passed", False),
            },
        )
        response_events = self._collect_events(
            task_id=validated_request.task_id,
            fallback=[adapter_start_event, adapter_complete_event],
        )
        return AgentResponse(
            agent_id=self.agent_id,
            output=workflow_result.report_markdown,
            artifacts={
                "workflow_id": workflow_result.workflow_id,
                "run_dir": workflow_result.run_dir,
                "report_markdown": workflow_result.report_markdown,
                "report_json": workflow_result.report_json.model_dump(mode="json"),
                "artifact_paths": workflow_result.artifact_paths,
                "clarity": workflow_result.clarity,
                "gate_opened": workflow_result.gate_opened,
                "quality_check": workflow_result.quality_check,
                "stage_results": [item.model_dump(mode="json") for item in workflow_result.stage_results],
                "tool_calls": [item.model_dump(mode="json") for item in workflow_result.tool_calls],
                "decision_log": workflow_result.decision_log,
                "intermediate_artifacts": workflow_result.intermediate_artifacts.model_dump(mode="json"),
                "metrics": workflow_result.metrics,
            },
            metadata={
                "summary": workflow_result.summary,
                "workflow_status": workflow_result.status,
                "clarity_score": workflow_result.metrics.get("clarity_score", workflow_result.clarity.get("score", 0)),
                "clarity_threshold": workflow_result.metrics.get(
                    "clarity_threshold",
                    workflow_result.clarity.get("threshold", self.config.clarity_gate_threshold),
                ),
                "gate_opened": workflow_result.metrics.get("gate_opened", workflow_result.gate_opened),
                "quality_score": workflow_result.metrics.get("quality_score", workflow_result.quality_check.get("score", 0)),
                "quality_passed": workflow_result.metrics.get(
                    "quality_passed",
                    workflow_result.quality_check.get("passed", False),
                ),
                "risk_count": workflow_result.metrics.get("risk_count", len(workflow_result.report_json.risks)),
                "decision_count": workflow_result.metrics.get("decision_count", len(workflow_result.report_json.decisions)),
                "tool_call_count": workflow_result.metrics.get("tool_call_count", len(workflow_result.tool_calls)),
                "tool_failure_count": workflow_result.metrics.get(
                    "tool_failure_count",
                    sum(1 for item in workflow_result.tool_calls if not item.success),
                ),
                "elapsed_ms": workflow_result.metrics.get("elapsed_ms", workflow_result.metadata.get("elapsed_ms", 0)),
                "stage_count": len(workflow_result.stage_results),
                "artifact_count": workflow_result.metadata.get("artifact_count", len(workflow_result.artifact_paths)),
            },
            events=response_events,
        )

    def _collect_events(self, *, task_id: str | None, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not task_id:
            return fallback
        events = event_logger.list_events(task_id=task_id, limit=500)
        return events or fallback
