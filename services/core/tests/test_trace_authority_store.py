from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.trace_authority import (
    CorrelatedTraceEvent,
    TraceEventCandidate,
    TracePhase,
    TraceSafeMetadata,
    TraceUncertaintyDisposition,
    event_id_for_candidate,
    materialize_trace_event,
    trace_id_for_request,
)
from simorgh_core.agents.trace_store import (
    InMemoryTraceStore,
    SQLiteTraceStore,
    TraceAppendKind,
    TraceConflictError,
    TraceStoreCorruptionError,
    TraceStoreInUseError,
    TraceStoreSchemaError,
)
from simorgh_core.agents.tracing import CacheDisposition, TraceEventKind


def _tool_candidate(
    *,
    request_id: UUID | None = None,
    invocation_id: UUID | None = None,
    occurred_at_ms: int = 2_000,
    outcome: str = "completed",
) -> TraceEventCandidate:
    return TraceEventCandidate(
        request_id=request_id or uuid4(),
        occurred_at_ms=occurred_at_ms,
        kind=TraceEventKind.TOOL_COMPLETED,
        phase=TracePhase.TOOL,
        invocation_id=invocation_id or uuid4(),
        tool_id="github.fetch-file",
        connector_id="github",
        cache=CacheDisposition.MISS,
        usage_delta=UsageVector(tool_calls=1),
        outcome=outcome,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
        tainted=True,
        metadata=TraceSafeMetadata(
            effect="read_only",
            projection_sha256="a" * 64,
            item_count=1,
            byte_count=128,
        ),
    )


def _result_candidate(
    *,
    request_id: UUID,
    invocation_id: UUID,
    result_id: UUID,
) -> TraceEventCandidate:
    return TraceEventCandidate(
        request_id=request_id,
        occurred_at_ms=3_000,
        kind=TraceEventKind.RESULT_COMMITTED,
        phase=TracePhase.RESULT,
        invocation_id=invocation_id,
        result_id=result_id,
        agent_id="github.read",
        agent_version="1.0.0",
        outcome="completed",
        metadata=TraceSafeMetadata(
            schema_id="simorgh.repository-report.v1",
            schema_version="1.0",
            result_sha256="b" * 64,
            evidence_count=1,
        ),
    )


def test_trace_event_identity_and_hash_are_deterministic() -> None:
    candidate = _tool_candidate()

    first = materialize_trace_event(candidate, causal_sequence=1)
    second = materialize_trace_event(
        TraceEventCandidate.model_validate(candidate.model_dump(mode="json")),
        causal_sequence=1,
    )

    assert first == second
    assert first.trace_id == trace_id_for_request(candidate.request_id)
    assert first.event_id == event_id_for_candidate(candidate)
    assert len(first.canonical_sha256) == 64


def test_trace_event_rejects_wrong_phase_and_missing_correlation() -> None:
    base = _tool_candidate().model_dump(mode="json")

    with pytest.raises(ValidationError, match="authority phase"):
        TraceEventCandidate.model_validate({**base, "phase": "model"})

    with pytest.raises(ValidationError, match="invocation identity"):
        TraceEventCandidate.model_validate({**base, "invocation_id": None})

    with pytest.raises(ValidationError, match="tool identity"):
        TraceEventCandidate.model_validate({**base, "tool_id": None})


def test_trace_metadata_is_explicit_and_content_free() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        TraceSafeMetadata.model_validate({"prompt": "private"})

    with pytest.raises(ValidationError, match="one bounded line"):
        TraceEventCandidate.model_validate(
            {
                **_tool_candidate().model_dump(mode="json"),
                "model_id": "line-one\nline-two",
            }
        )


def test_unknown_side_effect_requires_mutation_effect() -> None:
    payload = _tool_candidate().model_dump(mode="json")

    with pytest.raises(ValidationError, match="mutation effect"):
        TraceEventCandidate.model_validate(
            {
                **payload,
                "uncertainty": TraceUncertaintyDisposition.UNKNOWN_SIDE_EFFECT.value,
            }
        )


def test_in_memory_store_appends_replays_and_orders_events() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    store = InMemoryTraceStore()
    tool = _tool_candidate(
        request_id=request_id,
        invocation_id=invocation_id,
    )
    result = _result_candidate(
        request_id=request_id,
        invocation_id=invocation_id,
        result_id=uuid4(),
    )

    first = store.append(tool)
    replay = store.append(tool)
    second = store.append(result)

    assert first.kind == TraceAppendKind.NEW
    assert replay.kind == TraceAppendKind.REPLAY
    assert replay.record == first.record
    assert second.record.causal_sequence == 2
    assert [event.event_id for event in store.for_request(request_id)] == [
        first.record.event_id,
        second.record.event_id,
    ]
    assert store.for_trace(first.record.trace_id) == store.for_request(request_id)


def test_same_event_slot_with_changed_authority_conflicts() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    store = InMemoryTraceStore()
    original = _tool_candidate(
        request_id=request_id,
        invocation_id=invocation_id,
        outcome="completed",
    )
    changed = _tool_candidate(
        request_id=request_id,
        invocation_id=invocation_id,
        outcome="failed",
    )

    store.append(original)

    with pytest.raises(TraceConflictError, match="conflicts"):
        store.append(changed)


def test_sqlite_trace_round_trip_and_restart_replay(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    candidate = _tool_candidate()
    first_store = SQLiteTraceStore(path)

    created = first_store.append(candidate)
    first_store.close()

    reopened = SQLiteTraceStore(path)
    replayed = reopened.append(candidate)
    loaded = reopened.for_request(candidate.request_id)

    assert created.kind == TraceAppendKind.NEW
    assert replayed.kind == TraceAppendKind.REPLAY
    assert replayed.record == created.record
    assert loaded == (created.record,)
    assert reopened.get_event(created.record.event_id) == created.record
    reopened.close()


def test_sqlite_trace_store_detects_index_corruption(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    store = SQLiteTraceStore(path)
    store.append(_tool_candidate())
    store.close()

    connection = sqlite3.connect(path)
    connection.execute("UPDATE trace_events SET kind = 'model_completed'")
    connection.commit()
    connection.close()

    with pytest.raises(TraceStoreCorruptionError, match="index metadata"):
        SQLiteTraceStore(path)


def test_sqlite_trace_store_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    store = SQLiteTraceStore(path)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE trace_store_metadata SET value = '999' WHERE key = 'schema_version'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(TraceStoreSchemaError, match="unsupported"):
        SQLiteTraceStore(path)


def test_sqlite_trace_store_has_exclusive_process_ownership(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    first = SQLiteTraceStore(path)

    with pytest.raises(TraceStoreInUseError, match="another Simorgh Core process"):
        SQLiteTraceStore(path)

    first.close()
    reopened = SQLiteTraceStore(path)
    reopened.close()


def test_correlated_event_rejects_forged_hash() -> None:
    record = materialize_trace_event(_tool_candidate(), causal_sequence=1)
    payload = record.model_dump(mode="json")

    with pytest.raises(ValidationError, match="canonical hash"):
        CorrelatedTraceEvent.model_validate(
            {**payload, "canonical_sha256": "f" * 64}
        )
