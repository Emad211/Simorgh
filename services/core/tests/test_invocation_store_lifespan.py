from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.agents.budget import BudgetSnapshot
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RiskClass,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.invocation_store import (
    SQLiteInvocationStore,
    invocation_store_registry,
)
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    InvocationPhase,
    InvocationStoreSchemaError,
    canonical_fingerprint,
)
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import (
    SQLiteAgentTaskStore,
    new_task_store_entry,
)
from simorgh_core.app import app
from simorgh_core.config import get_settings

OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}


def _configure_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    get_settings.cache_clear()


def _routing_task() -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text="وضعیت پروژه را بررسی کن",
        requested_outcome="گزارش پایدار",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=1,
            max_tool_calls=0,
            max_input_tokens=10_000,
            max_output_tokens=1_000,
            max_estimated_cost_microusd=100_000,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def test_application_startup_recovers_interrupted_invocation_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_credentials(monkeypatch)
    path = Path(get_settings().simorgh_invocation_store_path)
    invocation_id = uuid4()
    store = SQLiteInvocationStore(path, recover_interrupted=False)
    store.begin(
        invocation_id=invocation_id,
        request_id=uuid4(),
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.search",
        input_fingerprint=canonical_fingerprint({"query": "Simorgh"}),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.search",
        connector_id="github",
    )
    store.close()

    with TestClient(app) as client:
        response = client.get("/health")
        recovered = invocation_store_registry.current().get(invocation_id)
        assert response.status_code == 200
        assert recovered.state == InvocationPhase.UNKNOWN
        assert recovered.failure_code == "process_interrupted"

    assert invocation_store_registry.current().load() == []


def test_startup_reconciles_reserved_invocation_usage_into_unknown_parent_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_credentials(monkeypatch)
    settings = get_settings()
    task = _routing_task()
    task_store = SQLiteAgentTaskStore(settings.simorgh_agent_task_store_path)
    task_store.upsert(
        new_task_store_entry(
            AgentTaskRecord(
                request_id=task.request_id,
                phase=AgentTaskPhase.ROUTING,
                created_at_ms=2_000,
                updated_at_ms=2_000,
                task=task,
                budget=BudgetSnapshot(
                    request_id=task.request_id,
                    limits=task.budget,
                    committed=UsageVector(),
                    reserved=UsageVector(),
                    elapsed_ms=100,
                    cancelled=False,
                ),
                detail="routing claim before simulated crash",
            )
        )
    )
    task_store.close()

    invocation_id = uuid4()
    invocation_usage = UsageVector(
        model_calls=1,
        input_tokens=600,
        output_tokens=200,
        estimated_cost_microusd=4_000,
    )
    invocation_store = SQLiteInvocationStore(
        settings.simorgh_invocation_store_path,
        recover_interrupted=False,
    )
    invocation_store.begin(
        invocation_id=invocation_id,
        request_id=task.request_id,
        agent_id="system.specialist-router",
        agent_version="1.0.0",
        operation="classify-primary-specialist",
        input_fingerprint=canonical_fingerprint({"task": str(task.request_id)}),
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="fake",
        model_id="cheap-fast",
    )
    invocation_store.reserve(
        invocation_id=invocation_id,
        usage=invocation_usage,
    )
    invocation_store.close()

    with TestClient(app) as client:
        status_response = client.get(
            f"/v1/agent-tasks/{task.request_id}",
            headers=OPERATOR_HEADERS,
        )
        recovered_invocation = invocation_store_registry.current().get(
            invocation_id
        )

    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["phase"] == "unknown"
    assert payload["budget"]["committed"] == invocation_usage.model_dump(
        mode="json"
    )
    assert payload["budget"]["reserved"] == UsageVector().model_dump(
        mode="json"
    )
    assert recovered_invocation.state == InvocationPhase.UNKNOWN
    assert recovered_invocation.committed_usage == invocation_usage


def test_invocation_schema_failure_aborts_startup_and_clean_path_can_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_credentials(monkeypatch)
    path = Path(get_settings().simorgh_invocation_store_path)
    store = SQLiteInvocationStore(path)
    store.close()
    connection = sqlite3.connect(path)
    connection.execute(
        """
        UPDATE invocation_store_metadata
        SET value = '999'
        WHERE key = 'schema_version'
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        InvocationStoreSchemaError,
        match="unsupported invocation store schema",
    ), TestClient(app):
        pass

    path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    get_settings.cache_clear()

    with TestClient(app) as restarted:
        response = restarted.get("/health")
        assert response.status_code == 200


def test_ungoverned_direct_model_endpoint_is_operator_bound_and_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_credentials(monkeypatch)
    payload = {
        "input": "این متن نباید مستقیماً به Provider برسد",
        "model": "arbitrary-model",
    }

    with TestClient(app) as client:
        missing = client.post("/v1/model/text", json=payload)
        device_only = client.post(
            "/v1/model/text",
            headers={"Authorization": "Bearer test-device-token"},
            json=payload,
        )
        operator = client.post(
            "/v1/model/text",
            headers=OPERATOR_HEADERS,
            json=payload,
        )

    assert missing.status_code == 401
    assert device_only.status_code == 401
    assert operator.status_code == 410
    assert operator.json()["detail"]["code"] == (
        "ungoverned_model_endpoint_disabled"
    )
