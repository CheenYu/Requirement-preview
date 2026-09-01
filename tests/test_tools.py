from __future__ import annotations

from agents.requirement_pre_review.src.agents import build_agent_team
from agents.requirement_pre_review.src.tool_contracts import (
    ClarityScoreOutput,
    RequirementAuditOutput,
    RiskTaxonomyCheckOutput,
    ToolErrorCode,
)
from agents.requirement_pre_review.src.tools import ToolRuntime, build_tool_ready_report, render_markdown_report


def test_requirement_audit_returns_structured_output(tool_runtime: ToolRuntime) -> None:
    result = tool_runtime.invoke(
        "requirement-audit",
        {
            "title": "订单导出优化",
            "requirement_text": (
                "目标是降低客服手工导单成本。\n"
                "运营和客服需要在后台按时间范围导出订单。\n"
                "本期范围包括筛选、导出、失败重试。\n"
                "必须兼容现有后台权限体系，并在本月上线。\n"
                "需要调用订单API并记录导出日志。\n"
                "验收标准是1000条订单在3分钟内导出成功。"
            ),
            "target_users": ["运营", "客服"],
            "explicit_constraints": ["本月上线", "沿用现有权限模型"],
        },
    )

    assert result.success is True
    assert result.output is not None
    assert result.output["requirement_items"][0]["requirement_id"] == "REQ-001"
    assert "objective" not in result.output["missing_dimensions"]


def test_invalid_tool_input_returns_fallback_output(tool_runtime: ToolRuntime) -> None:
    result = tool_runtime.invoke("requirement-audit", {"requirement_text": "   "})

    assert result.success is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.empty_input
    assert result.record.fallback_used is True
    assert result.output is not None
    assert result.output["overall_status"] == "needs_clarification"
    assert result.output["open_questions"][0]["question_id"] == "Q-001"


def test_report_export_and_quality_check_work_together(tool_runtime: ToolRuntime) -> None:
    audit = tool_runtime.invoke(
        "requirement-audit",
        {
            "requirement_text": (
                "目标是支持销售查看客户跟进记录。\n"
                "销售和主管可访问该页面。\n"
                "范围包括列表、详情和筛选。\n"
                "接口依赖CRM API。\n"
                "验收标准是销售能按客户名称检索记录。"
            )
        },
    )
    clarity = tool_runtime.invoke(
        "clarity-score",
        {
            "requirement_text": "销售跟进记录查看",
            "audit_result": audit.output,
            "threshold": 40,
        },
    )
    risk = tool_runtime.invoke(
        "risk-taxonomy-check",
        {
            "requirement_text": "销售查看客户跟进记录，需要调用CRM API。",
            "open_questions": audit.output["open_questions"],
        },
    )

    report = build_tool_ready_report(
        audit_output=RequirementAuditOutput.model_validate(audit.output),
        clarity_output=ClarityScoreOutput.model_validate(clarity.output),
        risk_output=RiskTaxonomyCheckOutput.model_validate(risk.output),
    )

    markdown = render_markdown_report(report)
    quality = tool_runtime.invoke(
        "report-quality-check",
        {
            "report_markdown": markdown,
            "report_json": report.model_dump(mode="json"),
        },
    )
    exported = tool_runtime.invoke(
        "report-export",
        {
            "report_json": report.model_dump(mode="json"),
            "format": "markdown",
            "title": "销售跟进记录预审报告",
        },
    )

    assert clarity.success is True
    assert quality.success is True
    assert quality.output["score"] >= 75
    assert exported.output["filename"].endswith(".md")
    assert "## 需求摘要" in exported.output["content"]


def test_clarity_score_and_risk_taxonomy_tools_cover_gate_and_categories(
    tool_runtime: ToolRuntime,
    clear_requirement_text: str,
    ambiguous_requirement_text: str,
) -> None:
    clear_audit = tool_runtime.invoke(
        "requirement-audit",
        {"requirement_text": clear_requirement_text},
    )
    clear_clarity = tool_runtime.invoke(
        "clarity-score",
        {
            "requirement_text": clear_requirement_text,
            "audit_result": clear_audit.output,
            "threshold": 65,
        },
    )
    ambiguous_audit = tool_runtime.invoke(
        "requirement-audit",
        {"requirement_text": ambiguous_requirement_text},
    )
    ambiguous_clarity = tool_runtime.invoke(
        "clarity-score",
        {
            "requirement_text": ambiguous_requirement_text,
            "audit_result": ambiguous_audit.output,
            "threshold": 65,
        },
    )
    risk_result = tool_runtime.invoke(
        "risk-taxonomy-check",
        {
            "requirement_text": clear_requirement_text,
            "solution_summary": "需要调用订单 API，复用权限体系，并在本月上线。",
            "open_questions": clear_audit.output["open_questions"],
        },
    )

    assert clear_clarity.output["passed"] is True
    assert ambiguous_clarity.output["passed"] is False
    assert "reliability" in risk_result.output["covered_categories"]
    assert "cost_timeline" in risk_result.output["covered_categories"]


def test_requirement_too_long_returns_stable_error_code(tool_runtime: ToolRuntime, workflow_config) -> None:
    too_long_text = "a" * (workflow_config.max_requirement_length + 1)

    result = tool_runtime.invoke("requirement-audit", {"requirement_text": too_long_text})

    assert result.success is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.requirement_too_long
    assert result.record.fallback_used is True


def test_unknown_tool_returns_stable_error_code(tool_runtime: ToolRuntime) -> None:
    result = tool_runtime.invoke("missing-tool", {"foo": "bar"})

    assert result.success is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.unknown_tool
    assert result.output is None


def test_agent_team_contains_expected_roles_and_tools(workflow_config) -> None:
    team = build_agent_team(config=workflow_config)

    assert team.execution_order == [
        "requirement_analyst",
        "solution_architect",
        "risk_reviewer",
        "report_synthesizer",
    ]
    assert team.get_agent("report_synthesizer").allowed_tools == ["report-quality-check", "report-export"]
    assert team.function_boundary.provider_agnostic is True
