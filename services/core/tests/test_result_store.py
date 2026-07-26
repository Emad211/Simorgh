from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
)
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    ResultReplayDisposition,
    RetentionDisposition,
    build_authoritative_plan_result,
    build_test_artifact_reference,
    default_result_schema_registry,
)
from simorgh_core.agents.result_service import (
    ResultAuthorityUnavailableError,
    ResultInvocationMismatchError,
    ResultReplayConflictError,
    SpecialistResultTerminalizer,
)
from simorgh_core.agents.result_store import (
    InMemoryResultStore,
    ResultConflictError,
    ResultStoreCorruptionError,
    ResultStoreInUseError,
    ResultStoreSchemaError,
    SQLiteResultStore,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistExecutionOutcome,
    SpecialistExecutionResult,
    SpecialistReplayDisposition,
)
from simorgh_core.agents.tracing import InMemoryTraceSink, TraceEventKind


def _execution_result(
    *,
    request_id: UUID | None = None,
    invocation_id: UUID | None = None,
    summary: str = "پاسخ پایدار",
) -> SpecialistExecutionResult:
    return SpecialistExecutionResult(
        request_id=request_id or uuid4(),
        invocation_id=invocation_id or uuid4(),
        agent_id="development.planner",
        agent_version="1.0.0",
        effect=InvocationEffect.PROPOSAL,
        outcome=SpecialistExecutionOutcome.COMPLETED,
        output_contract="simorgh.typed-plan.v1",
        payload={
            "summary": summary,
            "steps": ["ثبت", "بازپخش"],
            "unresolved_risks": [],
            "verification_requirements": ["SQLite reopen"],
        },
        started_at_ms=2_000,
        completed_at_ms=3_000,
    )


def _complete_invocation(
    store: InMemoryInvocationStore | SQLiteInvocationStore,
    execution: SpecialistExecutionResult,
) -> None:
    store.begin(
        invocation_id=execution.invocation_id,
        request_id=execution.request_id,
        agent_id=execution.agent_id,
        agent_version=execution.agent_version,
        operation="specialist.execute",
        input_fingerprint="c" * 64,
        kind=InvocationKind.SPECIALIST,
        effect=execution.effect,
    )
    store.complete(
        invocation_id=execution.invocation_id,
        result_payload=execution.model_dump(mode="json"),
        committed_usage=execution.committed_usage,
    )


def _terminalizer(
    *,
    invocation_store: InMemoryInvocationStore | SQLiteInvocationStore,
    result_store: InMemoryResultStore | SQLiteResultStore,
    traces: InMemoryTraceSink | None = None,
) -> SpecialistResultTerminalizer:
    return SpecialistResultTerminalizer(
        invocation_store=invocation_store,
        result_store=result_store,
        schema_registry=default_result_schema_registry(),
        trace_sink=traces,
    )


def test_memory_terminalization_is_immutable_and_replay_safe() -> None:
    invocation_store = InMemoryInvocationStore()
    result_store = InMemoryResultStore()
    traces = InMemoryTraceSink()
    execution = _execution_result()
    _complete_invocation(invocation_store, execution)
    terminalizer = _terminalizer(
        invocation_store=invocation_store,
        result_store=result_store,
        traces=traces,
    )

    first = terminalizer.terminalize(execution)
    replay = terminalizer.terminalize(
        execution.model_copy(update={"replay": SpecialistReplayDisposition.REPLAYED})
    )

    assert first.replay == ResultReplayDisposition.FRESH
    assert replay.replay == ResultReplayDisposition.REPLAYED
    assert replay.result_id == first.result_id
    assert replay.canonical_sha256 == first.canonical_sha256
    durable_invocation = invocation_store.get(execution.invocation_id)
    assert durable_invocation.committed_usage == execution.committed_usage
    assert len(result_store.load()) == 1
    events = traces.for_request(execution.request_id)
    assert [event.kind for event in events] == [
        TraceEventKind.RESULT_COMMITTED,
        TraceEventKind.RESULT_REPLAYED,
    ]
    assert all("پاسخ پایدار" not in str(event.metadata) for event in events)
    assert events[0].metadata["canonical_sha256"] == first.canonical_sha256


def test_sqlite_result_replay_survives_restart_without_rewriting_policy(
    tmp_path: Path,
) -> None:
    invocation_path = tmp_path / "invocations.sqlite3"
    result_path = tmp_path / "results.sqlite3"
    execution = _execution_result()

    first_invocations = SQLiteInvocationStore(invocation_path)
    _complete_invocation(first_invocations, execution)
    first_results = SQLiteResultStore(result_path)
    first_terminalizer = _terminalizer(
        invocation_store=first_invocations,
        result_store=first_results,
    )
    first = first_terminalizer.terminalize(
        execution,
        privacy=PrivacyClassification.PRIVATE,
        retention=RetentionDisposition.LONG_LIVED,
    )
    first_results.close()
    first_invocations.close()

    replay_invocations = SQLiteInvocationStore(invocation_path)
    replay_results = SQLiteResultStore(result_path)
    replay_terminalizer = _terminalizer(
        invocation_store=replay_invocations,
        result_store=replay_results,
    )
    durable_execution = SpecialistExecutionResult.model_validate(
        replay_invocations.get(execution.invocation_id).result_payload
    )
    replay = replay_terminalizer.terminalize(durable_execution)

    assert replay.replay == ResultReplayDisposition.REPLAYED
    assert replay.result_id == first.result_id
    assert replay.canonical_sha256 == first.canonical_sha256
    assert replay.privacy == PrivacyClassification.PRIVATE
    assert replay.retention == RetentionDisposition.LONG_LIVED
    replay_results.close()
    replay_invocations.close()


