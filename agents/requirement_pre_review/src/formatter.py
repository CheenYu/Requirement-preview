"""Formatting helpers for workflow stage artifacts and final report shaping."""

from __future__ import annotations

import re
from typing import Iterable

from .schemas import (
    AcceptanceCriterionItem,
    DataFlowStep,
    DecisionLogItem,
    InterfaceDraft,
    MilestoneItem,
    OpenQuestionItem,
    RequirementItem,
    RequirementReviewReport,
    RiskItem,
    ScopePriority,
    SolutionModule,
    SolutionPlan,
)
from .tool_contracts import ClarityScoreOutput, RequirementAuditOutput, RiskTaxonomyCheckOutput


def _truncate(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3]}..."


def _safe_lines(requirement_text: str) -> list[str]:
    lines = [line.strip("-* \t") for line in requirement_text.splitlines() if line.strip()]
    if lines:
        return lines
    return [part.strip() for part in re.split(r"[。！？!?;\n]+", requirement_text) if part.strip()]


def renumber_requirement_items(items: Iterable[RequirementItem]) -> list[RequirementItem]:
    return [
        item.model_copy(update={"requirement_id": f"REQ-{index:03d}"})
        for index, item in enumerate(items, start=1)
    ]


def renumber_acceptance_criteria(items: Iterable[AcceptanceCriterionItem]) -> list[AcceptanceCriterionItem]:
    return [
        item.model_copy(update={"criterion_id": f"AC-{index:03d}"})
        for index, item in enumerate(items, start=1)
    ]


def renumber_decisions(items: Iterable[DecisionLogItem]) -> list[DecisionLogItem]:
    return [
        item.model_copy(update={"decision_id": f"DEC-{index:03d}"})
        for index, item in enumerate(items, start=1)
    ]


def infer_scope_priority(audit_output: RequirementAuditOutput) -> ScopePriority:
    requirement_titles = [item.title for item in audit_output.requirement_items]
    must_have = requirement_titles[:3]
    should_have = requirement_titles[3:6]
    deferred = []
    if audit_output.open_questions:
        deferred.append("依赖澄清问题答案的扩展项")
    if len(requirement_titles) > 6:
        deferred.extend(requirement_titles[6:8])
    return ScopePriority(must_have=must_have, should_have=should_have, deferred=deferred)


