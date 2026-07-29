from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from simorgh_core.agents.cancellation_contracts import (
    CancellationDisposition,
    CancellationReplayDisposition,
    CancellationRequesterAuthority,
    TaskCancellationRequest,
    TaskCancellationResult,
)
from simorgh_core.agents.sqlite_trace_store import SQLiteTraceStore
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceCancellationDetails,
    TraceDisposition,
)
from simorgh_core.agents.trace_reconciliation import (
    reconcile_retained_trace_authority,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore

_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _cancellation_request(
    request_id: UUID,
    *,
    private_reason: str,
) -> TaskCancellationRequest:
    return TaskCancellationRequest.model_construct(
        request_id=request_id,
        cancellation_id=uuid4(),
        requested_at_ms=1_100,
        reason_code="operator_requested",
        operator_reason=private_reason,
        requester_authority=CancellationRequesterAuthority.OPERATOR,
        observed_task_phase="routed",
        observed_task_version=1_000,
    )


def _task_entry(
    *,
    settled: bool,
    uncertain_count: int = 0,
    replay: CancellationReplayDisposition = CancellationReplayDisposition.FRESH,
) -> tuple[AgentTaskStoreEntryV1, str]:
    request_id = uuid4()
    private_reason = "private operator reason must never enter trace"
    request = _cancellation_request(
        request_id,
        private_reason=private_reason,
    )
    result = None
    if settled:
        result = TaskCancellationResult.model_construct(
            request=request,
            accepted_at_ms=1_150,
            completed_at_ms=1_300,
            ownership_snapshot_sha256=_SHA_B,
            outcomes=(),
            terminal_count=0,
            pending_cancelled_count=0,
            reserved_cancelled_count=0,
            reserved_uncertain_count=uncertain_count,
            signalled_count=0,
            disposition=(
                CancellationDisposition.PARTIALLY_UNCERTAIN
                if uncertain_count
                else CancellationDisposition.APPLIED
            ),
            audit_event_id=uuid4(),
            replay=replay,
        )
    entry = AgentTaskStoreEntryV1.model_construct(
        request_id=request_id,
        task_fingerprint=_SHA_A,
        record=AgentTaskRecord.model_construct(
            request_id=request_id,
            phase=AgentTaskPhase.CANCELLED,
            created_at_ms=1_000,
            updated_at_ms=1_300 if settled else 1_150,
            routing_decision=None,
            cancellation_request=request,
            cancellation_result=result,
            cancel_reason=private_reason,
        ),
    )
    return entry, private_reason


def test_accepted_cancellation_without_settlement_keeps_trace_open() -> None:
    entry, private_reason = _task_entry(settled=False)
    store = InMemoryTraceStore()

    report = reconcile_retained_trace_authority(
        store=store,
        task_entries=(entry,),
        invocation_records=(),
        context_bundles=(),
        result_records=(),
        base_ingested_at_ms=2_000,
    )
    view = store.view(entry.request_id)

    assert report.projected_event_count == 1
    assert report.gap_event_count == 0
    assert view.envelope.disposition == TraceDisposition.IN_PROGRESS
    assert view.envelope.terminal is False
    assert [event.event_kind for event in view.events] == [
        DurableTraceEventKind.TASK_CLAIMED,
    ]
    assert private_reason not in str(view.model_dump(mode="json"))


def test_settled_cancellation_precedes_cancelled_request_terminal() -> None:
    entry, private_reason = _task_entry(settled=True)
    store = InMemoryTraceStore()

    report = reconcile_retained_trace_authority(
        store=store,
        task_entries=(entry,),
        invocation_records=(),
        context_bundles=(),
        result_records=(),
        base_ingested_at_ms=2_000,
    )
    view = store.view(entry.request_id)

    assert report.projected_event_count == 3
    assert view.envelope.disposition == TraceDisposition.CANCELLED
    assert [event.event_kind for event in view.events] == [
        DurableTraceEventKind.TASK_CLAIMED,
        DurableTraceEventKind.CANCELLATION_SETTLED,
        DurableTraceEventKind.TRACE_TERMINAL,
    ]
    cancellation = view.events[1]
    terminal = view.events[2]
    assert terminal.parent_event_id == cancellation.event_id
    assert isinstance(cancellation.details, TraceCancellationDetails)
    assert cancellation.details.uncertain_invocation_count == 0
    assert private_reason not in str(view.model_dump(mode="json"))


def test_uncertain_cancellation_terminal_remains_unknown_side_effect() -> None:
    entry, _ = _task_entry(settled=True, uncertain_count=2)
    store = InMemoryTraceStore()

    reconcile_retained_trace_authority(
        store=store,
        task_entries=(entry,),
        invocation_records=(),
        context_bundles=(),
        result_records=(),
        base_ingested_at_ms=2_000,
    )
    view = store.view(entry.request_id)

    assert view.envelope.disposition == TraceDisposition.UNKNOWN_SIDE_EFFECT
    assert view.events[1].details.uncertain_invocation_count == 2


def test_cancellation_restart_reconciliation_is_exactly_idempotent(
    tmp_path: Path,
) -> None:
    entry, private_reason = _task_entry(settled=True)
    inputs = dict(
        task_entries=(entry,),
        invocation_records=(),
        context_bundles=(),
        result_records=(),
    )
    path = tmp_path / "traces.sqlite3"
    store = SQLiteTraceStore(path)

    first = reconcile_retained_trace_authority(
        store=store,
        **inputs,
        base_ingested_at_ms=2_000,
    )
    first_view = store.view(entry.request_id)
    store.close()

    reopened = SQLiteTraceStore(path)
    second = reconcile_retained_trace_authority(
        store=reopened,
        **inputs,
        base_ingested_at_ms=90_000,
    )
    second_view = reopened.view(entry.request_id)

    assert first.projected_event_count == 3
    assert second.projected_event_count == 0
    assert second.replayed_event_count == 3
    assert first_view == second_view
    assert private_reason not in str(second_view.model_dump(mode="json"))
    reopened.close()
