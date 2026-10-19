from __future__ import annotations

from fastapi.testclient import TestClient

from backend.agents.profiles import PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID


def test_health_endpoint_returns_ok(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "timestamp" in payload


def test_health_endpoint_allows_local_static_frontend_origin(api_client: TestClient) -> None:
    response = api_client.options(
        "/health",
        headers={
            "Origin": "http://127.0.0.1:8765",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_agents_endpoint_returns_requirement_pre_review_agent(api_client: TestClient) -> None:
    response = api_client.get("/agents")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["agents"]) == 1
    assert payload["agents"][0]["agent_id"] == PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID


def test_tasks_create_run_and_get_round_trip(api_client: TestClient, clear_requirement_text: str) -> None:
    create_response = api_client.post(
        "/tasks",
        json={
            "title": "订单导出预审",
            "input": clear_requirement_text,
            "agent_id": PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID,
            "metadata": {
                "title": "订单导出预审",
                "target_users": ["运营", "客服"],
                "explicit_constraints": ["本月上线", "复用现有权限模型"],
            },
        },
    )

    assert create_response.status_code == 201
    task_id = create_response.json()["task_id"]
    assert create_response.json()["status"] == "pending"

    run_response = api_client.post(f"/tasks/{task_id}/run", json={"background": False})

    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["status"] == "completed"
    assert run_payload["output"].startswith("# 订单导出预审")
    assert run_payload["artifacts"]["gate_opened"] is True
    assert run_payload["artifacts"]["artifact_paths"]["input_text"].endswith("input.txt")
    assert run_payload["artifacts"]["metrics"]["tool_failure_count"] == 0

    get_response = api_client.get(f"/tasks/{task_id}")

    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["task_id"] == task_id
    assert get_payload["status"] == "completed"
    assert get_payload["metadata"]["quality_passed"] is True
    assert get_payload["metadata"]["risk_count"] >= 1
    assert get_payload["metadata"]["decision_count"] >= 1
    assert get_payload["metadata"]["tool_call_count"] >= 4
    assert get_payload["metadata"]["tool_failure_count"] == 0
    assert get_payload["metadata"]["elapsed_ms"] >= 0


def test_completed_task_accepts_follow_up_answers_and_returns_v2_artifacts(
    api_client: TestClient,
    ambiguous_requirement_text: str,
) -> None:
    create_response = api_client.post(
        "/tasks",
        json={
            "title": "异常订单管理页",
            "input": ambiguous_requirement_text,
            "agent_id": PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID,
            "metadata": {"title": "异常订单管理页"},
        },
    )
    task_id = create_response.json()["task_id"]
    run_response = api_client.post(f"/tasks/{task_id}/run", json={"background": False})

    assert run_response.status_code == 200
    assert run_response.json()["artifacts"]["gate_opened"] is False

    follow_up_response = api_client.post(
        f"/tasks/{task_id}/follow-up",
        json={
            "title": "异常订单管理页 V2",
            "answers": [
                {"question_id": "Q-001", "answer": "目标是降低运营处理异常订单的人工成本。"},
                {"question_id": "Q-002", "answer": "目标用户是运营和客服主管。"},
                {"question_id": "Q-003", "answer": "本期范围包括异常订单列表、状态筛选、处理备注和操作日志。"},
                {"question_id": "Q-004", "answer": "约束是在本月上线，并复用现有后台权限。"},
                {"question_id": "Q-005", "answer": "依赖订单 API、异常状态字段和处理日志表。"},
                {"question_id": "Q-006", "answer": "性能要求是 1000 条异常订单 2 秒内完成筛选，操作需要审计日志。"},
                {"question_id": "Q-007", "answer": "验收标准是运营能按状态筛选异常订单并保存处理备注。"},
            ],
        },
    )

    assert follow_up_response.status_code == 200
    payload = follow_up_response.json()
    follow_up = payload["artifacts"]["follow_up"]
    assert payload["metadata"]["follow_up_version"] == "v2"
    assert payload["metadata"]["follow_up_gate_opened"] is True
    assert follow_up["gate_opened"] is True
    assert follow_up["previous_gate_opened"] is False
    assert follow_up["answered_question_count"] == 7
    assert follow_up["open_questions_before"]
    assert follow_up["open_questions_after"] == []
    assert follow_up["artifact_paths"]["follow_up"].endswith("follow_up.json")
    assert "--- report_v1.md" in follow_up["diff_markdown"]
    assert "+++ report_v2.md" in follow_up["diff_markdown"]


def test_follow_up_requires_completed_task(api_client: TestClient, ambiguous_requirement_text: str) -> None:
    create_response = api_client.post(
        "/tasks",
        json={
            "title": "未运行需求",
            "input": ambiguous_requirement_text,
            "agent_id": PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID,
            "metadata": {},
        },
    )
    task_id = create_response.json()["task_id"]

    response = api_client.post(
        f"/tasks/{task_id}/follow-up",
        json={"answers": [{"question_id": "Q-001", "answer": "目标是降低处理成本。"}]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "task_not_completed"


def test_follow_up_rejects_empty_payload(api_client: TestClient, clear_requirement_text: str) -> None:
    create_response = api_client.post(
        "/tasks",
        json={
            "title": "订单导出预审",
            "input": clear_requirement_text,
            "agent_id": PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID,
            "metadata": {},
        },
    )
    task_id = create_response.json()["task_id"]
    api_client.post(f"/tasks/{task_id}/run", json={"background": False})

    response = api_client.post(f"/tasks/{task_id}/follow-up", json={})

    assert response.status_code == 422
    assert response.json()["code"] == "follow_up_empty"


def test_create_task_returns_not_found_for_unknown_agent(api_client: TestClient) -> None:
    response = api_client.post(
        "/tasks",
        json={
            "title": "unknown",
            "input": "做一个管理页面",
            "agent_id": "missing-agent",
            "metadata": {},
        },
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "agent_not_found"


def test_get_task_returns_not_found_for_unknown_task(api_client: TestClient) -> None:
    response = api_client.get("/tasks/missing-task")

    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "task_not_found"
