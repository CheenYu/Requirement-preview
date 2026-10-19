"""Minimal regression harness for requirement pre-review workflow changes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.requirement_pre_review.src.config import WorkflowConfig, load_workflow_config
from agents.requirement_pre_review.src.schemas import EvaluationResult
from agents.requirement_pre_review.src.workflow import WorkflowStageError, run_workflow
from evals.metrics import EvalSummary, build_evaluation_result, render_summary_markdown, summarize_results


DEFAULT_CASES_DIR = Path(__file__).resolve().parent / "cases"
DEFAULT_OUTPUTS_DIR = Path(__file__).resolve().parent / "outputs"


class EvalCase(BaseModel):
    case_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    requirement_text: str = Field(..., min_length=1)
    target_users: list[str] = Field(default_factory=list)
    explicit_constraints: list[str] = Field(default_factory=list)
    supplemental_context: list[str] = Field(default_factory=list)
    expected_gate_opened: bool
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_path: str = ""

    @field_validator("case_id", "title", "requirement_text")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("required text fields cannot be empty")
        return cleaned

    def build_workflow_payload(self, *, run_dir: Path) -> dict[str, Any]:
        return {
            "title": self.title,
            "requirement_text": self.requirement_text,
            "target_users": self.target_users,
            "explicit_constraints": self.explicit_constraints,
            "supplemental_context": self.supplemental_context,
            "metadata": {
                **self.metadata,
                "eval_case_id": self.case_id,
                "eval_tags": self.tags,
                "eval_notes": self.notes,
            },
            "task_id": f"eval-{self.case_id}",
            "run_dir": str(run_dir),
        }


class EvalCaseRunResult(BaseModel):
    case_id: str
    title: str
    source_path: str = ""
    tags: list[str] = Field(default_factory=list)
    expected_gate_opened: bool
    actual_gate_opened: bool
    gate_match: bool
    workflow_status: str
    workflow_summary: str
    clarity_score: int = 0
    quality_score: int = 0
    evaluation: EvaluationResult
    run_dir: str
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    failure_reason: str | None = None


class EvalSuiteReport(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.now)
    cases_dir: str
    output_dir: str
    selected_case_ids: list[str] = Field(default_factory=list)
    summary: EvalSummary
    results: list[EvalCaseRunResult] = Field(default_factory=list)


def load_eval_cases(cases_dir: str | Path = DEFAULT_CASES_DIR) -> list[EvalCase]:
    directory = Path(cases_dir)
    if not directory.exists():
        raise FileNotFoundError(f"Cases directory not found: {directory}")

    case_paths = sorted(path for path in directory.glob("*.json") if path.is_file())
    if not case_paths:
        raise FileNotFoundError(f"No eval case files found in: {directory}")

    cases: list[EvalCase] = []
    seen_case_ids: set[str] = set()
    for path in case_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        case = EvalCase.model_validate({**payload, "source_path": str(path)})
        if case.case_id in seen_case_ids:
            raise ValueError(f"Duplicate eval case_id detected: {case.case_id}")
        seen_case_ids.add(case.case_id)
        cases.append(case)
    return cases


def run_eval_suite(
    *,
    cases_dir: str | Path = DEFAULT_CASES_DIR,
    output_dir: str | Path | None = None,
    config: WorkflowConfig | None = None,
    case_ids: list[str] | None = None,
) -> EvalSuiteReport:
    cases = load_eval_cases(cases_dir)
    selected_case_ids = [item.strip() for item in (case_ids or []) if item.strip()]
    if selected_case_ids:
        requested = set(selected_case_ids)
        cases = [case for case in cases if case.case_id in requested]
        missing = sorted(requested - {case.case_id for case in cases})
        if missing:
            raise ValueError(f"Unknown eval case_id(s): {', '.join(missing)}")

    suite_output_dir = _prepare_suite_output_dir(output_dir)
    case_output_root = suite_output_dir / "cases"
    case_output_root.mkdir(parents=True, exist_ok=True)

    workflow_config = config or load_workflow_config()
    results = [
        _run_single_case(case, workflow_config=workflow_config, case_output_root=case_output_root)
        for case in cases
    ]
    evaluation_results = [item.evaluation for item in results]
    summary = summarize_results(
        evaluation_results,
        expected_gates={item.case_id: item.expected_gate_opened for item in results},
    )
    report = EvalSuiteReport(
        cases_dir=str(Path(cases_dir)),
        output_dir=str(suite_output_dir),
        selected_case_ids=selected_case_ids,
        summary=summary,
        results=results,
    )
    _persist_suite_outputs(report)
    return report


def _prepare_suite_output_dir(output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        path = Path(output_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = DEFAULT_OUTPUTS_DIR / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_single_case(
    case: EvalCase,
    *,
    workflow_config: WorkflowConfig,
    case_output_root: Path,
) -> EvalCaseRunResult:
    case_dir = case_output_root / case.case_id
    workflow_run_dir = case_dir / "workflow_artifacts"
    case_dir.mkdir(parents=True, exist_ok=True)

    try:
        workflow_result = run_workflow(
            case.build_workflow_payload(run_dir=workflow_run_dir),
            config=workflow_config,
        )
        evaluation = build_evaluation_result(
            case_id=case.case_id,
            report_payload=workflow_result.report_json.model_dump(mode="json"),
            report_markdown=workflow_result.report_markdown,
            gate_opened=workflow_result.gate_opened,
            expected_gate_opened=case.expected_gate_opened,
            tool_error_count=int(workflow_result.metrics.get("tool_failure_count", 0)),
            tool_call_count=int(workflow_result.metrics.get("tool_call_count", len(workflow_result.tool_calls))),
            workflow_latency_ms=int(workflow_result.metrics.get("elapsed_ms", 0)),
        )
        case_result = EvalCaseRunResult(
            case_id=case.case_id,
            title=case.title,
            source_path=case.source_path,
            tags=case.tags,
            expected_gate_opened=case.expected_gate_opened,
            actual_gate_opened=workflow_result.gate_opened,
            gate_match=workflow_result.gate_opened == case.expected_gate_opened,
            workflow_status=workflow_result.status,
            workflow_summary=workflow_result.summary,
            clarity_score=int(workflow_result.metrics.get("clarity_score", 0)),
            quality_score=int(workflow_result.metrics.get("quality_score", 0)),
            evaluation=evaluation,
            run_dir=workflow_result.run_dir,
            artifact_paths=workflow_result.artifact_paths,
        )
    except WorkflowStageError as exc:
        case_result = _build_failed_case_result(
            case=case,
            workflow_run_dir=workflow_run_dir,
            failure_reason=f"{exc.stage}: {exc.message}",
        )
    except Exception as exc:  # pragma: no cover - defensive layer
        case_result = _build_failed_case_result(
            case=case,
            workflow_run_dir=workflow_run_dir,
            failure_reason=str(exc),
        )

    _write_json(case_dir / "case_result.json", case_result.model_dump(mode="json"))
    return case_result


def _build_failed_case_result(
    *,
    case: EvalCase,
    workflow_run_dir: Path,
    failure_reason: str,
) -> EvalCaseRunResult:
    evaluation = build_evaluation_result(
        case_id=case.case_id,
        report_payload={},
        report_markdown="",
        gate_opened=False,
        expected_gate_opened=case.expected_gate_opened,
        tool_error_count=1,
        tool_call_count=0,
        workflow_latency_ms=0,
    )
    return EvalCaseRunResult(
        case_id=case.case_id,
        title=case.title,
        source_path=case.source_path,
        tags=case.tags,
        expected_gate_opened=case.expected_gate_opened,
        actual_gate_opened=False,
        gate_match=(False == case.expected_gate_opened),
        workflow_status="failed",
        workflow_summary=f"Workflow execution failed: {failure_reason}",
        evaluation=evaluation,
        run_dir=str(workflow_run_dir),
        artifact_paths={},
        failure_reason=failure_reason,
    )


def _persist_suite_outputs(report: EvalSuiteReport) -> None:
    output_dir = Path(report.output_dir)
    evaluation_results = [item.evaluation for item in report.results]
    _write_json(output_dir / "eval_report.json", report.model_dump(mode="json"))
    (output_dir / "eval_summary.md").write_text(
        render_summary_markdown(report.summary, evaluation_results),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the minimal regression harness for requirement pre-review workflow.")
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR), help="Directory containing eval case JSON files.")
    parser.add_argument("--output-dir", default=None, help="Directory for suite-level eval outputs.")
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        default=None,
        help="Run only the specified case_id. Repeat this flag to run multiple cases.",
    )
    args = parser.parse_args()

    report = run_eval_suite(
        cases_dir=args.cases_dir,
        output_dir=args.output_dir,
        case_ids=args.case_ids,
    )
    print(f"eval harness completed: {report.output_dir}")
    print(f"total cases: {report.summary.total_cases}")
    print(f"schema pass rate: {report.summary.schema_pass_rate:.2%}")
    print(f"gate consistency: {report.summary.gate_decision_consistency:.2%}")
    print(f"tool error rate: {report.summary.tool_error_rate:.2%}")


if __name__ == "__main__":
    main()
