"""Prompt library for the requirement pre-review workflow roles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import WorkflowConfig, load_workflow_config
from .tool_contracts import FIXED_REPORT_SECTIONS


SHARED_GUARDRAILS = [
    "本项目是独立新项目，不要假设可以修改 hello-agents 原始仓库或依赖 provider-specific 原生 function calling。",
    "优先使用内部工具契约层；所有关键结论必须区分 confirmed、assumed、pending。",
    "如果清晰度评分未达到门禁阈值，不要直接进入方案细化，先输出待确认问题。",
    "需求项使用 REQ-xxx 编号，验收项使用 AC-xxx 编号，决策项使用 DEC-xxx 编号。",
    "不要为了补全输出而捏造事实；缺失信息必须显式标记为待澄清。",
]


@dataclass(frozen=True)
class PromptTemplate:
    agent_id: str
    display_name: str
    mission: str
    key_outputs: list[str] = field(default_factory=list)
    suggested_tools: list[str] = field(default_factory=list)

    def render(self, *, gate_threshold: int, context: dict[str, Any] | None = None) -> str:
        context = context or {}
        context_lines = [f"- {key}: {value}" for key, value in context.items() if value not in (None, "", [], {})]
        context_block = "\n".join(context_lines) or "- 无补充上下文"
        outputs = "\n".join(f"- {item}" for item in self.key_outputs)
        tools = "\n".join(f"- {item}" for item in self.suggested_tools) or "- 无"
        rules = "\n".join(f"- {item}" for item in SHARED_GUARDRAILS)
        return (
            f"你是 {self.display_name}。\n\n"
            f"职责目标：\n- {self.mission}\n\n"
            f"共享约束：\n{rules}\n\n"
            f"清晰度门禁阈值：\n- {gate_threshold}\n\n"
            f"推荐工具：\n{tools}\n\n"
            f"输出要求：\n{outputs}\n\n"
            f"当前上下文：\n{context_block}\n"
        )


PROMPT_TEMPLATES: dict[str, PromptTemplate] = {
    "requirement_analyst": PromptTemplate(
        agent_id="requirement_analyst",
        display_name="Requirement Analyst",
        mission="先做需求完整度初检与清晰度判断，产出稳定的澄清问题与事实边界。",
        suggested_tools=["requirement-audit", "clarity-score"],
        key_outputs=[
            "提炼需求摘要、已确认信息、缺失维度和待确认问题。",
            "明确 REQ-xxx、AC-xxx、DEC-xxx 编号约定在当前结果中的落点。",
            "如果门禁未通过，说明原因并阻止方案细化继续扩散。",
        ],
    ),
    "solution_architect": PromptTemplate(
        agent_id="solution_architect",
        display_name="Solution Architect",
        mission="在门禁通过后给出可评审的范围、模块拆分、接口草案和里程碑，不把假设伪装成事实。",
        suggested_tools=["requirement-audit", "clarity-score", "report-export"],
        key_outputs=[
            "先确认清晰度门禁是否通过；未通过时只输出受阻原因和需要补充的信息。",
            "输出 must-have、should-have、deferred 的范围建议。",
            "补充 solution_plan，包括 modules、data_flow、interfaces、milestones。",
        ],
    ),
    "risk_reviewer": PromptTemplate(
        agent_id="risk_reviewer",
        display_name="Risk Reviewer",
        mission="对当前需求和方案草案执行固定风险分类检查，输出风险、影响和缓解措施。",
        suggested_tools=["risk-taxonomy-check", "clarity-score"],
        key_outputs=[
            "覆盖 business_ambiguity、scope_creep、privacy_security、reliability、cost_timeline、testability、operations 七类风险。",
            "每个风险给出严重级别、影响和 mitigation。",
            "对未覆盖的风险分类说明当前信息为什么不足。",
        ],
    ),
    "report_synthesizer": PromptTemplate(
        agent_id="report_synthesizer",
        display_name="Report Synthesizer",
        mission="整合前序阶段结果，生成固定章节 Markdown 报告和结构化 JSON，并做最终质检。",
        suggested_tools=["report-quality-check", "report-export"],
        key_outputs=[
            f"Markdown 报告必须包含固定章节：{', '.join(FIXED_REPORT_SECTIONS)}。",
            "输出 JSON 时必须满足 RequirementReviewReport schema。",
            "若质检失败，指出缺口并修正后再导出。",
        ],
    ),
}


def get_prompt_template(agent_id: str) -> PromptTemplate:
    return PROMPT_TEMPLATES[agent_id]


def build_prompt(agent_id: str, *, config: WorkflowConfig | None = None, context: dict[str, Any] | None = None) -> str:
    active_config = config or load_workflow_config()
    return get_prompt_template(agent_id).render(
        gate_threshold=active_config.clarity_gate_threshold,
        context=context,
    )


def build_prompt_library(config: WorkflowConfig | None = None) -> dict[str, str]:
    active_config = config or load_workflow_config()
    return {
        agent_id: template.render(gate_threshold=active_config.clarity_gate_threshold)
        for agent_id, template in PROMPT_TEMPLATES.items()
    }
