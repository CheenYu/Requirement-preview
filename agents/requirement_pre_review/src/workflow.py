"""Workflow core for requirement clarification and pre-review runs."""

from __future__ import annotations

import json
from datetime import datetime
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.events import event_logger

from .agents import RequirementPreReviewTeam, build_agent_team
from .config import WorkflowConfig, load_workflow_config
from .formatter import (
    build_analysis_markdown,
    build_architecture_markdown,
    build_report_json,
    build_risk_review_markdown,
)
from .providers import LLMCallRecord, OpenAICompatibleProvider, build_llm_provider
from .schemas import RequirementReviewReport, SolutionPlan, WorkflowIntermediateArtifacts
from .storage import WorkflowArtifactStore
from .tool_contracts import (
    RequirementAuditOutput,
    RiskTaxonomyCheckOutput,
    ToolCallRecord,
    ToolExecutionContext,
)
from .tools import ToolRuntime, invoke_tool


class WorkflowInput(BaseModel):
    title: str = ""
    requirement_text: str = Field(..., min_length=1)
    supplemental_context: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    explicit_constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    run_dir: str | None = None

    @field_validator("requirement_text")
    @classmethod
    def validate_requirement_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("requirement_text cannot be empty")
        return cleaned


class StageBoundarySnapshot(BaseModel):
    stage: str
    confirmed_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    gate_opened: bool = False


class WorkflowStageRecord(BaseModel):
    stage: str
    agent_id: str
    status: Literal["completed", "skipped", "failed"]
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0)
    summary: str = ""
    tool_names: list[str] = Field(default_factory=list)
    error: str | None = None


