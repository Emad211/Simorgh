from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

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
from simorgh_core.app import app
from simorgh_core.config import get_settings

OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}


def _configure_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    get_settings.cache_clear()


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
