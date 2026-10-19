"""Second-pass clarification workflow helpers."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.models import TaskRecord

from .config import WorkflowConfig, load_workflow_config
from .workflow import WorkflowResult, run_workflow


class ClarificationAnswer(BaseModel):
    question_id: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)

    @field_validator("question_id", "answer")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("clarification answer fields cannot be empty")
        return cleaned


class FollowUpInput(BaseModel):
    answers: list[ClarificationAnswer] = Field(default_factory=list)
    additional_context: list[str] = Field(default_factory=list)
    title: str | None = None

    @field_validator("additional_context")
    @classmethod
    def strip_context(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class FollowUpResult(BaseModel):
    version: str = "v2"
    source_task_id: str
    status: str
    answered_question_count: int
    previous_gate_opened: bool
    gate_opened: bool
    previous_clarity_score: int = 0
    clarity_score: int = 0
    report_markdown: str
    report_json: dict[str, Any]
    diff_markdown: str
    run_dir: str
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    answers: list[dict[str, str]] = Field(default_factory=list)
    open_questions_before: list[dict[str, Any]] = Field(default_factory=list)
    open_questions_after: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class RequirementFollowUpAgent:
    """Runs a second workflow pass using user answers to the first-pass questions."""

    def __init__(self, *, config: WorkflowConfig | None = None) -> None:
        self.config = config or load_workflow_config()
        self.agent_id = "requirement_follow_up"

    def run(self, task: TaskRecord, follow_up_input: FollowUpInput) -> FollowUpResult:
        if not follow_up_input.answers and not follow_up_input.additional_context:
            raise ValueError("follow-up requires at least one answer or additional context")

        previous_report = _get_report_json(task)
        previous_markdown = str(task.artifacts.get("report_markdown") or task.output or "")
        open_questions_before = extract_open_questions(previous_report)
        run_dir = _build_follow_up_run_dir(task)
        merged_context = build_follow_up_context(
            task=task,
            answers=follow_up_input.answers,
            additional_context=follow_up_input.additional_context,
        )
        workflow_result = run_workflow(
            {
                "title": follow_up_input.title or f"{task.title} V2",
                "requirement_text": merged_context["requirement_text"],
                "target_users": _coerce_string_list(task.metadata.get("target_users")),
                "explicit_constraints": _coerce_string_list(task.metadata.get("explicit_constraints")),
                "supplemental_context": merged_context["supplemental_context"],
                "metadata": {
                    **task.metadata,
                    "follow_up_version": "v2",
                    "source_task_id": task.task_id,
                    "answered_questions": [item.model_dump(mode="json") for item in follow_up_input.answers],
                },
                "task_id": f"{task.task_id}-follow-up-v2",
                "run_dir": str(run_dir),
            },
            config=self.config,
        )
        return build_follow_up_result(
            task=task,
            follow_up_input=follow_up_input,
            previous_report=previous_report,
            previous_markdown=previous_markdown,
            open_questions_before=open_questions_before,
            workflow_result=workflow_result,
        )


def extract_open_questions(report_payload: dict[str, Any]) -> list[dict[str, Any]]:
    questions = report_payload.get("open_questions") if isinstance(report_payload, dict) else []
    if not isinstance(questions, list):
        return []
    extracted: list[dict[str, Any]] = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id", "")).strip()
        question = str(item.get("question", "")).strip()
        if question_id and question:
            extracted.append(
                {
                    "question_id": question_id,
                    "question": question,
                    "impact": str(item.get("impact", "")).strip(),
                    "priority": str(item.get("priority", "")).strip() or "medium",
                }
            )
    return extracted


def build_follow_up_context(
    *,
    task: TaskRecord,
    answers: list[ClarificationAnswer],
    additional_context: list[str],
) -> dict[str, Any]:
    answer_lines = [f"{item.question_id}: {item.answer}" for item in answers]
    context_lines = list(additional_context)
    follow_up_text_parts = []
    if answer_lines:
        follow_up_text_parts.extend(["", "二轮澄清回答：", *answer_lines])
    if context_lines:
        follow_up_text_parts.extend(["", "二轮补充上下文：", *context_lines])
    requirement_text = task.input.strip() + "\n" + "\n".join(follow_up_text_parts).strip()
    supplemental_context = _coerce_string_list(task.metadata.get("supplemental_context"))
    supplemental_context.extend(answer_lines)
    supplemental_context.extend(context_lines)
    return {
        "requirement_text": requirement_text.strip(),
        "supplemental_context": supplemental_context,
    }


def build_follow_up_result(
    *,
    task: TaskRecord,
    follow_up_input: FollowUpInput,
    previous_report: dict[str, Any],
    previous_markdown: str,
    open_questions_before: list[dict[str, Any]],
    workflow_result: WorkflowResult,
) -> FollowUpResult:
    report_json = workflow_result.report_json.model_dump(mode="json")
    diff_markdown = build_markdown_diff(previous_markdown, workflow_result.report_markdown)
    return FollowUpResult(
        source_task_id=task.task_id,
        status=workflow_result.status,
        answered_question_count=len(follow_up_input.answers),
        previous_gate_opened=bool(task.artifacts.get("gate_opened", False)),
        gate_opened=workflow_result.gate_opened,
        previous_clarity_score=int((task.artifacts.get("metrics") or {}).get("clarity_score", 0)),
        clarity_score=int(workflow_result.metrics.get("clarity_score", 0)),
        report_markdown=workflow_result.report_markdown,
        report_json=report_json,
        diff_markdown=diff_markdown,
        run_dir=workflow_result.run_dir,
        artifact_paths=workflow_result.artifact_paths,
        answers=[item.model_dump(mode="json") for item in follow_up_input.answers],
        open_questions_before=open_questions_before,
        open_questions_after=extract_open_questions(report_json),
        metrics=workflow_result.metrics,
    )


def persist_follow_up_result(result: FollowUpResult) -> str:
    path = Path(result.run_dir) / "follow_up.json"
    path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def build_markdown_diff(previous_markdown: str, next_markdown: str) -> str:
    diff_lines = difflib.unified_diff(
        previous_markdown.splitlines(),
        next_markdown.splitlines(),
        fromfile="report_v1.md",
        tofile="report_v2.md",
        lineterm="",
    )
    return "\n".join(diff_lines) + "\n"


def _get_report_json(task: TaskRecord) -> dict[str, Any]:
    report = task.artifacts.get("report_json")
    if isinstance(report, dict):
        return report
    return {}


def _build_follow_up_run_dir(task: TaskRecord) -> Path:
    base_run_dir = Path(str(task.artifacts.get("run_dir") or "data/task_runs")) / "followups"
    run_dir = base_run_dir / "v2"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    cleaned = str(value).strip()
    return [cleaned] if cleaned else []
