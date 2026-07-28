from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.trace_authority import (
    TraceEventDraft,
    TraceOutcomeCode,
    TraceReasonCode,
    trace_event_id_for,
    trace_id_for,
)
from simorgh_core.agents.trace_store import (
    InMemoryTraceStore,
    SQLiteTraceStore,
    TraceAppendKind,
    TraceConflictError,
    TraceStoreCorruptionError,
    TraceStoreInUseError,
)
from simorgh_core.agents.tracing import TraceEventKind


def _draft(
    request_id: UUID,
    *,
    logical_identity: str,
    occurred_at_ms: int,
    outcome: TraceOutcomeCode = TraceOutcomeCode.STARTED,
) -> TraceEventDraft:
    return TraceEventDraft(
        event_id=trace_event_id_for(
            request_id=request_id,
            kind=TraceEventKind.TOOL_STARTED,
            logical_identity=logical_identity,
        ),
        trace_id=trace_id_for(request_id),
        request_id=request_id,
        kind=TraceEventKind.TOOL_STARTED,
        occurred_at_ms=occurred_at_ms,
        tool_id="github.fetch-file",
        connector_id="github",
        outcome=outcome,
        reason_code=TraceReasonCode.STARTED_APPROVED_WORK,
    )


def test_in_memory_append_is_sequenced_idempotent_and_conflict_safe() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    draft = _draft(request_id, logical_identity="tool:1", occurred_at_ms=1_000)

    first = store.append(draft)
    replay = store.append(draft)

    assert first.kind == TraceAppendKind.NEW
    assert replay.kind == TraceAppendKind.REPLAY
    assert first.event == replay.event
    assert first.event.sequence == 1

    changed = draft.model_copy(update={"occurred_at_ms": 2_000})
    with pytest.raises(TraceConflictError, match="different authoritative metadata"):
        store.append(changed)


def test_in_memory_concurrent_append_allocates_contiguous_sequences() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    drafts = tuple(
        _draft(
            request_id,
            logical_identity=f"tool:{index}",
            occurred_at_ms=1_000 - index,
        )
        for index in range(32)
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(store.append, drafts))

    assert all(result.kind == TraceAppendKind.NEW for result in results)
    events = store.for_request(request_id)
    assert tuple(event.sequence for event in events) == tuple(range(1, 33))
    assert len({event.event_id for event in events}) == 32


def test_sqlite_trace_reopens_with_exact_projection(tmp_path: Path) -> None:
    request_id = uuid4()
    path = tmp_path / "traces.sqlite3"
    store = SQLiteTraceStore(path)
    first = store.append(
        _draft(request_id, logical_identity="tool:1", occurred_at_ms=2_000)
    )
    second = store.append(
        _draft(
            request_id,
            logical_identity="tool:2",
            occurred_at_ms=1_000,
            outcome=TraceOutcomeCode.COMPLETED,
        )
    )
    original_projection = store.project(request_id)
    store.close()

    reopened = SQLiteTraceStore(path)
    replay = reopened.append(
        _draft(request_id, logical_identity="tool:1", occurred_at_ms=2_000)
    )
    reopened_projection = reopened.project(request_id)

    assert first.event.sequence == 1
    assert second.event.sequence == 2
    assert replay.kind == TraceAppendKind.REPLAY
    assert original_projection == reopened_projection
    reopened.close()


def test_sqlite_trace_process_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    first = SQLiteTraceStore(path)

    with pytest.raises(TraceStoreInUseError, match="another Simorgh Core process"):
        SQLiteTraceStore(path)

    first.close()
    reopened = SQLiteTraceStore(path)
    reopened.close()


def test_sqlite_trace_payload_corruption_fails_closed(tmp_path: Path) -> None:
    request_id = uuid4()
    path = tmp_path / "traces.sqlite3"
    store = SQLiteTraceStore(path)
    store.append(_draft(request_id, logical_identity="tool:1", occurred_at_ms=1_000))
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE trace_events SET payload_json = ?",
        ('{"corrupted":true}',),
    )
    connection.commit()
    connection.close()

    with pytest.raises(TraceStoreCorruptionError, match="payload hash"):
        SQLiteTraceStore(path)
