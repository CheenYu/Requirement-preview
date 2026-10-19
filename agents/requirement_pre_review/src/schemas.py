"""Structured output schemas for requirement pre-review results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RequirementItem(BaseModel):
    requirement_id: str
    title: str
    description: str
    status: Literal["confirmed", "assumed", "pending"]


class OpenQuestionItem(BaseModel):
    question_id: str
    question: str
    impact: str
    priority: Literal["high", "medium", "low"] = "medium"


class ScopePriority(BaseModel):
    must_have: list[str] = Field(default_factory=list)
    should_have: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


class SolutionModule(BaseModel):
    name: str
    responsibility: str
    dependencies: list[str] = Field(default_factory=list)


class DataFlowStep(BaseModel):
    step: str
    description: str


class InterfaceDraft(BaseModel):
    name: str
    purpose: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class MilestoneItem(BaseModel):
    milestone: str
    goal: str


class SolutionPlan(BaseModel):
    goal: str = ""
    modules: list[SolutionModule] = Field(default_factory=list)
    data_flow: list[DataFlowStep] = Field(default_factory=list)
    interfaces: list[InterfaceDraft] = Field(default_factory=list)
    milestones: list[MilestoneItem] = Field(default_factory=list)


class RiskItem(BaseModel):
    risk_id: str
    category: Literal[
        "business_ambiguity",
        "scope_creep",
        "privacy_security",
        "reliability",
        "cost_timeline",
        "testability",
        "operations",
    ]
    title: str
    impact: str
    mitigation: str
    severity: Literal["high", "medium", "low"]
    owner: str = ""


class AcceptanceCriterionItem(BaseModel):
    criterion_id: str
    description: str
    testable: bool = True


class DecisionLogItem(BaseModel):
    decision_id: str
    topic: str
    status: Literal["confirmed", "pending", "blocked"]
    rationale: str
    owner: str = ""


class RequirementReviewReport(BaseModel):
    summary: str = ""
    confirmed_facts: list[str] = Field(default_factory=list)
    requirement_items: list[RequirementItem] = Field(default_factory=list)
    open_questions: list[OpenQuestionItem] = Field(default_factory=list)
    scope_priority: ScopePriority = Field(default_factory=ScopePriority)
    solution_plan: SolutionPlan = Field(default_factory=SolutionPlan)
    risks: list[RiskItem] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterionItem] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    decisions: list[DecisionLogItem] = Field(default_factory=list)


class WorkflowIntermediateArtifacts(BaseModel):
    audit: dict = Field(default_factory=dict)
    clarity: dict = Field(default_factory=dict)
    analysis_markdown: str = ""
    architecture_markdown: str = ""
    risk_review_markdown: str = ""


class EvaluationResult(BaseModel):
    case_id: str
    schema_passed: bool
    section_completeness: int = Field(ge=0, le=100)
    gate_opened: bool
    tool_error_count: int = 0
    tool_call_count: int = 0
    workflow_latency_ms: int = 0
