from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.agents.api import agent_task_control_plane, agent_trace_sink
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RiskClass,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
)
from simorgh_core.app import app
from simorgh_core.config import get_settings

OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}
DEVICE_HEADERS = {"Authorization": "Bearer test-device-token"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    get_settings.cache_clear()
    asyncio.run(agent_task_control_plane.clear_for_test())
    agent_trace_sink.clear()
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(agent_task_control_plane.clear_for_test())
    agent_trace_sink.clear()
    get_settings.cache_clear()


def _task(
    *,
    request_id: UUID | None = None,
    input_text: str = "ریپازیتوری GitHub پروژه را بررسی کن",
) -> TaskEnvelope:
    now_ms = int(time.time() * 1_000)
    return TaskEnvelope(
        request_id=request_id or uuid4(),
        received_at_ms=now_ms,
        deadline_at_ms=now_ms + 60_000,
        locale="fa-IR",
        input_text=input_text,
        requested_outcome="گزارش ساختاریافتهٔ وضعیت ریپازیتوری",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=0,
            max_tool_calls=4,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def test_operator_authentication_is_required_for_agent_tasks(client: TestClient) -> None:
    task = _task()

    missing = client.post("/v1/agent-tasks", json=task.model_dump(mode="json"))
    device_credential = client.post(
        "/v1/agent-tasks",
        headers=DEVICE_HEADERS,
        json=task.model_dump(mode="json"),
    )

    assert missing.status_code == 401
    assert device_credential.status_code == 401


def test_explicit_persian_task_routes_with_zero_model_cost(client: TestClient) -> None:
    task = _task()

    response = client.post(
        "/v1/agent-tasks",
        headers=OPERATOR_HEADERS,
        json=task.model_dump(mode="json"),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["request_id"] == str(task.request_id)
    assert payload["phase"] == "routed"
    assert payload["routing_decision"]["selected_agent_id"] == "github.read"
    assert payload["routing_decision"]["method"] == "explicit_task_kind"
    assert payload["routing_decision"]["model_calls"] == 0
    assert payload["budget"]["committed"]["model_calls"] == 0
    assert payload["budget"]["committed"]["estimated_cost_microusd"] == 0

    traces = agent_trace_sink.for_request(task.request_id)
    assert len(traces) == 2
    encoded = "\n".join(event.model_dump_json() for event in traces)
    assert task.input_text not in encoded


def test_exact_submit_replay_reuses_stable_routing_decision(client: TestClient) -> None:
    task = _task()
    body = task.model_dump(mode="json")

    first = client.post("/v1/agent-tasks", headers=OPERATOR_HEADERS, json=body)
    replay = client.post("/v1/agent-tasks", headers=OPERATOR_HEADERS, json=body)

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["routing_decision"]["decision_id"] == (
        first.json()["routing_decision"]["decision_id"]
    )
    assert replay.json()["created_at_ms"] == first.json()["created_at_ms"]
    assert len(agent_trace_sink.for_request(task.request_id)) == 2


def test_request_identity_reuse_with_changed_content_conflicts(client: TestClient) -> None:
    request_id = uuid4()
    first = _task(request_id=request_id)
    changed = _task(
        request_id=request_id,
        input_text="این بار یک ورودی متفاوت با همان شناسه است",
    )

    accepted = client.post(
        "/v1/agent-tasks",
        headers=OPERATOR_HEADERS,
        json=first.model_dump(mode="json"),
    )
    conflict = client.post(
        "/v1/agent-tasks",
        headers=OPERATOR_HEADERS,
        json=changed.model_dump(mode="json"),
    )

    assert accepted.status_code == 202
    assert conflict.status_code == 409
    assert "reused with different task content" in conflict.json()["detail"]


def test_status_and_cancel_are_typed_and_idempotent(client: TestClient) -> None:
    task = _task()
    submitted = client.post(
        "/v1/agent-tasks",
        headers=OPERATOR_HEADERS,
        json=task.model_dump(mode="json"),
    )
    assert submitted.status_code == 202

    status_response = client.get(
        f"/v1/agent-tasks/{task.request_id}",
        headers=OPERATOR_HEADERS,
    )
    first_cancel = client.post(
        f"/v1/agent-tasks/{task.request_id}/cancel",
        headers=OPERATOR_HEADERS,
        json={"reason": "کاربر از طریق Voice گفت لغو"},
    )
    duplicate_cancel = client.post(
        f"/v1/agent-tasks/{task.request_id}/cancel",
        headers=OPERATOR_HEADERS,
        json={"reason": "دلیل متفاوت نباید هویت لغو را عوض کند"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["phase"] == "routed"
    assert first_cancel.status_code == 202
    assert first_cancel.json()["phase"] == "cancelled"
    assert first_cancel.json()["budget"]["cancelled"] is True
    assert first_cancel.json()["cancel_reason"] == "کاربر از طریق Voice گفت لغو"
    assert duplicate_cancel.status_code == 202
    assert duplicate_cancel.json()["cancel_reason"] == first_cancel.json()["cancel_reason"]
    assert duplicate_cancel.json()["updated_at_ms"] == first_cancel.json()["updated_at_ms"]


def test_expired_task_never_enters_router_or_model_path(client: TestClient) -> None:
    now_ms = int(time.time() * 1_000)
    task = TaskEnvelope(
        received_at_ms=now_ms - 2_000,
        deadline_at_ms=now_ms - 1_000,
        locale="fa-IR",
        input_text="این درخواست پیش از ورود به صف منقضی شده است",
        requested_outcome="نباید Route شود",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        risk_class=RiskClass.PLANNING,
        execution_mode=ExecutionMode.PLAN,
        budget=TaskBudget(max_model_calls=1),
    )

    response = client.post(
        "/v1/agent-tasks",
        headers=OPERATOR_HEADERS,
        json=task.model_dump(mode="json"),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["phase"] == "expired"
    assert payload["routing_decision"] is None
    assert payload["budget"]["committed"]["model_calls"] == 0
    assert agent_trace_sink.for_request(task.request_id) == ()


def test_unknown_task_status_and_cancel_return_not_found(client: TestClient) -> None:
    request_id = uuid4()

    status_response = client.get(
        f"/v1/agent-tasks/{request_id}",
        headers=OPERATOR_HEADERS,
    )
    cancel_response = client.post(
        f"/v1/agent-tasks/{request_id}/cancel",
        headers=OPERATOR_HEADERS,
        json={"reason": "unknown"},
    )

    assert status_response.status_code == 404
    assert cancel_response.status_code == 404
