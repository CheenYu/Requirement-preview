from pathlib import Path

from agents.requirement_pre_review.src.follow_up import (
    ClarificationAnswer,
    FollowUpInput,
    RequirementFollowUpAgent,
    build_follow_up_context,
    extract_open_questions,
    persist_follow_up_result,
)
from agents.requirement_pre_review.src.workflow import run_workflow
from backend.models import TaskRecord, TaskStatus


def _follow_up_answers() -> list[ClarificationAnswer]:
    return [
        ClarificationAnswer(question_id="Q-001", answer="目标是降低运营处理异常订单的人工成本。"),
        ClarificationAnswer(question_id="Q-002", answer="目标用户是运营和客服主管。"),
        ClarificationAnswer(question_id="Q-003", answer="本期范围包括异常订单列表、状态筛选、处理备注和操作日志。"),
        ClarificationAnswer(question_id="Q-004", answer="约束是在本月上线，并复用现有后台权限。"),
        ClarificationAnswer(question_id="Q-005", answer="依赖订单 API、异常状态字段和处理日志表。"),
        ClarificationAnswer(question_id="Q-006", answer="性能要求是 1000 条异常订单 2 秒内完成筛选，操作需要审计日志。"),
        ClarificationAnswer(question_id="Q-007", answer="验收标准是运营能按状态筛选异常订单并保存处理备注。"),
    ]


def test_extract_open_questions_keeps_stable_question_fields() -> None:
    questions = extract_open_questions(
        {
            "open_questions": [
                {
                    "question_id": "Q-001",
                    "question": "业务目标是什么？",
                    "impact": "影响方案取舍。",
                    "priority": "high",
                },
                {"question_id": "", "question": "ignored"},
                "invalid",
            ]
        }
    )

    assert questions == [
        {
            "question_id": "Q-001",
            "question": "业务目标是什么？",
            "impact": "影响方案取舍。",
            "priority": "high",
        }
    ]


def test_build_follow_up_context_merges_original_input_answers_and_context(
    ambiguous_requirement_text: str,
) -> None:
    task = TaskRecord(
        title="模糊需求",
        input=ambiguous_requirement_text,
        agent_id="requirement_pre_review",
        metadata={"supplemental_context": ["已有后台基础框架。"]},
    )

    payload = build_follow_up_context(
        task=task,
        answers=[ClarificationAnswer(question_id="Q-001", answer="目标是降低处理成本。")],
        additional_context=["只做运营后台。"],
    )

    assert payload["requirement_text"].startswith(ambiguous_requirement_text)
    assert "Q-001: 目标是降低处理成本。" in payload["requirement_text"]
    assert "只做运营后台。" in payload["requirement_text"]
    assert payload["supplemental_context"] == [
        "已有后台基础框架。",
        "Q-001: 目标是降低处理成本。",
        "只做运营后台。",
    ]


def test_follow_up_agent_generates_v2_report_diff_and_persisted_artifact(
    tmp_path: Path,
    workflow_config,
    ambiguous_requirement_text: str,
) -> None:
    first_pass = run_workflow(
        {
            "title": "异常订单管理页",
            "requirement_text": ambiguous_requirement_text,
            "run_dir": str(tmp_path / "v1"),
            "task_id": "task-follow-up",
        },
        config=workflow_config,
    )
    task = TaskRecord(
        task_id="task-follow-up",
        title="异常订单管理页",
        input=ambiguous_requirement_text,
        agent_id="requirement_pre_review",
        status=TaskStatus.completed,
        output=first_pass.report_markdown,
        artifacts={
            "run_dir": first_pass.run_dir,
            "report_markdown": first_pass.report_markdown,
            "report_json": first_pass.report_json.model_dump(mode="json"),
            "gate_opened": first_pass.gate_opened,
            "metrics": first_pass.metrics,
        },
    )

    result = RequirementFollowUpAgent(config=workflow_config).run(
        task,
        FollowUpInput(answers=_follow_up_answers(), title="异常订单管理页 V2"),
    )
    artifact_path = persist_follow_up_result(result)

    assert result.status == "completed"
    assert result.previous_gate_opened is False
    assert result.gate_opened is True
    assert result.clarity_score > result.previous_clarity_score
    assert result.answered_question_count == 7
    assert result.open_questions_before
    assert result.open_questions_after == []
    assert "--- report_v1.md" in result.diff_markdown
    assert "+++ report_v2.md" in result.diff_markdown
    assert Path(artifact_path).exists()
