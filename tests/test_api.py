from __future__ import annotations

from fastapi.testclient import TestClient

from backend.agents.profiles import PLATFORM_REQUIREMENT_PRE_REVIEW_AGENT_ID


def test_health_endpoint_returns_ok(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "timestamp" in payload


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