def test_result_identity_conflicts_on_changed_payload() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    first_execution = _execution_result(
        request_id=request_id,
        invocation_id=invocation_id,
        summary="نسخه اول",
    )
    changed_execution = _execution_result(
        request_id=request_id,
        invocation_id=invocation_id,
        summary="نسخه متفاوت",
    )
    registry = default_result_schema_registry()
    first = build_authoritative_plan_result(
        execution_result=first_execution,
        registry=registry,
    )
    changed = build_authoritative_plan_result(
        execution_result=changed_execution,
        registry=registry,
    )
    store = InMemoryResultStore()

    store.claim(first)
    with pytest.raises(ResultConflictError, match="different authoritative content"):
        store.claim(changed)


def test_replay_rejects_changed_artifact_metadata() -> None:
    invocation_store = InMemoryInvocationStore()
    execution = _execution_result()
    _complete_invocation(invocation_store, execution)
    terminalizer = _terminalizer(
        invocation_store=invocation_store,
        result_store=InMemoryResultStore(),
    )
    first_artifact = build_test_artifact_reference(
        artifact_id=uuid4(),
        content=b"first",
        media_type="application/octet-stream",
        request_id=execution.request_id,
        invocation_id=execution.invocation_id,
        producer_agent_id=execution.agent_id,
        producer_agent_version=execution.agent_version,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
        created_at_ms=2_500,
    )
    changed_artifact = build_test_artifact_reference(
        artifact_id=first_artifact.artifact_id,
        content=b"changed",
        media_type="application/octet-stream",
        request_id=execution.request_id,
        invocation_id=execution.invocation_id,
        producer_agent_id=execution.agent_id,
        producer_agent_version=execution.agent_version,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
        created_at_ms=2_500,
    )

    terminalizer.terminalize(execution, artifacts=(first_artifact,))
    with pytest.raises(ResultReplayConflictError, match="different immutable artifact"):
        terminalizer.terminalize(execution, artifacts=(changed_artifact,))


def test_terminalizer_rejects_result_not_matching_durable_invocation() -> None:
    invocation_store = InMemoryInvocationStore()
    result_store = InMemoryResultStore()
    execution = _execution_result(summary="محتوای ثبت‌شده")
    _complete_invocation(invocation_store, execution)
    assert execution.payload is not None
    changed_payload = execution.payload.model_copy(
        update={"summary": "محتوای جعلی"}
    )
    changed = execution.model_copy(update={"payload": changed_payload})
    terminalizer = _terminalizer(
        invocation_store=invocation_store,
        result_store=result_store,
    )

    with pytest.raises(ResultInvocationMismatchError, match="does not match"):
        terminalizer.terminalize(changed)
    assert result_store.load() == []


def test_sqlite_payload_hash_corruption_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "results.sqlite3"
    execution = _execution_result()
    record = build_authoritative_plan_result(
        execution_result=execution,
        registry=default_result_schema_registry(),
    )
    store = SQLiteResultStore(path)
    store.claim(record)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE result_records SET payload_sha256 = ? WHERE result_id = ?",
        ("0" * 64, str(record.result_id)),
    )
    connection.commit()
    connection.close()

    reopened = SQLiteResultStore(path)
    with pytest.raises(ResultStoreCorruptionError, match="hash mismatch"):
        reopened.load()
    reopened.close()


def test_sqlite_unsupported_schema_and_concurrent_owner_fail_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "results.sqlite3"
    owner = SQLiteResultStore(path)
    with pytest.raises(ResultStoreInUseError, match="owns the result store"):
        SQLiteResultStore(path)
    owner.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE result_store_metadata SET value = '999' WHERE key = 'schema_version'"
    )
    connection.commit()
    connection.close()
    with pytest.raises(ResultStoreSchemaError, match="unsupported result store schema"):
        SQLiteResultStore(path)


def test_terminalization_failure_does_not_echo_private_payload() -> None:
    invocation_store = InMemoryInvocationStore()
    traces = InMemoryTraceSink()
    execution = _execution_result(summary="private-marker-123")
    terminalizer = _terminalizer(
        invocation_store=invocation_store,
        result_store=InMemoryResultStore(),
        traces=traces,
    )

    with pytest.raises(ResultAuthorityUnavailableError) as caught:
        terminalizer.terminalize(execution)
    assert "private-marker-123" not in str(caught.value)
    events = traces.for_request(execution.request_id)
    assert len(events) == 1
    assert events[0].kind == TraceEventKind.RESULT_FAILED
    assert "private-marker-123" not in str(events[0].model_dump(mode="json"))
