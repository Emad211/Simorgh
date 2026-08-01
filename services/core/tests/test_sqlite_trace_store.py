from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import simorgh_core.agents.trace_store as trace_store_module
from simorgh_core.agents.contracts import RoutingMethod, RoutingState
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.sqlite_trace_store import (
    SQLiteTraceStore,
    TraceStoreCorruptionError,
    TraceStoreInUseError,
    TraceStoreSchemaError,
)
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.trace_contracts import (
    MAX_TRACE_EVENTS,
    MAX_TRACE_GAPS,
    DurableTraceEventKind,
    TraceEventCandidate,
    TraceGapCode,
    TraceGapDetails,
    TraceRoutingDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceTaskDetails,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_store import (
    TraceClaimKind,
    TraceConflictError,
    TraceLimitError,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _task_event(
    request_id: UUID,
    *,
    occurred_at_ms: int = 1_000,
    source_sha256: str = _SHA_A,
) -> TraceEventCandidate:
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=DurableTraceEventKind.TASK_CLAIMED,
        stage=TraceStage.TASK,
        source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
        source_authority_id=request_id,
        source_authority_sha256=source_sha256,
        details=TraceTaskDetails(
            task_fingerprint=source_sha256,
            phase=AgentTaskPhase.ROUTING,
        ),
        occurred_at_ms=occurred_at_ms,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
    )


def _routing_event(
    request_id: UUID,
    *,
    parent_event_id: UUID,
    decision_id: UUID,
) -> TraceEventCandidate:
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=DurableTraceEventKind.ROUTING_DECIDED,
        stage=TraceStage.ROUTING,
        source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
        source_authority_id=decision_id,
        source_authority_sha256=_SHA_B,
        parent_event_id=parent_event_id,
        causation_event_id=parent_event_id,
        details=TraceRoutingDetails(
            routing_fingerprint=_SHA_B,
            state=RoutingState.ROUTED,
            method=RoutingMethod.EXPLICIT_TASK_KIND,
            selected_agent_id="development.planner",
            selected_agent_version="1.0.0",
        ),
        occurred_at_ms=1_100,
    )


def _gap_event(request_id: UUID, *, source_id: UUID) -> TraceEventCandidate:
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=DurableTraceEventKind.TRACE_GAP,
        stage=TraceStage.TERMINAL,
        source_authority_kind=TraceSourceAuthorityKind.TRACE_RECONCILIATION,
        source_authority_id=source_id,
        source_authority_sha256=_SHA_B,
        details=TraceGapDetails(
            gap_code=TraceGapCode.MISSING_CONTEXT,
            missing_stage=TraceStage.CONTEXT,
            missing_source_kind=TraceSourceAuthorityKind.CONTEXT_BUNDLE,
        ),
        occurred_at_ms=1_200,
    )


def test_sqlite_round_trip_restart_and_exact_duplicate_replay(tmp_path: Path) -> None:
    path = tmp_path / "trace.sqlite3"
    request_id = uuid4()
    decision_id = uuid4()
    first_store = SQLiteTraceStore(path)
    task = first_store.append(
        _task_event(request_id),
        ingested_at_ms=2_000,
    ).record
    routing = first_store.append(
        _routing_event(
            request_id,
            parent_event_id=task.event_id,
            decision_id=decision_id,
        ),
        ingested_at_ms=2_010,
    ).record
    first_view = first_store.view(request_id)
    first_store.close()

    reopened = SQLiteTraceStore(path)
    replay = reopened.append(
        _task_event(request_id, occurred_at_ms=9_000),
        ingested_at_ms=9_100,
    )
    reopened_view = reopened.view(request_id)

    assert replay.kind == TraceClaimKind.REPLAY
    assert replay.record == task
    assert reopened.get_event(routing.event_id) == routing
    assert reopened_view == first_view
    assert [record.sequence for record in reopened.load()] == [1, 2]
    reopened.close()


def test_sqlite_changed_event_identity_conflicts_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "trace.sqlite3"
    request_id = uuid4()
    store = SQLiteTraceStore(path)
    store.append(_task_event(request_id), ingested_at_ms=2_000)
    store.close()

    reopened = SQLiteTraceStore(path)
    with pytest.raises(TraceConflictError, match="immutable event identity"):
        reopened.append(
            _task_event(request_id, source_sha256=_SHA_B),
            ingested_at_ms=2_100,
        )
    reopened.close()