def infer_solution_plan(
    *,
    requirement_text: str,
    audit_output: RequirementAuditOutput,
    clarity_output: ClarityScoreOutput,
) -> SolutionPlan:
    text = requirement_text.lower()
    if not clarity_output.passed:
        return SolutionPlan(
            goal="当前需求未通过清晰度门禁，技术方案仅保留待澄清占位。",
            modules=[
                SolutionModule(
                    name="Clarification Gate",
                    responsibility="先补齐高优先级问题，再进入具体架构和接口设计。",
                    dependencies=["product_confirmation"],
                )
            ],
            data_flow=[
                DataFlowStep(step="1", description="收集澄清问题答案并更新需求边界。"),
                DataFlowStep(step="2", description="门禁通过后再进入方案拆解和风险复审。"),
            ],
            interfaces=[],
            milestones=[
                MilestoneItem(milestone="M1", goal="完成需求补充与门禁复核"),
            ],
        )

    modules = [
        SolutionModule(
            name="Experience Layer",
            responsibility="承接用户或内部角色的页面、入口或操作流。",
            dependencies=["business_service"],
        ),
        SolutionModule(
            name="Business Service",
            responsibility="实现需求核心规则、状态流转和校验逻辑。",
            dependencies=["data_access"],
        ),
    ]
    if re.search(r"api|接口|同步|crm|erp|第三方|导入|导出|回调", text, re.IGNORECASE):
        modules.append(
            SolutionModule(
                name="Integration Layer",
                responsibility="对接外部系统、封装接口协议和失败重试策略。",
                dependencies=["business_service"],
            )
        )
    if re.search(r"日志|监控|告警|审计|权限|安全|隐私", text, re.IGNORECASE):
        modules.append(
            SolutionModule(
                name="Governance Layer",
                responsibility="处理权限、审计日志、监控与安全控制。",
                dependencies=["business_service"],
            )
        )
    modules.append(
        SolutionModule(
            name="Data Access",
            responsibility="维护数据读写、查询过滤和持久化约束。",
            dependencies=[],
        )
    )

    data_flow = [
        DataFlowStep(step="1", description="用户或内部角色提交需求触发操作。"),
        DataFlowStep(step="2", description="Experience Layer 完成输入校验并调用 Business Service。"),
        DataFlowStep(step="3", description="Business Service 按需求规则处理并访问 Data Access。"),
    ]
    if any(module.name == "Integration Layer" for module in modules):
        data_flow.append(DataFlowStep(step="4", description="Integration Layer 调用外部接口并统一处理失败重试。"))
        data_flow.append(DataFlowStep(step="5", description="结果回写业务状态，并返回页面或导出结果。"))
    else:
        data_flow.append(DataFlowStep(step="4", description="结果回写数据并返回页面或业务结果。"))

    interfaces = [
        InterfaceDraft(
            name="submitRequirement",
            purpose="提交业务操作或筛选条件。",
            inputs=["用户标识", "业务参数", "约束信息"],
            outputs=["处理结果", "状态反馈"],
        )
    ]
    if re.search(r"导出|export", text, re.IGNORECASE):
        interfaces.append(
            InterfaceDraft(
                name="exportReport",
                purpose="导出满足筛选条件的业务结果。",
                inputs=["筛选条件", "导出格式"],
                outputs=["导出任务状态", "文件地址或下载结果"],
            )
        )
    if re.search(r"api|接口|回调", text, re.IGNORECASE):
        interfaces.append(
            InterfaceDraft(
                name="syncExternalData",
                purpose="与外部系统交换主数据或状态数据。",
                inputs=["外部标识", "同步载荷"],
                outputs=["同步结果", "错误码"],
            )
        )

    milestones = [
        MilestoneItem(milestone="M1", goal="补齐澄清问题并冻结本期范围。"),
        MilestoneItem(milestone="M2", goal="完成方案评审与接口定义。"),
        MilestoneItem(milestone="M3", goal="完成开发联调与验收准备。"),
    ]

    inferred_goal = audit_output.confirmed_facts[0] if audit_output.confirmed_facts else "形成可执行的 MVP 方案草案。"
    return SolutionPlan(
        goal=f"围绕当前需求构建可评审方案：{_truncate(inferred_goal, 100)}",
        modules=modules,
        data_flow=data_flow,
        interfaces=interfaces,
        milestones=milestones,
    )


def build_report_json(
    *,
    requirement_text: str,
    audit_output: RequirementAuditOutput,
    clarity_output: ClarityScoreOutput,
    risk_output: RiskTaxonomyCheckOutput,
) -> RequirementReviewReport:
    requirement_items = renumber_requirement_items(audit_output.requirement_items)
    acceptance_criteria = renumber_acceptance_criteria(audit_output.acceptance_criteria)
    decisions = renumber_decisions(audit_output.decisions)
    scope_priority = infer_scope_priority(audit_output)
    solution_plan = infer_solution_plan(
        requirement_text=requirement_text,
        audit_output=audit_output,
        clarity_output=clarity_output,
    )

    summary_parts = [
        f"清晰度得分为 {clarity_output.score}/{clarity_output.threshold}。",
        "已通过方案预审门禁。" if clarity_output.passed else "未通过方案预审门禁，当前以澄清问题收敛为主。",
    ]
    if audit_output.missing_dimensions:
        summary_parts.append(f"当前仍缺失 {len(audit_output.missing_dimensions)} 个关键维度。")
    if risk_output.risks:
        summary_parts.append(f"已识别 {len(risk_output.risks)} 个主要风险。")

    next_actions = [
        "由产品或需求提出方补齐高优先级澄清问题。",
        "确认范围边界、约束和验收标准后复核清晰度门禁。",
    ]
    if clarity_output.passed:
        next_actions.append("组织方案评审并冻结接口与里程碑。")
    else:
        next_actions.append("在门禁通过前不要进入详细开发排期。")
    if risk_output.risks:
        next_actions.append("将高风险项纳入评审会议显式检查清单。")

    return RequirementReviewReport(
        summary=" ".join(summary_parts),
        confirmed_facts=audit_output.confirmed_facts or [_truncate(requirement_text, 120)],
        requirement_items=requirement_items,
        open_questions=audit_output.open_questions,
        scope_priority=scope_priority,
        solution_plan=solution_plan,
        risks=risk_output.risks,
        acceptance_criteria=acceptance_criteria,
        next_actions=next_actions,
        decisions=decisions,
    )


