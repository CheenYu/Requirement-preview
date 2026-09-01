"""Metrics helpers for the minimal regression evaluation harness."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agents.requirement_pre_review.src.schemas import EvaluationResult, RequirementReviewReport
from agents.requirement_pre_review.src.tool_contracts import FIXED_REPORT_SECTIONS


class EvalSummary(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.now)
    total_cases: int
    schema_pass_rate: float = Field(ge=0.0, le=1.0)
    average_section_completeness: float = Field(ge=0.0, le=100.0)
    gate_decision_consistency: float = Field(ge=0.0, le=1.0)
    tool_error_rate: float = Field(ge=0.0)
    average_workflow_latency_ms: float = Field(ge=0.0)
    passed_cases: int = 0
    gate_mismatch_cases: list[str] = Field(default_factory=list)


def validate_report_schema(report_payload: dict[str, Any]) -> bool:
    try:
        RequirementReviewReport.model_validate(report_payload)
        return True
    except Exception:
        return False


def calculate_section_completeness(report_markdown: str) -> int:
    if not report_markdown.strip():
        return 0
    present_sections = sum(1 for section in FIXED_REPORT_SECTIONS if f"## {section}" in report_markdown)
    return int((present_sections / len(FIXED_REPORT_SECTIONS)) * 100)


def build_evaluation_result(
    *,
    case_id: str,
    report_payload: dict[str, Any],
    report_markdown: str,
    gate_opened: bool,
    expected_gate_opened: bool,
    tool_error_count: int,
    workflow_latency_ms: int,
) -> EvaluationResult:
    return EvaluationResult(
        case_id=case_id,
        schema_passed=validate_report_schema(report_payload),
        section_completeness=calculate_section_completeness(report_markdown),
        gate_opened=gate_opened,
        tool_error_count=tool_error_count,
        workflow_latency_ms=workflow_latency_ms,
    )


def summarize_results(
    results: list[EvaluationResult],
    *,
    expected_gates: dict[str, bool],
) -> EvalSummary:
    if not results:
        return EvalSummary(
            total_cases=0,
            schema_pass_rate=0.0,
            average_section_completeness=0.0,
            gate_decision_consistency=0.0,
            tool_error_rate=0.0,
            average_workflow_latency_ms=0.0,
            passed_cases=0,
            gate_mismatch_cases=[],
        )

    total_cases = len(results)
    schema_pass_count = sum(1 for item in results if item.schema_passed)
    total_tool_errors = sum(item.tool_error_count for item in results)
    total_tool_calls_proxy = total_cases * 5
    gate_mismatches = [
        item.case_id for item in results if expected_gates.get(item.case_id) is not None and item.gate_opened != expected_gates[item.case_id]
    ]
    passed_cases = sum(
        1
        for item in results
        if item.schema_passed
        and item.section_completeness == 100
        and item.tool_error_count == 0
        and item.case_id not in gate_mismatches
    )

    return EvalSummary(
        total_cases=total_cases,
        schema_pass_rate=schema_pass_count / total_cases,
        average_section_completeness=sum(item.section_completeness for item in results) / total_cases,
        gate_decision_consistency=(total_cases - len(gate_mismatches)) / total_cases,
        tool_error_rate=total_tool_errors / total_tool_calls_proxy if total_tool_calls_proxy else 0.0,
        average_workflow_latency_ms=sum(item.workflow_latency_ms for item in results) / total_cases,
        passed_cases=passed_cases,
        gate_mismatch_cases=gate_mismatches,
    )


def render_summary_markdown(summary: EvalSummary, results: list[EvaluationResult]) -> str:
    lines = [
        "# Eval Summary",
        "",
        f"- Generated At: {summary.generated_at.isoformat()}",
        f"- Total Cases: {summary.total_cases}",
        f"- Schema Pass Rate: {summary.schema_pass_rate:.2%}",
        f"- Average Section Completeness: {summary.average_section_completeness:.1f}",
        f"- Gate Decision Consistency: {summary.gate_decision_consistency:.2%}",
        f"- Tool Error Rate: {summary.tool_error_rate:.2%}",
        f"- Average Workflow Latency (ms): {summary.average_workflow_latency_ms:.1f}",
        f"- Passed Cases: {summary.passed_cases}",
        "",
        "## Case Results",
    ]
    for result in results:
        lines.append(
            f"- {result.case_id}: schema_passed={result.schema_passed}, "
            f"section_completeness={result.section_completeness}, gate_opened={result.gate_opened}, "
            f"tool_error_count={result.tool_error_count}, latency_ms={result.workflow_latency_ms}"
        )
    if summary.gate_mismatch_cases:
        lines.extend(["", "## Gate Mismatches"])
        lines.extend(f"- {case_id}" for case_id in summary.gate_mismatch_cases)
    return "\n".join(lines) + "\n"