class WorkflowResult(BaseModel):
    workflow_id: str
    task_id: str | None = None
    status: Literal["completed", "failed"]
    run_dir: str
    summary: str
    clarity: dict[str, Any]
    gate_opened: bool
    quality_check: dict[str, Any]
    report_json: RequirementReviewReport
    report_markdown: str
    stage_results: list[WorkflowStageRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    intermediate_artifacts: WorkflowIntermediateArtifacts = Field(default_factory=WorkflowIntermediateArtifacts)
    decision_log: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowStageError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


class RequirementPreReviewWorkflow:
    def __init__(
        self,
        *,
        config: WorkflowConfig | None = None,
        tool_runtime: ToolRuntime | None = None,
        team: RequirementPreReviewTeam | None = None,
        llm_provider: OpenAICompatibleProvider | None = None,
    ) -> None:
        self.config = config or load_workflow_config()
        self.tool_runtime = tool_runtime or ToolRuntime(config=self.config)
        self.team = team or build_agent_team(config=self.config, tool_runtime=self.tool_runtime)
        self.llm_provider = llm_provider or build_llm_provider(self.config)

    def run(self, payload: WorkflowInput | dict[str, Any]) -> WorkflowResult:
        try:
            workflow_input = WorkflowInput.model_validate(payload)
        except ValidationError as exc:
            raise WorkflowStageError("input_validation", str(exc)) from exc
        store = self._build_store(workflow_input)
        workflow_id = uuid4().hex
        stage_results: list[WorkflowStageRecord] = []
        boundary_snapshots: list[StageBoundarySnapshot] = []
        llm_calls: list[LLMCallRecord] = []
        started_at = perf_counter()
        self.tool_runtime.clear_history()

        event_logger.emit(
            "workflow_started",
            task_id=workflow_input.task_id,
            agent_id="requirement_pre_review_workflow",
            payload={"workflow_id": workflow_id, "run_dir": str(store.run_dir)},
        )

        try:
            artifact_paths: dict[str, str] = {}
            artifact_paths.update(store.persist_input(workflow_input.model_dump(mode="json")))

            audit_result = self._run_tool_stage(
                stage="requirement_audit",
                agent_id="requirement_analyst",
                tool_name="requirement-audit",
                payload={
                    "title": workflow_input.title,
                    "requirement_text": workflow_input.requirement_text,
                    "supplemental_context": workflow_input.supplemental_context,
                    "target_users": workflow_input.target_users,
                    "explicit_constraints": workflow_input.explicit_constraints,
                    "max_open_questions": self.config.max_open_questions,
                },
                task_id=workflow_input.task_id,
                stage_results=stage_results,
            )
            audit_output = audit_result.output or {}
            llm_audit = self._run_llm_stage(
                stage="llm_requirement_analysis",
                agent_id="requirement_analyst",
                payload={
                    "title": workflow_input.title,
                    "requirement_text": workflow_input.requirement_text,
                    "supplemental_context": workflow_input.supplemental_context,
                    "target_users": workflow_input.target_users,
                    "explicit_constraints": workflow_input.explicit_constraints,
                    "max_open_questions": self.config.max_open_questions,
                    "deterministic_baseline": audit_output,
                },
                output_model=RequirementAuditOutput,
                task_id=workflow_input.task_id,
                llm_calls=llm_calls,
                stage_results=stage_results,
            )
            if llm_audit is not None:
                audit_output = llm_audit.model_dump(mode="json")

            clarity_result = self._run_tool_stage(
                stage="clarity_gate",
                agent_id="requirement_analyst",
                tool_name="clarity-score",
                payload={
                    "requirement_text": workflow_input.requirement_text,
                    "audit_result": audit_output,
                    "threshold": self.config.clarity_gate_threshold,
                },
                task_id=workflow_input.task_id,
                stage_results=stage_results,
            )

            clarity_output = clarity_result.output or {}
            boundary_snapshots.append(
                self._build_boundary_snapshot(
                    stage="requirement_analyst",
                    audit_output=audit_output,
                    gate_opened=bool(clarity_output.get("passed", False)),
                )
            )
            analysis_markdown = build_analysis_markdown(
                self._validate_model("audit", audit_output),
                self._validate_model("clarity", clarity_output),
            )

            gate_opened = bool(clarity_output.get("passed", False))

            solution_plan: SolutionPlan | None = None
            if gate_opened:
                solution_plan = self._run_llm_stage(
                    stage="llm_solution_design",
                    agent_id="solution_architect",
                    payload={
                        "title": workflow_input.title,
                        "requirement_text": workflow_input.requirement_text,
                        "audit": audit_output,
                        "clarity": clarity_output,
                    },
                    output_model=SolutionPlan,
                    task_id=workflow_input.task_id,
                    llm_calls=llm_calls,
                    stage_results=stage_results,
                )

            risk_input_summary = (
                "门禁未通过，方案阶段仅保留澄清占位。"
                if not gate_opened
                else json.dumps(
                    solution_plan.model_dump(mode="json") if solution_plan is not None else {"status": "gate_opened"},
                    ensure_ascii=False,
                )
            )
            provisional_risk_result = self._run_tool_stage(
                stage="risk_review",
                agent_id="risk_reviewer",
                tool_name="risk-taxonomy-check",
                payload={
                    "requirement_text": workflow_input.requirement_text,
                    "solution_summary": risk_input_summary,
                    "open_questions": audit_output.get("open_questions", []),
                    "max_risks": self.config.max_risks_per_run,
                },
                task_id=workflow_input.task_id,
                stage_results=stage_results,
            )
            risk_output = provisional_risk_result.output or {}
            llm_risk = self._run_llm_stage(
                stage="llm_risk_review",
                agent_id="risk_reviewer",
                payload={
                    "title": workflow_input.title,
                    "requirement_text": workflow_input.requirement_text,
                    "audit": audit_output,
                    "clarity": clarity_output,
                    "solution_plan": solution_plan.model_dump(mode="json") if solution_plan is not None else None,
                    "max_risks": self.config.max_risks_per_run,
                    "deterministic_baseline": risk_output,
                },
                output_model=RiskTaxonomyCheckOutput,
                task_id=workflow_input.task_id,
                llm_calls=llm_calls,
                stage_results=stage_results,
            )
            if llm_risk is not None:
                risk_output = llm_risk.model_dump(mode="json")

            report_json = build_report_json(
                requirement_text=workflow_input.requirement_text,
                audit_output=self._validate_model("audit", audit_output),
                clarity_output=self._validate_model("clarity", clarity_output),
                risk_output=self._validate_model("risk", risk_output),
                solution_plan=solution_plan,
            )
            boundary_snapshots.append(
                self._build_boundary_snapshot(
                    stage="solution_architect",
                    audit_output=audit_output,
                    gate_opened=gate_opened,
                    assumptions=[] if gate_opened else ["技术方案未展开，仅保留待澄清占位。"],
                )
            )
            architecture_markdown = build_architecture_markdown(report_json, gate_opened=gate_opened)
            stage_results.append(
                self._make_stage_record(
                    stage="solution_design",
                    agent_id="solution_architect",
                    status="completed" if gate_opened else "skipped",
                    started_at=datetime.now(),
                    finished_at=datetime.now(),
                    summary="方案草案已生成。" if gate_opened else "清晰度门禁未通过，方案阶段跳过详细展开。",
                    tool_names=[],
                )
            )

            risk_review_markdown = build_risk_review_markdown(
                self._validate_model("risk", risk_output)
            )
            boundary_snapshots.append(
                self._build_boundary_snapshot(
                    stage="risk_reviewer",
                    audit_output=audit_output,
                    gate_opened=gate_opened,
                )
            )

            markdown_export = self._run_tool_stage(
                stage="report_export_markdown",
                agent_id="report_synthesizer",
                tool_name="report-export",
                payload={
                    "report_json": report_json.model_dump(mode="json"),
                    "format": "markdown",
                    "title": workflow_input.title or "需求澄清与方案预审报告",
                },
                task_id=workflow_input.task_id,
                stage_results=stage_results,
            )
            json_export = self._run_tool_stage(
                stage="report_export_json",
                agent_id="report_synthesizer",
                tool_name="report-export",
                payload={
                    "report_json": report_json.model_dump(mode="json"),
                    "format": "json",
                    "title": workflow_input.title or "需求澄清与方案预审报告",
                },
                task_id=workflow_input.task_id,
                stage_results=stage_results,
            )
            report_markdown = (markdown_export.output or {}).get("content", "")
            report_json_text = (json_export.output or {}).get("content", json.dumps(report_json.model_dump(mode="json"), ensure_ascii=False))

            quality_result = self._run_tool_stage(
                stage="report_quality_check",
                agent_id="report_synthesizer",
                tool_name="report-quality-check",
                payload={
                    "report_markdown": report_markdown,
                    "report_json": report_json.model_dump(mode="json"),
                },
                task_id=workflow_input.task_id,
                stage_results=stage_results,
            )
            boundary_snapshots.append(
                self._build_boundary_snapshot(
                    stage="report_synthesizer",
                    audit_output=audit_output,
                    gate_opened=gate_opened,
                )
            )

            intermediate_artifacts = WorkflowIntermediateArtifacts(
                audit=audit_output,
                clarity=clarity_output,
                analysis_markdown=analysis_markdown,
                architecture_markdown=architecture_markdown,
                risk_review_markdown=risk_review_markdown,
            )

            artifact_paths.update(store.persist_intermediate_artifacts(intermediate_artifacts))
            tool_call_records = self.tool_runtime.list_call_records()
            tool_failure_count = sum(1 for item in tool_call_records if not item.success)
            llm_failure_count = sum(1 for item in llm_calls if not item.success)
            llm_total_tokens = sum(item.total_tokens or 0 for item in llm_calls)
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            metrics = {
                "clarity_score": clarity_output.get("score", 0),
                "clarity_threshold": clarity_output.get("threshold", self.config.clarity_gate_threshold),
                "gate_opened": gate_opened,
                "risk_count": len(report_json.risks),
                "decision_count": len(report_json.decisions),
                "tool_call_count": len(tool_call_records),
                "tool_failure_count": tool_failure_count,
                "llm_enabled": self.llm_provider is not None,
                "llm_call_count": len(llm_calls),
                "llm_failure_count": llm_failure_count,
                "llm_total_tokens": llm_total_tokens,
                "quality_score": (quality_result.output or {}).get("score", 0),
                "quality_passed": (quality_result.output or {}).get("passed", False),
                "elapsed_ms": elapsed_ms,
            }
            artifact_paths.update(
                store.persist_report(
                    report=report_json,
                    report_markdown=report_markdown,
                    report_json_text=report_json_text,
                    decision_log=[item.model_dump(mode="json") for item in report_json.decisions],
                    quality_check=quality_result.output or {},
                    tool_calls=tool_call_records,
                    meta={
                        "workflow_id": workflow_id,
                        "task_id": workflow_input.task_id,
                        "title": workflow_input.title,
                        "metrics": metrics,
                        "boundary_snapshots": [item.model_dump(mode="json") for item in boundary_snapshots],
                        "llm_calls": [item.model_dump(mode="json") for item in llm_calls],
                        "function_interface_boundary": {
                            "provider_agnostic": self.team.function_boundary.provider_agnostic,
                            "native_function_calling_required": self.team.function_boundary.native_function_calling_required,
                        },
                    },
                    stage_results=[item.model_dump(mode="json") for item in stage_results],
                )
            )
            artifact_paths["artifact_index"] = store.persist_index(artifact_paths)

            summary = (
                f"需求清晰度 {clarity_output.get('score', 0)}/{clarity_output.get('threshold', self.config.clarity_gate_threshold)}，"
                f"{'通过' if gate_opened else '未通过'}门禁；"
                f"识别风险 {len(report_json.risks)} 个；"
                f"工具调用 {metrics['tool_call_count']} 次，失败 {metrics['tool_failure_count']} 次。"
            )

            result = WorkflowResult(
                workflow_id=workflow_id,
                task_id=workflow_input.task_id,
                status="completed",
                run_dir=str(store.run_dir),
                summary=summary,
                clarity=clarity_output,
                gate_opened=gate_opened,
                quality_check=quality_result.output or {},
                report_json=RequirementReviewReport.model_validate_json(report_json_text),
                report_markdown=report_markdown,
                stage_results=stage_results,
                tool_calls=tool_call_records,
                artifact_paths=artifact_paths,
                intermediate_artifacts=intermediate_artifacts,
                decision_log=[item.model_dump(mode="json") for item in report_json.decisions],
                metrics=metrics,
                metadata={
                    "elapsed_ms": elapsed_ms,
                    "team_execution_order": self.team.execution_order,
                    "boundary_snapshots": [item.model_dump(mode="json") for item in boundary_snapshots],
                    "llm_provider": "openai-compatible" if self.llm_provider is not None else None,
                    "llm_model": self.config.llm.model if self.llm_provider is not None else None,
                    "llm_calls": [item.model_dump(mode="json") for item in llm_calls],
                    "artifact_count": len(artifact_paths),
                },
            )
            event_logger.emit(
                "workflow_completed",
                task_id=workflow_input.task_id,
                agent_id="requirement_pre_review_workflow",
                payload={"workflow_id": workflow_id, "elapsed_ms": elapsed_ms, "gate_opened": gate_opened},
            )
            return result
        except ValidationError as exc:
            raise WorkflowStageError("report_validation", str(exc)) from exc
        except WorkflowStageError:
            raise
        except Exception as exc:
            raise WorkflowStageError("workflow", str(exc)) from exc

    def _build_store(self, workflow_input: WorkflowInput) -> WorkflowArtifactStore:
        if workflow_input.run_dir:
            return WorkflowArtifactStore(workflow_input.run_dir)
        return WorkflowArtifactStore.from_task(workflow_input.task_id)

    def _run_llm_stage(
        self,
        *,
        stage: str,
        agent_id: str,
        payload: dict[str, Any],
        output_model: type[BaseModel],
        task_id: str | None,
        llm_calls: list[LLMCallRecord],
        stage_results: list[WorkflowStageRecord],
    ) -> BaseModel | None:
        if self.llm_provider is None:
            return None

        started_at = datetime.now()
        generation = self.llm_provider.generate_structured(
            stage=stage,
            system_prompt=self.team.get_agent(agent_id).system_prompt,
            payload=payload,
            output_model=output_model,
        )
        finished_at = datetime.now()
        llm_calls.append(generation.record)
        stage_results.append(
            self._make_stage_record(
                stage=stage,
                agent_id=agent_id,
                status="completed" if generation.output is not None else "failed",
                started_at=started_at,
                finished_at=finished_at,
                summary=(
                    "模型结构化输出已通过 Schema 校验。"
                    if generation.output is not None
                    else "模型调用失败或输出无效，已使用确定性规则结果降级。"
                ),
                tool_names=[f"llm:{self.config.llm.model}"],
                error=generation.record.error,
            )
        )
        event_logger.emit(
            "llm_invocation",
            task_id=task_id,
            agent_id=agent_id,
            payload=generation.record.model_dump(mode="json"),
        )
        return generation.output

    def _run_tool_stage(
        self,
        *,
        stage: str,
        agent_id: str,
        tool_name: str,
        payload: dict[str, Any],
        task_id: str | None,
        stage_results: list[WorkflowStageRecord],
    ):
        started_at = datetime.now()
        try:
            result = invoke_tool(
                tool_name,
                payload,
                context=ToolExecutionContext(task_id=task_id, agent_id=agent_id, stage=stage),
                runtime=self.tool_runtime,
            )
            finished_at = datetime.now()
            stage_results.append(
                self._make_stage_record(
                    stage=stage,
                    agent_id=agent_id,
                    status="completed" if result.success else "failed",
                    started_at=started_at,
                    finished_at=finished_at,
                    summary="工具执行成功。" if result.success else f"工具执行失败，已使用兜底：{tool_name}",
                    tool_names=[tool_name],
                    error=result.error.message if result.error else None,
                )
            )
            if result.output is None:
                raise WorkflowStageError(stage, f"{tool_name} returned no output")
            return result
        except WorkflowStageError:
            raise
        except Exception as exc:
            finished_at = datetime.now()
            stage_results.append(
                self._make_stage_record(
                    stage=stage,
                    agent_id=agent_id,
                    status="failed",
                    started_at=started_at,
                    finished_at=finished_at,
                    summary=f"阶段失败：{tool_name}",
                    tool_names=[tool_name],
                    error=str(exc),
                )
            )
            raise WorkflowStageError(stage, str(exc)) from exc

    def _make_stage_record(
        self,
        *,
        stage: str,
        agent_id: str,
        status: Literal["completed", "skipped", "failed"],
        started_at: datetime,
        finished_at: datetime,
        summary: str,
        tool_names: list[str],
        error: str | None = None,
    ) -> WorkflowStageRecord:
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        return WorkflowStageRecord(
            stage=stage,
            agent_id=agent_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(duration_ms, 0),
            summary=summary,
            tool_names=tool_names,
            error=error,
        )

    def _build_boundary_snapshot(
        self,
        *,
        stage: str,
        audit_output: dict[str, Any],
        gate_opened: bool,
        assumptions: list[str] | None = None,
    ) -> StageBoundarySnapshot:
        return StageBoundarySnapshot(
            stage=stage,
            confirmed_facts=audit_output.get("confirmed_facts", []),
            assumptions=assumptions or [],
            open_questions=[item.get("question") for item in audit_output.get("open_questions", [])],
            constraints=[item for item in audit_output.get("confirmed_facts", []) if str(item).startswith("约束")],
            gate_opened=gate_opened,
        )

    def _validate_model(self, model_type: str, payload: dict[str, Any]):
        if model_type == "audit":
            from .tool_contracts import RequirementAuditOutput

            return RequirementAuditOutput.model_validate(payload)
        if model_type == "clarity":
            from .tool_contracts import ClarityScoreOutput

            return ClarityScoreOutput.model_validate(payload)
        if model_type == "risk":
            from .tool_contracts import RiskTaxonomyCheckOutput

            return RiskTaxonomyCheckOutput.model_validate(payload)
        raise ValueError(f"Unsupported model type: {model_type}")


def run_workflow(
    payload: WorkflowInput | dict[str, Any],
    *,
    config: WorkflowConfig | None = None,
    tool_runtime: ToolRuntime | None = None,
    llm_provider: OpenAICompatibleProvider | None = None,
) -> WorkflowResult:
    workflow = RequirementPreReviewWorkflow(
        config=config,
        tool_runtime=tool_runtime,
        llm_provider=llm_provider,
    )
    return workflow.run(payload)
