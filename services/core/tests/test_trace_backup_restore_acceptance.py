from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from simorgh_core.agents.contracts import RoutingState
from simorgh_core.agents.sqlite_trace_store import (
    SQLiteTraceStore,
    TraceStoreCorruptionError,
)
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceDisposition,
    TraceGapCode,
    TraceGapDetails,
    TraceRoutingDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceTaskDetails,
    TraceTerminalDetails,
    new_trace_event_candidate,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


def _terminal_trace(store: SQLiteTraceStore):
    request_id = uuid4()
    task = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            details=TraceTaskDetails(
                task_fingerprint=_SHA_A,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=1_000,
        ),
        ingested_at_ms=2_000,
    ).record
    decision_id = uuid4()
    routing = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.ROUTING_DECIDED,
            stage=TraceStage.ROUTING,
            source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            source_authority_id=decision_id,
            source_authority_sha256=_SHA_B,
            parent_event_id=task.event_id,
            causation_event_id=task.event_id,
            details=TraceRoutingDetails(
                routing_fingerprint=_SHA_B,
                state=RoutingState.NEEDS_CLARIFICATION,
            ),
            occurred_at_ms=1_100,
        ),
        ingested_at_ms=2_100,
    ).record
    store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_TERMINAL,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            parent_event_id=routing.event_id,
            causation_event_id=routing.event_id,
            details=TraceTerminalDetails(
                disposition=TraceDisposition.NEEDS_CLARIFICATION,
                reason_code="needs_clarification",
            ),
            occurred_at_ms=1_200,
        ),
        ingested_at_ms=2_200,
    )
    return request_id


def _online_backup(source_path: Path, backup_path: Path) -> None:
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def test_online_backup_restore_is_point_in_time_and_fail_closed(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "traces.sqlite3"
    backup_path = tmp_path / "traces.backup.sqlite3"
    restored_path = tmp_path / "traces.restored.sqlite3"
    corrupt_path = tmp_path / "traces.corrupt.sqlite3"
    source_store = SQLiteTraceStore(source_path)
    request_id = _terminal_trace(source_store)
    baseline = source_store.view(request_id)

    assert Path(f"{source_path}-wal").exists()
    _online_backup(source_path, backup_path)

    backup_store = SQLiteTraceStore(backup_path)
    assert backup_store.view(request_id) == baseline
    assert backup_store.load() == list(baseline.events)

    gap_source_id = uuid4()
    source_store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_GAP,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TRACE_RECONCILIATION,
            source_authority_id=gap_source_id,
            source_authority_sha256=_SHA_C,
            parent_event_id=baseline.events[-1].event_id,
            causation_event_id=baseline.events[-1].event_id,
            details=TraceGapDetails(
                gap_code=TraceGapCode.RETENTION_GAP,
                missing_stage=TraceStage.RESULT,
                missing_source_kind=TraceSourceAuthorityKind.RESULT_RECORD,
            ),
            occurred_at_ms=1_300,
        ),
        ingested_at_ms=2_300,
    )
    assert source_store.view(request_id).envelope.disposition == (
        TraceDisposition.INCOMPLETE_GAP
    )
    assert backup_store.view(request_id) == baseline

    backup_store.close()
    source_store.close()
    for suffix in ("-wal", "-shm", ".lock"):
        sidecar = Path(f"{backup_path}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    shutil.copy2(backup_path, restored_path)

    restored = SQLiteTraceStore(restored_path)
    assert restored.view(request_id) == baseline
    assert restored.load() == list(baseline.events)
    restored.close()

    shutil.copy2(restored_path, corrupt_path)
    connection = sqlite3.connect(corrupt_path)
    connection.execute(
        "UPDATE trace_events SET payload_json = '{}' WHERE sequence = 1"
    )
    connection.commit()
    connection.close()

    with pytest.raises(TraceStoreCorruptionError, match="payload hash mismatch"):
        SQLiteTraceStore(corrupt_path)
