from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.contracts import RoutingState
from simorgh_core.agents.sqlite_trace_store import SQLiteTraceStore
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceContextDetails,
    TraceDisposition,
    TraceGapCode,
    TraceGapDetails,
    TraceRoutingDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceSupersessionDetails,
    TraceTaskDetails,
    TraceTerminalDetails,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore
from simorgh_core.agents.trace_supersession import (
    new_trace_resolved_candidate,
    new_trace_superseded_candidate,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64


def _terminal_trace(store, request_id):
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
    terminal = store.append(
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
                reason_code="needs-clarification",
            ),
            occurred_at_ms=1_200,
        ),
        ingested_at_ms=2_200,
    ).record
    gap_source_id = uuid4()
    gap = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_GAP,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TRACE_RECONCILIATION,
            source_authority_id=gap_source_id,
            source_authority_sha256=_SHA_C,
            parent_event_id=terminal.event_id,
            causation_event_id=terminal.event_id,
            details=TraceGapDetails(
                gap_code=TraceGapCode.SOURCE_HASH_MISMATCH,
                missing_stage=TraceStage.TERMINAL,
                missing_source_kind=TraceSourceAuthorityKind.TASK_RECORD,
                missing_source_id=request_id,
            ),
            occurred_at_ms=1_300,
        ),
        ingested_at_ms=2_300,
    ).record
    return routing, terminal, gap


def test_supersession_reopens_terminal_without_erasing_historical_gap() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    routing, terminal, gap = _terminal_trace(store, request_id)

    superseded = store.append(
        new_trace_superseded_candidate(
            request_id=request_id,
            previous_status_event=terminal,
            source_snapshot_sha256=_SHA_D,
            resolved_gap_event_ids=(gap.event_id,),
            occurred_at_ms=1_400,
            parent_event_id=gap.event_id,
        ),
        ingested_at_ms=2_400,
    ).record
    view = store.view(request_id)

    assert view.envelope.disposition == TraceDisposition.IN_PROGRESS
    assert view.envelope.terminal is False
    assert view.envelope.gap_count == 1
    assert view.envelope.unresolved_gap_count == 0
    assert view.envelope.unresolved_gap_event_ids == ()
    assert gap.event_id in {item.gap_event_id for item in view.envelope.gaps}
    assert superseded.details.previous_status_event_id == terminal.event_id
    assert superseded.details.resolved_gap_event_ids == (gap.event_id,)

    context_id = uuid4()
    context = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.CONTEXT_COMPILED,
            stage=TraceStage.CONTEXT,
            source_authority_kind=TraceSourceAuthorityKind.CONTEXT_BUNDLE,
            source_authority_id=context_id,
            source_authority_sha256=_SHA_D,
            parent_event_id=routing.event_id,
            causation_event_id=superseded.event_id,
            invocation_id=uuid4(),
            context_bundle_id=context_id,
            details=TraceContextDetails(
                context_bundle_id=context_id,
                context_sha256=_SHA_D,
                source_manifest_sha256=_SHA_C,
                section_count=1,
                omission_count=0,
            ),
            occurred_at_ms=1_500,
        ),
        ingested_at_ms=2_500,
    ).record
    resolved = store.append(
        new_trace_resolved_candidate(
            request_id=request_id,
            superseded_event=superseded,
            source_snapshot_sha256=_SHA_D,
            disposition=TraceDisposition.FAILED,
            reason_code="replacement-failed",
            occurred_at_ms=1_600,
            parent_event_id=context.event_id,
        ),
        ingested_at_ms=2_600,
    ).record
    final_view = store.view(request_id)

    assert final_view.envelope.disposition == TraceDisposition.FAILED
    assert final_view.envelope.terminal is True
    assert final_view.envelope.gap_count == 1
    assert final_view.envelope.unresolved_gap_count == 0
    assert resolved.details.previous_status_event_id == superseded.event_id


def test_unresolved_gap_keeps_current_envelope_incomplete() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    routing, terminal, source_gap = _terminal_trace(store, request_id)
    superseded = store.append(
        new_trace_superseded_candidate(
            request_id=request_id,
            previous_status_event=terminal,
            source_snapshot_sha256=_SHA_D,
            resolved_gap_event_ids=(source_gap.event_id,),
            occurred_at_ms=1_400,
            parent_event_id=source_gap.event_id,
        ),
        ingested_at_ms=2_400,
    ).record
    other_gap = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_GAP,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TRACE_RECONCILIATION,
            source_authority_id=uuid4(),
            source_authority_sha256=_SHA_B,
            parent_event_id=superseded.event_id,
            causation_event_id=superseded.event_id,
            details=TraceGapDetails(
                gap_code=TraceGapCode.MISSING_RESULT,
                missing_stage=TraceStage.RESULT,
                missing_source_kind=TraceSourceAuthorityKind.RESULT_RECORD,
                missing_source_id=uuid4(),
            ),
            occurred_at_ms=1_500,
        ),
        ingested_at_ms=2_500,
    ).record
    resolved = store.append(
        new_trace_resolved_candidate(
            request_id=request_id,
            superseded_event=superseded,
            source_snapshot_sha256=_SHA_D,
            disposition=TraceDisposition.FAILED,
            reason_code="replacement-failed",
            occurred_at_ms=1_600,
            parent_event_id=routing.event_id,
        ),
        ingested_at_ms=2_600,
    ).record
    view = store.view(request_id)

    assert resolved.event_kind == DurableTraceEventKind.TRACE_RESOLVED
    assert view.envelope.disposition == TraceDisposition.INCOMPLETE_GAP
    assert view.envelope.terminal is True
    assert view.envelope.gap_count == 2
    assert view.envelope.unresolved_gap_count == 1
    assert view.envelope.unresolved_gap_event_ids == (other_gap.event_id,)


def test_supersession_contract_rejects_invalid_terminal_shape() -> None:
    with pytest.raises(ValidationError):
        TraceSupersessionDetails(
            previous_status_event_id=uuid4(),
            source_snapshot_sha256=_SHA_A,
            disposition=TraceDisposition.COMPLETED,
            terminal=False,
            reason_code="invalid",
        )
    with pytest.raises(ValidationError):
        TraceSupersessionDetails(
            previous_status_event_id=uuid4(),
            source_snapshot_sha256=_SHA_A,
            disposition=TraceDisposition.IN_PROGRESS,
            terminal=True,
            reason_code="invalid",
        )


def test_sqlite_supersession_reopens_identically_after_restart(
    tmp_path: Path,
) -> None:
    request_id = uuid4()
    path = tmp_path / "traces.sqlite3"
    store = SQLiteTraceStore(path)
    _, terminal, gap = _terminal_trace(store, request_id)
    store.append(
        new_trace_superseded_candidate(
            request_id=request_id,
            previous_status_event=terminal,
            source_snapshot_sha256=_SHA_D,
            resolved_gap_event_ids=(gap.event_id,),
            occurred_at_ms=1_400,
            parent_event_id=gap.event_id,
        ),
        ingested_at_ms=2_400,
    )
    before = store.view(request_id)
    store.close()

    reopened = SQLiteTraceStore(path)
    after = reopened.view(request_id)

    assert before == after
    assert after.envelope.disposition == TraceDisposition.IN_PROGRESS
    assert after.envelope.terminal is False
    assert after.envelope.gap_count == 1
    assert after.envelope.unresolved_gap_count == 0
    reopened.close()