def test_sqlite_process_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "trace.sqlite3"
    first = SQLiteTraceStore(path)

    with pytest.raises(TraceStoreInUseError, match="owns the trace store"):
        SQLiteTraceStore(path)

    first.close()
    reopened = SQLiteTraceStore(path)
    reopened.close()


def test_sqlite_payload_corruption_fails_closed_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "trace.sqlite3"
    request_id = uuid4()
    store = SQLiteTraceStore(path)
    store.append(_task_event(request_id), ingested_at_ms=2_000)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE trace_events SET payload_json = '{}' WHERE request_id = ?",
        (str(request_id),),
    )
    connection.commit()
    connection.close()

    with pytest.raises(TraceStoreCorruptionError, match="payload hash mismatch"):
        SQLiteTraceStore(path)


def test_sqlite_unsupported_schema_version_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "trace.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE trace_store_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    connection.execute(
        "INSERT INTO trace_store_metadata(key, value) VALUES('schema_version', '999')"
    )
    connection.commit()
    connection.close()

    with pytest.raises(TraceStoreSchemaError, match="unsupported trace store schema"):
        SQLiteTraceStore(path)


def test_sqlite_event_limit_preserves_replay_and_rolls_back_fresh_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "trace.sqlite3"
    request_id = uuid4()
    store = SQLiteTraceStore(path)
    task = store.append(_task_event(request_id), ingested_at_ms=2_000).record
    store.append(
        _routing_event(
            request_id,
            parent_event_id=task.event_id,
            decision_id=uuid4(),
        ),
        ingested_at_ms=2_010,
    )
    monkeypatch.setattr(trace_store_module, "MAX_TRACE_EVENTS", 2)
    baseline = store.view(request_id)

    with pytest.raises(TraceLimitError, match="event count exceeds"):
        store.append(
            _gap_event(request_id, source_id=uuid4()),
            ingested_at_ms=9_000,
        )

    replay = store.append(
        _task_event(request_id, occurred_at_ms=9_100),
        ingested_at_ms=9_200,
    )
    assert replay.kind == TraceClaimKind.REPLAY
    assert replay.record == task
    assert store.view(request_id) == baseline
    store.close()
    monkeypatch.setattr(trace_store_module, "MAX_TRACE_EVENTS", MAX_TRACE_EVENTS)

    reopened = SQLiteTraceStore(path)
    assert reopened.view(request_id) == baseline
    assert len(reopened.load()) == 2
    reopened.close()


def test_sqlite_gap_limit_rolls_back_and_reopens_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "trace.sqlite3"
    request_id = uuid4()
    store = SQLiteTraceStore(path)
    store.append(_task_event(request_id), ingested_at_ms=2_000)
    monkeypatch.setattr(trace_store_module, "MAX_TRACE_GAPS", 2)

    for index in range(2):
        store.append(
            _gap_event(request_id, source_id=uuid4()),
            ingested_at_ms=3_000 + index,
        )

    baseline = store.view(request_id)
    assert baseline.envelope.gap_count == 2

    with pytest.raises(TraceLimitError, match="gap count exceeds"):
        store.append(
            _gap_event(request_id, source_id=uuid4()),
            ingested_at_ms=9_000,
        )

    assert store.view(request_id) == baseline
    store.close()
    monkeypatch.setattr(trace_store_module, "MAX_TRACE_GAPS", MAX_TRACE_GAPS)

    reopened = SQLiteTraceStore(path)
    assert reopened.view(request_id) == baseline
    assert len(reopened.load()) == 3
    reopened.close()


def test_sqlite_concurrent_appends_assign_unique_contiguous_sequences(
    tmp_path: Path,
) -> None:
    path = tmp_path / "trace.sqlite3"
    request_id = uuid4()
    store = SQLiteTraceStore(path)
    store.append(_task_event(request_id), ingested_at_ms=2_000)
    source_ids = tuple(uuid4() for _ in range(24))

    def append_gap(item: tuple[int, UUID]) -> int:
        index, source_id = item
        claim = store.append(
            _gap_event(request_id, source_id=source_id),
            ingested_at_ms=2_100 + index,
        )
        return claim.record.sequence

    with ThreadPoolExecutor(max_workers=8) as executor:
        sequences = tuple(executor.map(append_gap, enumerate(source_ids)))

    view = store.view(request_id)
    assert sorted(sequences) == list(range(2, 26))
    assert [event.sequence for event in view.events] == list(range(1, 26))
    assert view.envelope.gap_count == 24
    store.close()
