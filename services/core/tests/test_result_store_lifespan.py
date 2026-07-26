from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.agents.invocations import InvocationEffect
from simorgh_core.agents.result_authority import (
    AuthoritativeSpecialistResult,
    build_authoritative_plan_result,
    default_result_schema_registry,
)
from simorgh_core.agents.result_store import (
    ResultStoreSchemaError,
    SQLiteResultStore,
    result_store_registry,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistExecutionOutcome,
    SpecialistExecutionResult,
)
from simorgh_core.app import app, lifespan
from simorgh_core.config import get_settings


def _record() -> AuthoritativeSpecialistResult:
    execution = SpecialistExecutionResult(
        request_id=uuid4(),
        invocation_id=uuid4(),
        agent_id="development.planner",
        agent_version="1.0.0",
        effect=InvocationEffect.PROPOSAL,
        outcome=SpecialistExecutionOutcome.COMPLETED,
        output_contract="simorgh.typed-plan.v1",
        payload={"summary": "نتیجه پایدار", "steps": ["ثبت"]},
        started_at_ms=2_000,
        completed_at_ms=3_000,
    )
    return build_authoritative_plan_result(
        execution_result=execution,
        registry=default_result_schema_registry(),
    )


def test_application_lifespan_loads_and_resets_result_authority() -> None:
    path = Path(get_settings().simorgh_result_store_path)
    record = _record()
    store = SQLiteResultStore(path)
    store.claim(record)
    store.close()

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert result_store_registry.current().get(record.result_id) == record

    assert result_store_registry.current().load() == []


def test_result_schema_failure_aborts_startup() -> None:
    path = Path(get_settings().simorgh_result_store_path)
    store = SQLiteResultStore(path)
    store.close()
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE result_store_metadata SET value = '999' WHERE key = 'schema_version'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        ResultStoreSchemaError,
        match="unsupported result store schema",
    ), TestClient(app):
        pass


def test_core_rejects_result_and_invocation_path_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared.sqlite3"
    monkeypatch.setenv("SIMORGH_INVOCATION_STORE_PATH", str(shared))
    monkeypatch.setenv("SIMORGH_RESULT_STORE_PATH", str(shared))
    get_settings.cache_clear()

    async def enter() -> None:
        async with lifespan(None):  # type: ignore[arg-type]
            raise AssertionError("lifespan must not start")

    with pytest.raises(RuntimeError, match="must be distinct"):
        asyncio.run(enter())
