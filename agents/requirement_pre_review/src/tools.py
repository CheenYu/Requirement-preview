"""Deterministic workflow tools with provider-agnostic contract validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable

from pydantic import BaseModel, ValidationError

from backend.events import event_logger

from .config import WorkflowConfig, load_workflow_config
from .schemas import (
    AcceptanceCriterionItem,
    DecisionLogItem,
    OpenQuestionItem,
    RequirementItem,
    RequirementReviewReport,
    RiskItem,
    ScopePriority,
    SolutionPlan,
)
from .tool_contracts import (
    ClarityScoreInput,
    ClarityScoreOutput,
    CoverageDimension,
    FIXED_REPORT_SECTIONS,
    RISK_CATEGORIES,
    ReportExportInput,
    ReportExportOutput,
    ReportQualityCheckInput,
    ReportQualityCheckOutput,
    RequirementAuditInput,
    RequirementAuditOutput,
    RiskTaxonomyCheckInput,
    RiskTaxonomyCheckOutput,
    ToolCallRecord,
    ToolError,
    ToolErrorCode,
    ToolExecutionContext,
    ToolInvocationResult,
    empty_audit_output,
    empty_clarity_output,
    empty_export_output,
    empty_quality_output,
    empty_risk_output,
)


DIMENSION_RULES: dict[str, dict[str, Any]] = {
    "objective": {
        "keywords": ("目标", "目的", "希望", "提升", "降低", "goal", "objective", "kpi"),
        "question": "这个需求最核心的业务目标和成功指标是什么？",
        "impact": "缺少目标会导致方案评审无法判断取舍标准。",
    },
    "target_users": {
        "keywords": ("用户", "客户", "角色", "运营", "商家", "管理员", "user", "role"),
        "question": "这个需求面向哪些用户或内部角色？",
        "impact": "缺少用户边界会导致需求范围和体验路径失真。",
    },
    "scope": {
        "keywords": ("范围", "包括", "不包括", "支持", "功能", "模块", "页面", "接口"),
        "question": "本次版本明确包含什么，不包含什么？",
        "impact": "缺少范围边界容易造成范围蔓延和估时失真。",
    },
    "constraints": {
        "keywords": ("约束", "限制", "必须", "截止", "时间", "预算", "技术栈", "兼容", "deadline"),
        "question": "是否存在上线时间、预算、技术栈或兼容性约束？",
        "impact": "缺少约束条件会让技术方案不具备可执行性。",
    },
    "data_dependencies": {
        "keywords": ("数据", "字段", "api", "接口", "表", "同步", "导入", "导出", "schema"),
        "question": "需要依赖哪些数据源、字段、接口或外部系统？",
        "impact": "数据依赖不清会直接影响实现复杂度与联调风险。",
    },
    "non_functional": {
        "keywords": ("性能", "安全", "稳定", "并发", "权限", "日志", "监控", "可用性", "sla"),
        "question": "是否有性能、安全、权限、日志或稳定性要求？",
        "impact": "非功能要求缺失时，方案预审容易遗漏关键工程风险。",
    },
    "acceptance_criteria": {
        "keywords": ("验收", "完成标准", "acceptance", "通过条件", "指标", "测试"),
        "question": "该需求的验收标准、通过条件或可测试结果是什么？",
        "impact": "没有验收标准就无法判断需求是否真正完成。",
    },
}

RISK_RULES: dict[str, dict[str, Any]] = {
    "business_ambiguity": {
        "title": "业务边界和目标存在不确定性",
        "impact": "团队可能基于不同理解推进设计与开发，导致返工。",
        "mitigation": "在进入方案评审前补齐业务目标、用户对象和验收标准。",
        "severity": "high",
    },
    "scope_creep": {
        "title": "需求范围可能持续扩张",
        "impact": "迭代计划和实现复杂度会在评审后失控。",
        "mitigation": "明确本期范围、非目标项以及 deferred 项目。",
        "severity": "high",
    },
    "privacy_security": {
        "title": "隐私与安全约束未被充分定义",
        "impact": "涉及用户数据或权限场景时可能留下合规与安全缺口。",
        "mitigation": "补充数据分级、权限边界、审计和脱敏要求。",
        "severity": "medium",
    },
    "reliability": {
        "title": "可靠性与异常处理要求不完整",
        "impact": "接口失败、并发冲突或重试场景下系统行为不可控。",
        "mitigation": "补充异常流、幂等性、超时重试和监控告警策略。",
        "severity": "medium",
    },
    "cost_timeline": {
        "title": "交付窗口或成本约束存在实现风险",
        "impact": "需求过宽或依赖过多时，迭代节奏和投入会偏离预期。",
        "mitigation": "拆分里程碑，确认最小可交付范围和关键依赖。",
        "severity": "medium",
    },
    "testability": {
        "title": "需求可测试性不足",
        "impact": "缺少可验证标准会阻碍测试设计和验收闭环。",
        "mitigation": "补充验收条目、边界条件和成功失败判定。",
        "severity": "high",
    },
    "operations": {
        "title": "运维与上线准备考虑不足",
        "impact": "上线后的监控、回滚和运营支持可能缺失。",
        "mitigation": "提前明确监控指标、日志留存和发布回滚方案。",
        "severity": "medium",
    },
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _slugify_filename(value: str) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value.strip().lower())
    base = base.strip("_") or "requirement_pre_review_report"
    return base


def _truncate(value: str, limit: int = 120) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3]}..."


def _extract_lines(requirement_text: str) -> list[str]:
    lines = [line.strip("-* \t") for line in requirement_text.splitlines()]
    lines = [line for line in lines if line]
    if lines:
        return lines[:20]

    parts = re.split(r"[。！？!?;\n]+", requirement_text)
    return [_normalize_text(part) for part in parts if _normalize_text(part)][:20]


def _build_requirement_items(requirement_text: str) -> list[RequirementItem]:
    items: list[RequirementItem] = []
    for index, line in enumerate(_extract_lines(requirement_text), start=1):
        items.append(
            RequirementItem(
                requirement_id=f"REQ-{index:03d}",
                title=_truncate(line, limit=24),
                description=line,
                status="confirmed",
            )
        )
    return items or [
        RequirementItem(
            requirement_id="REQ-001",
            title="原始需求",
            description=_truncate(_normalize_text(requirement_text), limit=200),
            status="confirmed",
        )
    ]


def _build_acceptance_criteria(lines: Iterable[str]) -> list[AcceptanceCriterionItem]:
    criteria: list[AcceptanceCriterionItem] = []
    matched_lines = [
        line for line in lines if re.search(r"验收|完成标准|acceptance|通过条件|测试|指标", line, flags=re.IGNORECASE)
    ]
    for index, line in enumerate(matched_lines[:8], start=1):
        criteria.append(
            AcceptanceCriterionItem(
                criterion_id=f"AC-{index:03d}",
                description=line,
                testable=True,
            )
        )
    return criteria


def _build_coverage(input_data: RequirementAuditInput) -> list[CoverageDimension]:
    source_parts = [input_data.requirement_text]
    source_parts.extend(input_data.supplemental_context)
    source_parts.extend(input_data.target_users)
    source_parts.extend(input_data.explicit_constraints)
    source_text = " ".join(source_parts).lower()

    coverage: list[CoverageDimension] = []
    for dimension, rule in DIMENSION_RULES.items():
        evidence = [keyword for keyword in rule["keywords"] if keyword.lower() in source_text][:3]
        coverage.append(
            CoverageDimension(
                dimension=dimension,  # type: ignore[arg-type]
                covered=bool(evidence),
                evidence=evidence,
                note="" if evidence else f"未发现与 {dimension} 直接对应的约束或事实。",
            )
        )
    return coverage


def _build_confirmed_facts(input_data: RequirementAuditInput) -> list[str]:
    facts: list[str] = []
    if input_data.title:
        facts.append(f"需求标题：{input_data.title}")
    if input_data.target_users:
        facts.append(f"目标用户：{', '.join(input_data.target_users)}")
    for index, constraint in enumerate(input_data.explicit_constraints, start=1):
        facts.append(f"约束 {index}：{constraint}")
    for context in input_data.supplemental_context[:5]:
        facts.append(context)
    return facts


def _build_open_questions(coverage: list[CoverageDimension], limit: int) -> list[OpenQuestionItem]:
    questions: list[OpenQuestionItem] = []
    for dimension in coverage:
        if dimension.covered:
            continue
        rule = DIMENSION_RULES[dimension.dimension]
        questions.append(
            OpenQuestionItem(
                question_id=f"Q-{len(questions) + 1:03d}",
                question=rule["question"],
                impact=rule["impact"],
                priority="high" if dimension.dimension in {"objective", "scope", "acceptance_criteria"} else "medium",
            )
        )
        if len(questions) >= limit:
            break
    return questions


def _build_decisions(coverage: list[CoverageDimension]) -> list[DecisionLogItem]:
    decisions: list[DecisionLogItem] = []
    for dimension in coverage:
        decisions.append(
            DecisionLogItem(
                decision_id=f"DEC-{len(decisions) + 1:03d}",
                topic=dimension.dimension,
                status="confirmed" if dimension.covered else "pending",
                rationale="发现明确证据，可进入后续分析。" if dimension.covered else "当前资料中缺少稳定证据，需要澄清。",
                owner="product",
            )
        )
    return decisions


def _coerce_audit_result(value: RequirementAuditOutput | dict[str, Any] | None) -> RequirementAuditOutput | None:
    if value is None:
        return None
    if isinstance(value, RequirementAuditOutput):
        return value
    return RequirementAuditOutput.model_validate(value)


def _coerce_report(value: RequirementReviewReport | dict[str, Any]) -> RequirementReviewReport:
    if isinstance(value, RequirementReviewReport):
        return value
    return RequirementReviewReport.model_validate(value)


def render_markdown_report(report: RequirementReviewReport, *, title: str = "需求澄清与方案预审报告") -> str:
    confirmed = "\n".join(f"- {item}" for item in report.confirmed_facts) or "- 无"
    questions = (
        "\n".join(f"- {item.question_id} {item.question}（影响：{item.impact}）" for item in report.open_questions) or "- 无"
    )
    scope = "\n".join(
        [
            f"- Must Have: {', '.join(report.scope_priority.must_have) or '无'}",
            f"- Should Have: {', '.join(report.scope_priority.should_have) or '无'}",
            f"- Deferred: {', '.join(report.scope_priority.deferred) or '无'}",
        ]
    )
    modules = "\n".join(
        f"- {module.name}: {module.responsibility}" for module in report.solution_plan.modules
    ) or "- 无"
    risks = (
        "\n".join(
            f"- {risk.risk_id} [{risk.category}/{risk.severity}] {risk.title}: {risk.mitigation}" for risk in report.risks
        )
        or "- 无"
    )
    acceptance = (
        "\n".join(f"- {item.criterion_id} {item.description}" for item in report.acceptance_criteria) or "- 无"
    )
    next_actions = "\n".join(f"- {item}" for item in report.next_actions) or "- 无"

    sections = [
        f"# {title}",
        "",
        "## 需求摘要",
        report.summary or "待补充需求摘要。",
        "",
        "## 已确认信息",
        confirmed,
        "",
        "## 待确认问题",
        questions,
        "",
        "## 范围与优先级",
        scope,
        "",
        "## 技术方案",
        modules,
        "",
        "## 风险与对策",
        risks,
        "",
        "## 验收标准",
        acceptance,
        "",
        "## 下一步行动",
        next_actions,
    ]
    return "\n".join(sections).strip() + "\n"


def build_tool_ready_report(
    audit_output: RequirementAuditOutput,
    clarity_output: ClarityScoreOutput,
    risk_output: RiskTaxonomyCheckOutput,
) -> RequirementReviewReport:
    must_have = [item.title for item in audit_output.requirement_items[:3]]
    should_have = [item.title for item in audit_output.requirement_items[3:6]]
    report = RequirementReviewReport(
        summary=(
            f"清晰度得分 {clarity_output.score}/{clarity_output.threshold}。"
            f"{'已通过' if clarity_output.passed else '未通过'}方案预审门禁。"
        ),
        confirmed_facts=audit_output.confirmed_facts,
        requirement_items=audit_output.requirement_items,
        open_questions=audit_output.open_questions,
        scope_priority=ScopePriority(
            must_have=must_have,
            should_have=should_have,
            deferred=["待澄清后再排期的扩展项"] if audit_output.open_questions else [],
        ),
        solution_plan=SolutionPlan(goal="基于当前需求形成可评审的实现方案草案。"),
        risks=risk_output.risks,
        acceptance_criteria=audit_output.acceptance_criteria,
        next_actions=[
            "由产品补充高优先级澄清问题。",
            "在门禁通过后进入技术方案评审。",
            "将高风险项转为评审会议显式检查项。",
        ],
        decisions=audit_output.decisions,
    )
    return report


@dataclass
class StructuredToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel, WorkflowConfig], BaseModel]
    fallback: Callable[[ToolError], BaseModel]


class ToolRuntime:
    """Unified runtime for contract validation, logging, and failure fallback."""

    def __init__(self, config: WorkflowConfig | None = None) -> None:
        self.config = config or load_workflow_config()
        self._registry: dict[str, StructuredToolSpec] = {}
        self._records: list[ToolCallRecord] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(
            StructuredToolSpec(
                name="requirement-audit",
                description="Audit requirement completeness and produce clarification questions.",
                input_model=RequirementAuditInput,
                output_model=RequirementAuditOutput,
                handler=_handle_requirement_audit,
                fallback=lambda error: empty_audit_output(f"{error.code}: {error.message}"),
            )
        )
        self.register(
            StructuredToolSpec(
                name="clarity-score",
                description="Score requirement clarity and apply gate threshold.",
                input_model=ClarityScoreInput,
                output_model=ClarityScoreOutput,
                handler=_handle_clarity_score,
                fallback=lambda error: empty_clarity_output(f"{error.code}: {error.message}"),
            )
        )
        self.register(
            StructuredToolSpec(
                name="risk-taxonomy-check",
                description="Classify pre-review risks using a fixed taxonomy.",
                input_model=RiskTaxonomyCheckInput,
                output_model=RiskTaxonomyCheckOutput,
                handler=_handle_risk_taxonomy_check,
                fallback=lambda error: empty_risk_output(f"{error.code}: {error.message}"),
            )
        )
        self.register(
            StructuredToolSpec(
                name="report-quality-check",
                description="Validate report sections and schema completeness.",
                input_model=ReportQualityCheckInput,
                output_model=ReportQualityCheckOutput,
                handler=_handle_report_quality_check,
                fallback=lambda error: empty_quality_output(f"{error.code}: {error.message}"),
            )
        )
        self.register(
            StructuredToolSpec(
                name="report-export",
                description="Export the structured report to markdown or JSON.",
                input_model=ReportExportInput,
                output_model=ReportExportOutput,
                handler=_handle_report_export,
                fallback=lambda error: empty_export_output(
                    title="需求澄清与方案预审报告",
                    fmt="markdown",
                    note=f"{error.code}: {error.message}",
                ),
            )
        )

    def register(self, spec: StructuredToolSpec) -> None:
        self._registry[spec.name] = spec

    def list_tools(self) -> list[str]:
        return list(self._registry.keys())

    def describe_tool(self, tool_name: str) -> dict[str, Any]:
        spec = self._registry[tool_name]
        return {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_model.model_json_schema(),
            "output_schema": spec.output_model.model_json_schema(),
        }

    def list_call_records(self) -> list[ToolCallRecord]:
        return list(self._records)

    def clear_history(self) -> None:
        self._records.clear()

    def invoke(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolInvocationResult:
        started_at = datetime.now()
        context = context or ToolExecutionContext()
        spec = self._registry.get(tool_name)

        if spec is None:
            error = ToolError(
                code=ToolErrorCode.unknown_tool,
                message=f"Unknown tool: {tool_name}",
                details={"tool_name": tool_name},
            )
            record = self._finalize_record(
                tool_name=tool_name,
                started_at=started_at,
                context=context,
                input_payload=payload,
                output_payload=None,
                success=False,
                fallback_used=False,
                error=error,
            )
            return ToolInvocationResult(tool_name=tool_name, success=False, output=None, error=error, record=record)

        try:
            validated_input = spec.input_model.model_validate(payload)
        except ValidationError as exc:
            error = self._classify_input_error(exc)
            output_model = self._build_fallback_output(spec, error, payload)
            return self._finish_with_output(
                spec=spec,
                started_at=started_at,
                context=context,
                validated_input=payload,
                output_model=output_model,
                success=False,
                fallback_used=True,
                error=error,
            )

        try:
            output_candidate = spec.handler(validated_input, self.config)
            validated_output = spec.output_model.model_validate(output_candidate)
            return self._finish_with_output(
                spec=spec,
                started_at=started_at,
                context=context,
                validated_input=validated_input.model_dump(mode="json"),
                output_model=validated_output,
                success=True,
                fallback_used=False,
                error=None,
            )
        except ValidationError as exc:
            error = ToolError(
                code=ToolErrorCode.output_validation_failed,
                message="Tool output validation failed.",
                retriable=False,
                details={"errors": exc.errors()},
            )
        except Exception as exc:  # pragma: no cover - defensive layer
            error_message = str(exc)
            if error_message.startswith(f"{ToolErrorCode.requirement_too_long.value}:"):
                error_code = ToolErrorCode.requirement_too_long
                error_message = error_message.split(":", 1)[1].strip()
            elif spec.name == "report-export":
                error_code = ToolErrorCode.export_failed
            else:
                error_code = ToolErrorCode.tool_execution_failed
            error = ToolError(
                code=error_code,
                message=error_message,
                retriable=False,
                details={"tool_name": tool_name},
            )

        output_model = self._build_fallback_output(spec, error, validated_input.model_dump(mode="json"))
        return self._finish_with_output(
            spec=spec,
            started_at=started_at,
            context=context,
            validated_input=validated_input.model_dump(mode="json"),
            output_model=output_model,
            success=False,
            fallback_used=True,
            error=error,
        )

    def _classify_input_error(self, exc: ValidationError) -> ToolError:
        message = "Tool input validation failed."
        code = ToolErrorCode.invalid_input
        for issue in exc.errors():
            if "requirement_text" in ".".join(str(item) for item in issue.get("loc", ())):
                code = ToolErrorCode.empty_input
                message = "requirement_text cannot be empty"
                break
        return ToolError(code=code, message=message, retriable=False, details={"errors": exc.errors()})

    def _finish_with_output(
        self,
        *,
        spec: StructuredToolSpec,
        started_at: datetime,
        context: ToolExecutionContext,
        validated_input: dict[str, Any],
        output_model: BaseModel,
        success: bool,
        fallback_used: bool,
        error: ToolError | None,
    ) -> ToolInvocationResult:
        output_payload = output_model.model_dump(mode="json")
        record = self._finalize_record(
            tool_name=spec.name,
            started_at=started_at,
            context=context,
            input_payload=validated_input,
            output_payload=output_payload,
            success=success,
            fallback_used=fallback_used,
            error=error,
        )
        return ToolInvocationResult(
            tool_name=spec.name,
            success=success,
            output=output_payload,
            error=error,
            record=record,
        )

    def _build_fallback_output(
        self,
        spec: StructuredToolSpec,
        error: ToolError,
        payload: dict[str, Any],
    ) -> BaseModel:
        if spec.name == "report-export":
            fmt = payload.get("format", "markdown")
            if fmt not in {"markdown", "json"}:
                fmt = "markdown"
            title = payload.get("title", "需求澄清与方案预审报告")
            return empty_export_output(title=title, fmt=fmt, note=f"{error.code}: {error.message}")
        return spec.fallback(error)

    def _finalize_record(
        self,
        *,
        tool_name: str,
        started_at: datetime,
        context: ToolExecutionContext,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any] | None,
        success: bool,
        fallback_used: bool,
        error: ToolError | None,
    ) -> ToolCallRecord:
        finished_at = datetime.now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        record = ToolCallRecord(
            tool_name=tool_name,
            success=success,
            fallback_used=fallback_used,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(duration_ms, 0),
            context=context,
            input_payload=input_payload,
            output_payload=output_payload,
            error=error,
        )
        self._records.append(record)
        event_logger.emit(
            "tool_invocation",
            task_id=context.task_id,
            agent_id=context.agent_id,
            payload={
                "tool_name": tool_name,
                "stage": context.stage,
                "success": success,
                "fallback_used": fallback_used,
                "error_code": error.code if error else None,
                "duration_ms": record.duration_ms,
                "trace_id": context.trace_id,
            },
        )
        return record


def _handle_requirement_audit(raw_input: BaseModel, config: WorkflowConfig) -> RequirementAuditOutput:
    input_data = RequirementAuditInput.model_validate(raw_input)
    if len(input_data.requirement_text) > config.max_requirement_length:
        raise ValueError(
            f"{ToolErrorCode.requirement_too_long}: requirement_text exceeds {config.max_requirement_length} characters"
        )

    coverage = _build_coverage(input_data)
    open_questions = _build_open_questions(coverage, min(input_data.max_open_questions, config.max_open_questions))
    requirement_items = _build_requirement_items(input_data.requirement_text)
    acceptance_criteria = _build_acceptance_criteria(_extract_lines(input_data.requirement_text))

    notes = [
        "Requirement items use REQ-xxx numbering.",
        "Acceptance criteria use AC-xxx numbering.",
        "Decision log items use DEC-xxx numbering.",
    ]
    return RequirementAuditOutput(
        coverage_dimensions=coverage,
        missing_dimensions=[item.dimension for item in coverage if not item.covered],
        confirmed_facts=_build_confirmed_facts(input_data),
        requirement_items=requirement_items,
        open_questions=open_questions,
        acceptance_criteria=acceptance_criteria,
        decisions=_build_decisions(coverage),
        overall_status="ready_for_scoring" if not open_questions else "needs_clarification",
        notes=notes,
    )


def _handle_clarity_score(raw_input: BaseModel, config: WorkflowConfig) -> ClarityScoreOutput:
    input_data = ClarityScoreInput.model_validate(raw_input)
    audit_result = _coerce_audit_result(input_data.audit_result)
    if audit_result is None:
        audit_result = _handle_requirement_audit(
            RequirementAuditInput(requirement_text=input_data.requirement_text),
            config,
        )

    coverage_count = sum(1 for item in audit_result.coverage_dimensions if item.covered)
    missing_count = len(audit_result.missing_dimensions)
    question_penalty = min(len(audit_result.open_questions) * 4, 24)
    criterion_bonus = min(len(audit_result.acceptance_criteria) * 5, 10)
    requirement_bonus = min(len(audit_result.requirement_items) * 2, 10)

    score = max(0, min(100, coverage_count * 12 + requirement_bonus + criterion_bonus - question_penalty))
    threshold = input_data.threshold or config.clarity_gate_threshold
    strengths = [f"{item.dimension} 已覆盖" for item in audit_result.coverage_dimensions if item.covered]
    blockers = [f"{dimension} 信息不足" for dimension in audit_result.missing_dimensions]
    rationale = (
        f"覆盖维度 {coverage_count}/7，缺失维度 {missing_count}，"
        f"澄清问题 {len(audit_result.open_questions)} 个。"
    )
    return ClarityScoreOutput(
        score=score,
        threshold=threshold,
        passed=score >= threshold,
        strengths=strengths[:5],
        blockers=blockers[:5],
        rationale=rationale,
    )


def _should_raise_privacy_security(text: str) -> bool:
    return bool(re.search(r"登录|账号|权限|支付|订单|隐私|个人信息|文件上传|customer|user data", text, re.IGNORECASE))


def _should_raise_operations(text: str) -> bool:
    return bool(re.search(r"上线|部署|监控|告警|运维|回滚|发布", text, re.IGNORECASE))


def _handle_risk_taxonomy_check(raw_input: BaseModel, config: WorkflowConfig) -> RiskTaxonomyCheckOutput:
    input_data = RiskTaxonomyCheckInput.model_validate(raw_input)
    combined_text = f"{input_data.requirement_text}\n{input_data.solution_summary}"
    lines = _extract_lines(combined_text)
    question_count = len(input_data.open_questions)

    triggered_categories: list[str] = []
    if question_count >= 2 or not re.search(r"目标|用户|验收|goal|user|acceptance", combined_text, re.IGNORECASE):
        triggered_categories.append("business_ambiguity")
    if re.search(r"全部|所有|统一|一期先|后续继续|尽量", combined_text, re.IGNORECASE):
        triggered_categories.append("scope_creep")
    if _should_raise_privacy_security(combined_text):
        triggered_categories.append("privacy_security")
    if re.search(r"接口|同步|异步|并发|重试|失败|超时|api", combined_text, re.IGNORECASE):
        triggered_categories.append("reliability")
    if re.search(r"本周|本月|尽快|deadline|预算|人天|排期", combined_text, re.IGNORECASE):
        triggered_categories.append("cost_timeline")
    if question_count >= 1 or not re.search(r"验收|测试|指标|acceptance", combined_text, re.IGNORECASE):
        triggered_categories.append("testability")
    if _should_raise_operations(combined_text):
        triggered_categories.append("operations")

    deduped_categories: list[str] = []
    for category in triggered_categories:
        if category not in deduped_categories:
            deduped_categories.append(category)

    risks: list[RiskItem] = []
    for index, category in enumerate(deduped_categories[: min(input_data.max_risks, config.max_risks_per_run)], start=1):
        template = RISK_RULES[category]
        risks.append(
            RiskItem(
                risk_id=f"RISK-{index:03d}",
                category=category,  # type: ignore[arg-type]
                title=template["title"],
                impact=template["impact"],
                mitigation=template["mitigation"],
                severity=template["severity"],  # type: ignore[arg-type]
                owner="engineering" if category in {"reliability", "operations"} else "product",
            )
        )

    review_notes = [
        f"基于需求文本与方案摘要识别到 {len(risks)} 个风险分类。",
        f"尚未触达的风险分类：{', '.join(category for category in RISK_CATEGORIES if category not in deduped_categories) or '无'}。",
    ]
    return RiskTaxonomyCheckOutput(
        covered_categories=deduped_categories,
        missing_categories=[category for category in RISK_CATEGORIES if category not in deduped_categories],
        risks=risks,
        review_notes=review_notes,
    )


def _handle_report_quality_check(raw_input: BaseModel, config: WorkflowConfig) -> ReportQualityCheckOutput:
    del config
    input_data = ReportQualityCheckInput.model_validate(raw_input)

    section_presence = {
        section: f"## {section}" in input_data.report_markdown for section in input_data.required_sections
    }
    issues: list[str] = []
    suggested_actions: list[str] = []
    score = 100

    for section, present in section_presence.items():
        if not present:
            issues.append(f"缺少固定章节：{section}")
            suggested_actions.append(f"补齐 `{section}` 章节内容。")
            score -= 10

    report: RequirementReviewReport | None = None
    if input_data.report_json is None:
        issues.append("缺少结构化 JSON 报告。")
        suggested_actions.append("提供 `report_json` 并执行 schema 校验。")
        score -= 20
    else:
        try:
            report = _coerce_report(input_data.report_json)
        except ValidationError as exc:
            issues.append("结构化 JSON 报告未通过 schema 校验。")
            suggested_actions.append("修复 report_json 字段结构后重新质检。")
            score -= 25
            report = None

    if report is not None:
        if not report.summary.strip():
            issues.append("报告摘要为空。")
            score -= 10
        if not report.risks:
            issues.append("风险章节缺少结构化风险条目。")
            score -= 10
        if not report.acceptance_criteria:
            issues.append("验收标准为空，测试闭环不足。")
            score -= 10

    score = max(0, min(score, 100))
    passed = score >= 75 and all(section_presence.values()) and not any("schema" in issue for issue in issues)
    if not suggested_actions:
        suggested_actions.append("报告结构完整，可进入导出或归档。")
    return ReportQualityCheckOutput(
        passed=passed,
        score=score,
        section_presence=section_presence,
        issues=issues,
        suggested_actions=suggested_actions,
    )


def _handle_report_export(raw_input: BaseModel, config: WorkflowConfig) -> ReportExportOutput:
    del config
    input_data = ReportExportInput.model_validate(raw_input)
    report = _coerce_report(input_data.report_json)
    slug = _slugify_filename(input_data.title)

    if input_data.format == "markdown":
        content = render_markdown_report(report, title=input_data.title)
        filename = f"{slug}.md"
        sections = list(FIXED_REPORT_SECTIONS)
    else:
        content = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
        filename = f"{slug}.json"
        sections = []

    return ReportExportOutput(
        format=input_data.format,
        title=input_data.title,
        filename=filename,
        content=content,
        sections=sections,
    )


_DEFAULT_RUNTIME = ToolRuntime()


def get_tool_runtime(config: WorkflowConfig | None = None) -> ToolRuntime:
    if config is None:
        return _DEFAULT_RUNTIME
    return ToolRuntime(config=config)


def invoke_tool(
    tool_name: str,
    payload: dict[str, Any],
    *,
    context: ToolExecutionContext | None = None,
    runtime: ToolRuntime | None = None,
) -> ToolInvocationResult:
    active_runtime = runtime or _DEFAULT_RUNTIME
    return active_runtime.invoke(tool_name, payload, context=context)