def build_analysis_markdown(
    audit_output: RequirementAuditOutput,
    clarity_output: ClarityScoreOutput,
) -> str:
    covered = "\n".join(
        f"- {item.dimension}: {'covered' if item.covered else 'missing'}"
        for item in audit_output.coverage_dimensions
    ) or "- 无"
    questions = "\n".join(
        f"- {item.question_id} {item.question}（{item.priority}）" for item in audit_output.open_questions
    ) or "- 无"
    facts = "\n".join(f"- {item}" for item in audit_output.confirmed_facts) or "- 无"
    requirements = "\n".join(
        f"- {item.requirement_id} {item.title}: {item.description}" for item in audit_output.requirement_items
    ) or "- 无"
    return (
        "# Requirement Analyst Output\n\n"
        "## Clarity Gate\n"
        f"- Score: {clarity_output.score}/{clarity_output.threshold}\n"
        f"- Passed: {clarity_output.passed}\n"
        f"- Rationale: {clarity_output.rationale}\n\n"
        "## Confirmed Facts\n"
        f"{facts}\n\n"
        "## Coverage\n"
        f"{covered}\n\n"
        "## Requirement Items\n"
        f"{requirements}\n\n"
        "## Open Questions\n"
        f"{questions}\n"
    )


def build_architecture_markdown(report: RequirementReviewReport, *, gate_opened: bool) -> str:
    modules = "\n".join(
        f"- {module.name}: {module.responsibility}" for module in report.solution_plan.modules
    ) or "- 无"
    data_flow = "\n".join(
        f"- Step {step.step}: {step.description}" for step in report.solution_plan.data_flow
    ) or "- 无"
    interfaces = "\n".join(
        f"- {item.name}: {item.purpose}" for item in report.solution_plan.interfaces
    ) or "- 无"
    milestones = "\n".join(
        f"- {item.milestone}: {item.goal}" for item in report.solution_plan.milestones
    ) or "- 无"
    return (
        "# Solution Architect Output\n\n"
        f"- Gate Opened: {gate_opened}\n"
        f"- Goal: {report.solution_plan.goal}\n\n"
        "## Scope Priority\n"
        f"- Must Have: {', '.join(report.scope_priority.must_have) or '无'}\n"
        f"- Should Have: {', '.join(report.scope_priority.should_have) or '无'}\n"
        f"- Deferred: {', '.join(report.scope_priority.deferred) or '无'}\n\n"
        "## Modules\n"
        f"{modules}\n\n"
        "## Data Flow\n"
        f"{data_flow}\n\n"
        "## Interfaces\n"
        f"{interfaces}\n\n"
        "## Milestones\n"
        f"{milestones}\n"
    )


def build_risk_review_markdown(risk_output: RiskTaxonomyCheckOutput) -> str:
    risks = "\n".join(
        f"- {item.risk_id} [{item.category}/{item.severity}] {item.title}: {item.mitigation}"
        for item in risk_output.risks
    ) or "- 无"
    missing = ", ".join(risk_output.missing_categories) or "无"
    notes = "\n".join(f"- {item}" for item in risk_output.review_notes) or "- 无"
    return (
        "# Risk Reviewer Output\n\n"
        "## Risks\n"
        f"{risks}\n\n"
        "## Missing Categories\n"
        f"- {missing}\n\n"
        "## Notes\n"
        f"{notes}\n"
    )
