"""Tool contracts for deterministic Phase 3 workflow capabilities."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .schemas import (
    AcceptanceCriterionItem,
    DecisionLogItem,
    OpenQuestionItem,
    RequirementItem,
    RequirementReviewReport,
    RiskItem,
)


TOOL_NAMES = (
    "requirement-audit",
    "report-quality-check",
    "report-export",
    "clarity-score",
    "risk-taxonomy-check",
)

FIXED_REPORT_SECTIONS = (
    "需求摘要",
    "已确认信息",
    "待确认问题",
    "范围与优先级",
    "技术方案",
    "风险与对策",
    "验收标准",
    "下一步行动",
)

RISK_CATEGORIES = (
    "business_ambiguity",
    "scope_creep",
    "privacy_security",
    "reliability",
    "cost_timeline",
    "testability",
    "operations",
)


class ToolErrorCode(str, Enum):
    invalid_input = "INVALID_INPUT"
    empty_input = "EMPTY_INPUT"
    requirement_too_long = "REQUIREMENT_TOO_LONG"
    output_validation_failed = "OUTPUT_VALIDATION_FAILED"
    tool_execution_failed = "TOOL_EXECUTION_FAILED"
    export_failed = "EXPORT_FAILED"
    fallback_used = "FALLBACK_USED"
    unknown_tool = "UNKNOWN_TOOL"


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str
    retriable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionContext(BaseModel):
    task_id: str | None = None
    agent_id: str | None = None
    stage: str | None = None
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    call_id: str = Field(default_factory=lambda: uuid4().hex)
    tool_name: str
    success: bool
    fallback_used: bool = False
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0)
    context: ToolExecutionContext = Field(default_factory=ToolExecutionContext)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] | None = None
    error: ToolError | None = None


class ToolInvocationResult(BaseModel):
    tool_name: str
    success: bool
    output: dict[str, Any] | None = None
    error: ToolError | None = None
    record: ToolCallRecord


class CoverageDimension(BaseModel):
    dimension: Literal[
        "objective",
        "target_users",
        "scope",
        "constraints",
        "data_dependencies",
        "non_functional",
        "acceptance_criteria",
    ]
    covered: bool
    evidence: list[str] = Field(default_factory=list)
    note: str = ""


class RequirementAuditInput(BaseModel):
    requirement_text: str = Field(..., min_length=1)
    title: str = ""
    supplemental_context: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    explicit_constraints: list[str] = Field(default_factory=list)
    max_open_questions: int = Field(default=12, ge=1, le=30)

    @field_validator("requirement_text")
    @classmethod
    def validate_requirement_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("requirement_text cannot be empty")
        return cleaned


class RequirementAuditOutput(BaseModel):
    coverage_dimensions: list[CoverageDimension] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    requirement_items: list[RequirementItem] = Field(default_factory=list)
    open_questions: list[OpenQuestionItem] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterionItem] = Field(default_factory=list)
    decisions: list[DecisionLogItem] = Field(default_factory=list)
    overall_status: Literal["ready_for_scoring", "needs_clarification"] = "needs_clarification"
    notes: list[str] = Field(default_factory=list)


class ClarityScoreInput(BaseModel):
    requirement_text: str = Field(..., min_length=1)
    audit_result: RequirementAuditOutput | dict[str, Any] | None = None
    threshold: int = Field(default=65, ge=0, le=100)

    @field_validator("requirement_text")
    @classmethod
    def validate_requirement_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("requirement_text cannot be empty")
        return cleaned


class ClarityScoreOutput(BaseModel):
    score: int = Field(ge=0, le=100)
    threshold: int = Field(ge=0, le=100)
    passed: bool
    strengths: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    rationale: str = ""


class RiskTaxonomyCheckInput(BaseModel):
    requirement_text: str = Field(..., min_length=1)
    solution_summary: str = ""
    open_questions: list[OpenQuestionItem] | list[dict[str, Any]] = Field(default_factory=list)
    max_risks: int = Field(default=12, ge=1, le=30)

    @field_validator("requirement_text")
    @classmethod
    def validate_requirement_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("requirement_text cannot be empty")
        return cleaned


class RiskTaxonomyCheckOutput(BaseModel):
    covered_categories: list[str] = Field(default_factory=list)
    missing_categories: list[str] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)


class ReportQualityCheckInput(BaseModel):
    report_markdown: str = ""
    report_json: RequirementReviewReport | dict[str, Any] | None = None
    required_sections: list[str] = Field(default_factory=lambda: list(FIXED_REPORT_SECTIONS))

    @field_validator("required_sections")
    @classmethod
    def validate_required_sections(cls, value: list[str]) -> list[str]:
        return value or list(FIXED_REPORT_SECTIONS)


class ReportQualityCheckOutput(BaseModel):
    passed: bool
    score: int = Field(ge=0, le=100)
    section_presence: dict[str, bool] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class ReportExportInput(BaseModel):
    report_json: RequirementReviewReport | dict[str, Any]
    format: Literal["markdown", "json"] = "markdown"
    title: str = "需求澄清与方案预审报告"


class ReportExportOutput(BaseModel):
    format: Literal["markdown", "json"]
    title: str
    filename: str
    content: str
    sections: list[str] = Field(default_factory=list)


def empty_audit_output(note: str) -> RequirementAuditOutput:
    return RequirementAuditOutput(
        overall_status="needs_clarification",
        missing_dimensions=[
            "objective",
            "target_users",
            "scope",
            "constraints",
            "data_dependencies",
            "non_functional",
            "acceptance_criteria",
        ],
        open_questions=[
            OpenQuestionItem(
                question_id="Q-001",
                question="请补充该需求的目标、用户、范围、约束和验收标准。",
                impact="缺失核心输入时无法开展稳定预审。",
                priority="high",
            )
        ],
        notes=[note],
    )


def empty_clarity_output(note: str, threshold: int = 65) -> ClarityScoreOutput:
    return ClarityScoreOutput(
        score=0,
        threshold=threshold,
        passed=False,
        strengths=[],
        blockers=["需求输入不足，清晰度评分使用兜底结果。"],
        rationale=note,
    )


def empty_risk_output(note: str) -> RiskTaxonomyCheckOutput:
    return RiskTaxonomyCheckOutput(
        covered_categories=[],
        missing_categories=list(RISK_CATEGORIES),
        risks=[],
        review_notes=[note],
    )


def empty_quality_output(note: str) -> ReportQualityCheckOutput:
    return ReportQualityCheckOutput(
        passed=False,
        score=0,
        section_presence={section: False for section in FIXED_REPORT_SECTIONS},
        issues=[note],
        suggested_actions=["补齐固定章节并重新执行报告质检。"],
    )


def empty_export_output(title: str, fmt: Literal["markdown", "json"], note: str) -> ReportExportOutput:
    fallback_content = note if fmt == "markdown" else '{"error": "export fallback"}'
    filename = "requirement_pre_review_report.md" if fmt == "markdown" else "requirement_pre_review_report.json"
    return ReportExportOutput(
        format=fmt,
        title=title,
        filename=filename,
        content=fallback_content,
        sections=list(FIXED_REPORT_SECTIONS) if fmt == "markdown" else [],
    )
