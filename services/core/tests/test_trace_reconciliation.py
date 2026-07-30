from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.contracts import (
    InvocationState,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    UsageVector,
)
from simorgh_core.agents.invocations import InvocationEffect, InvocationKind, InvocationRecord
from simorgh_core.agents.result_authority import (
    AuthoritativeSpecialistResult,
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.sqlite_trace_store import SQLiteTraceStore
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceDisposition,
    TraceGapCode,
    TraceGapDetails,
    TraceInvocationDetails,
)
from simorgh_core.agents.trace_reconciliation import (
    reconcile_retained_trace_authority,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64
_SHA_E = "e" * 64
_SHA_F = "f" * 64


def _task_entry(request_id: UUID) -> AgentTaskStoreEntryV1:
    decision = RoutingDecision.model_construct(
        decision_id=uuid4(),
        request_id=request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="development.planner",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        candidate_agent_ids=("development.planner",),
        matched_rule_ids=(),
        classifier_invocation_id=None,
        model_calls=0,
        reason="fixture",
    )
    record = AgentTaskRecord.model_construct(
        request_id=request_id,
        phase=AgentTaskPhase.ROUTED,
        created_at_ms=1_000,
        updated_at_ms=1_100,
        routing_decision=decision,
    )
    return AgentTaskStoreEntryV1.model_construct(
        request_id=request_id,
        task_fingerprint=_SHA_A,
        record=record,
    )


def _context(
    request_id: UUID,
    invocation_id: UUID,
    *,
    compiled_at_ms: int,
) -> SpecialistContextBundle:
    return SpecialistContextBundle.model_construct(
        request_id=request_id,
        specialist_invocation_id=invocation_id,
        context_bundle_id=uuid4(),
        canonical_sha256=_SHA_B,
        source_manifest_sha256=_SHA_C,
        section_count=3,
        omission_count=0,
        compiled_at_ms=compiled_at_ms,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
    )


def _specialist(
    request_id: UUID,
    *,
    invocation_id: UUID,
    state: InvocationState,
    attempt: int = 1,
    parent_invocation_id: UUID | None = None,
    created_at_ms: int = 1_300,
    updated_at_ms: int = 1_400,
) -> InvocationRecord:
    completed = state == InvocationState.COMPLETED
    return InvocationRecord.model_construct(
        schema_version=2,
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="Specialist Execute V1",
        input_fingerprint=_SHA_D,
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.PROPOSAL,
        provider_id=None,
        model_id=None,
        tool_id=None,
        connector_id=None,
        parent_invocation_id=parent_invocation_id,
        cancellation_owner_id=None,
        state=state,
        attempt=attempt,
        created_at_ms=created_at_ms,
        updated_at_ms=updated_at_ms,
        reserved_usage=UsageVector(),
        committed_usage=UsageVector(input_tokens=11, output_tokens=7),
        result_payload=({"ok": True} if completed else None),
        result_payload_sha256=(_SHA_E if completed else None),
        failure_code=(None if completed else "PRIVATE failure 42"),
        failure_detail=None,
    )


def _result(
    request_id: UUID,
    invocation_id: UUID,
    *,
    completed_at_ms: int,
) -> AuthoritativeSpecialistResult:
    return AuthoritativeSpecialistResult.model_construct(
        result_id=uuid4(),
        canonical_sha256=_SHA_F,
        request_id=request_id,
        invocation_id=invocation_id,
        result_schema_id="simorgh.specialist-plan-result",
        result_schema_version="1.0",
        completed_at_ms=completed_at_ms,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
    )


def test_reconciliation_projects_complete_zero_external_vertical_slice() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    task = _task_entry(request_id)
    context = _context(request_id, invocation_id, compiled_at_ms=1_200)
    invocation = _specialist(
        request_id,
        invocation_id=invocation_id,
        state=InvocationState.COMPLETED,
    )
    result = _result(request_id, invocation_id, completed_at_ms=1_500)
    store = InMemoryTraceStore()

    report = reconcile_retained_trace_authority(
        store=store,
        task_entries=(task,),
        invocation_records=(invocation,),
        context_bundles=(context,),
        result_records=(result,),
        base_ingested_at_ms=10_000,
    )
    view = store.view(request_id)

    assert report.projected_event_count == 7
    assert report.replayed_event_count == 0
    assert report.gap_event_count == 0
    assert view.envelope.disposition == TraceDisposition.COMPLETED
    assert [event.event_kind for event in view.events] == [
        DurableTraceEventKind.TASK_CLAIMED,
        DurableTraceEventKind.ROUTING_DECIDED,
        DurableTraceEventKind.CONTEXT_COMPILED,
        DurableTraceEventKind.INVOCATION_STARTED,
        DurableTraceEventKind.INVOCATION_TERMINAL,
        DurableTraceEventKind.RESULT_COMMITTED,
        DurableTraceEventKind.TRACE_TERMINAL,
    ]
    invocation_terminal = view.events[4]
    result_committed = view.events[5]
    assert invocation_terminal.usage == invocation.committed_usage
    assert result_committed.usage == UsageVector()
    assert isinstance(invocation_terminal.details, TraceInvocationDetails)
    assert invocation_terminal.details.operation_id == "specialist-execute-v1"


def test_reconciliation_is_idempotent_and_does_not_duplicate_usage() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    task = _task_entry(request_id)
    context = _context(request_id, invocation_id, compiled_at_ms=1_200)
    invocation = _specialist(
        request_id,
        invocation_id=invocation_id,
        state=InvocationState.COMPLETED,
    )
    result = _result(request_id, invocation_id, completed_at_ms=1_500)
    store = InMemoryTraceStore()
    inputs = dict(
        store=store,
        task_entries=(task,),
        invocation_records=(invocation,),
        context_bundles=(context,),
        result_records=(result,),
    )

    first = reconcile_retained_trace_authority(
        **inputs,
        base_ingested_at_ms=10_000,
    )
    first_view = store.view(request_id)
    second = reconcile_retained_trace_authority(
        **inputs,
        base_ingested_at_ms=99_000,
    )
    second_view = store.view(request_id)

    assert first.projected_event_count == 7
    assert second.projected_event_count == 0
    assert second.replayed_event_count == 7
    assert first_view == second_view
    assert sum(event.usage.input_tokens for event in second_view.events) == 11
    assert sum(event.usage.output_tokens for event in second_view.events) == 7


def test_completed_specialist_without_result_becomes_typed_gap() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    store = InMemoryTraceStore()

    report = reconcile_retained_trace_authority(
        store=store,
        task_entries=(_task_entry(request_id),),
        invocation_records=(
            _specialist(
                request_id,
                invocation_id=invocation_id,
                state=InvocationState.COMPLETED,
            ),
        ),
        context_bundles=(
            _context(request_id, invocation_id, compiled_at_ms=1_200),
        ),
        result_records=(),
        base_ingested_at_ms=10_000,
    )
    view = store.view(request_id)
    gaps = [
        event.details
        for event in view.events
        if isinstance(event.details, TraceGapDetails)
    ]

    assert report.gap_event_count == 1
    assert view.envelope.disposition == TraceDisposition.INCOMPLETE_GAP
    assert [gap.gap_code for gap in gaps] == [TraceGapCode.MISSING_RESULT]
    assert DurableTraceEventKind.TRACE_TERMINAL not in {
        event.event_kind for event in view.events
    }


def test_orphan_invocation_produces_missing_task_gap_only() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    store = InMemoryTraceStore()

    report = reconcile_retained_trace_authority(
        store=store,
        task_entries=(),
        invocation_records=(
            _specialist(
                request_id,
                invocation_id=invocation_id,
                state=InvocationState.FAILED,
            ),
        ),
        context_bundles=(),
        result_records=(),
        base_ingested_at_ms=10_000,
    )
    view = store.view(request_id)

    assert report.request_count == 1
    assert report.projected_event_count == 1
    assert view.envelope.disposition == TraceDisposition.INCOMPLETE_GAP
    assert isinstance(view.events[0].details, TraceGapDetails)
    assert view.events[0].details.gap_code == TraceGapCode.MISSING_TASK


def test_retry_chain_has_one_request_terminal_and_parent_causality() -> None:
    request_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    first = _specialist(
        request_id,
        invocation_id=first_id,
        state=InvocationState.FAILED,
        attempt=1,
        created_at_ms=1_300,
        updated_at_ms=1_400,
    )
    second = _specialist(
        request_id,
        invocation_id=second_id,
        state=InvocationState.COMPLETED,
        attempt=2,
        parent_invocation_id=first_id,
        created_at_ms=1_500,
        updated_at_ms=1_600,
    )
    result = _result(request_id, second_id, completed_at_ms=1_700)
    store = InMemoryTraceStore()

    reconcile_retained_trace_authority(
        store=store,
        task_entries=(_task_entry(request_id),),
        invocation_records=(second, first),
        context_bundles=(
            _context(request_id, first_id, compiled_at_ms=1_200),
            _context(request_id, second_id, compiled_at_ms=1_450),
        ),
        result_records=(result,),
        base_ingested_at_ms=10_000,
    )
    view = store.view(request_id)
    starts = [
        event
        for event in view.events
        if event.event_kind == DurableTraceEventKind.INVOCATION_STARTED
    ]
    terminals = [
        event
        for event in view.events
        if event.event_kind == DurableTraceEventKind.INVOCATION_TERMINAL
    ]
    request_terminals = [
        event
        for event in view.events
        if event.event_kind == DurableTraceEventKind.TRACE_TERMINAL
    ]

    first_terminal = next(event for event in terminals if event.invocation_id == first_id)
    second_start = next(event for event in starts if event.invocation_id == second_id)
    assert second_start.parent_event_id == first_terminal.event_id
    assert second_start.parent_invocation_id == first_id
    assert len(request_terminals) == 1
    assert view.envelope.disposition == TraceDisposition.COMPLETED


def test_sqlite_reconciliation_reopens_and_replays_without_new_rows(
    tmp_path: Path,
) -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    task = _task_entry(request_id)
    context = _context(request_id, invocation_id, compiled_at_ms=1_200)
    invocation = _specialist(
        request_id,
        invocation_id=invocation_id,
        state=InvocationState.COMPLETED,
    )
    result = _result(request_id, invocation_id, completed_at_ms=1_500)
    path = tmp_path / "traces.sqlite3"
    first = SQLiteTraceStore(path)

    first_report = reconcile_retained_trace_authority(
        store=first,
        task_entries=(task,),
        invocation_records=(invocation,),
        context_bundles=(context,),
        result_records=(result,),
        base_ingested_at_ms=10_000,
    )
    first_view = first.view(request_id)
    first.close()

    reopened = SQLiteTraceStore(path)
    second_report = reconcile_retained_trace_authority(
        store=reopened,
        task_entries=(task,),
        invocation_records=(invocation,),
        context_bundles=(context,),
        result_records=(result,),
        base_ingested_at_ms=99_000,
    )
    second_view = reopened.view(request_id)

    assert first_report.projected_event_count == 7
    assert second_report.projected_event_count == 0
    assert second_report.replayed_event_count == 7
    assert second_view == first_view
    assert len(reopened.load()) == 7
    reopened.close()



def test_latest_retry_outcome_controls_request_terminal() -> None:
    request_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    first = _specialist(
        request_id,
        invocation_id=first_id,
        state=InvocationState.COMPLETED,
        attempt=1,
        created_at_ms=1_300,
        updated_at_ms=1_400,
    )
    second = _specialist(
        request_id,
        invocation_id=second_id,
        state=InvocationState.FAILED,
        attempt=2,
        parent_invocation_id=first_id,
        created_at_ms=1_500,
        updated_at_ms=1_600,
    )
    first_result = _result(request_id, first_id, completed_at_ms=1_450)
    store = InMemoryTraceStore()

    reconcile_retained_trace_authority(
        store=store,
        task_entries=(_task_entry(request_id),),
        invocation_records=(first, second),
        context_bundles=(
            _context(request_id, first_id, compiled_at_ms=1_200),
            _context(request_id, second_id, compiled_at_ms=1_480),
        ),
        result_records=(first_result,),
        base_ingested_at_ms=10_000,
    )
    view = store.view(request_id)
    request_terminals = [
        event
        for event in view.events
        if event.event_kind == DurableTraceEventKind.TRACE_TERMINAL
    ]

    assert len(request_terminals) == 1
    assert view.envelope.disposition == TraceDisposition.FAILED
    assert request_terminals[0].result_id is None


def test_retry_added_after_prior_terminal_becomes_explicit_gap() -> None:
    request_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    first = _specialist(
        request_id,
        invocation_id=first_id,
        state=InvocationState.FAILED,
        attempt=1,
        created_at_ms=1_300,
        updated_at_ms=1_400,
    )
    store = InMemoryTraceStore()

    reconcile_retained_trace_authority(
        store=store,
        task_entries=(_task_entry(request_id),),
        invocation_records=(first,),
        context_bundles=(
            _context(request_id, first_id, compiled_at_ms=1_200),
        ),
        result_records=(),
        base_ingested_at_ms=10_000,
    )
    second = _specialist(
        request_id,
        invocation_id=second_id,
        state=InvocationState.COMPLETED,
        attempt=2,
        parent_invocation_id=first_id,
        created_at_ms=1_500,
        updated_at_ms=1_600,
    )
    second_result = _result(request_id, second_id, completed_at_ms=1_700)

    report = reconcile_retained_trace_authority(
        store=store,
        task_entries=(_task_entry(request_id),),
        invocation_records=(first, second),
        context_bundles=(
            _context(request_id, first_id, compiled_at_ms=1_200),
            _context(request_id, second_id, compiled_at_ms=1_450),
        ),
        result_records=(second_result,),
        base_ingested_at_ms=20_000,
    )
    view = store.view(request_id)

    assert report.gap_event_count == 1
    assert view.envelope.disposition == TraceDisposition.INCOMPLETE_GAP
    assert any(
        isinstance(event.details, TraceGapDetails)
        and event.details.gap_code == TraceGapCode.SOURCE_HASH_MISMATCH
        for event in view.events
    )
    assert sum(
        event.event_kind == DurableTraceEventKind.TRACE_TERMINAL
        for event in view.events
    ) == 1
    event_count = len(view.events)

    replay = reconcile_retained_trace_authority(
        store=store,
        task_entries=(_task_entry(request_id),),
        invocation_records=(first, second),
        context_bundles=(
            _context(request_id, first_id, compiled_at_ms=1_200),
            _context(request_id, second_id, compiled_at_ms=1_450),
        ),
        result_records=(second_result,),
        base_ingested_at_ms=30_000,
    )

    assert replay.projected_event_count == 0
    assert replay.gap_event_count == 1
    assert len(store.view(request_id).events) == event_count


def test_changed_task_terminal_snapshot_becomes_explicit_gap() -> None:
    request_id = uuid4()
    initial = _task_entry(request_id)
    initial = initial.model_copy(
        update={
            "record": initial.record.model_copy(
                update={"phase": AgentTaskPhase.UNKNOWN}
            )
        }
    )
    store = InMemoryTraceStore()

    reconcile_retained_trace_authority(
        store=store,
        task_entries=(initial,),
        invocation_records=(),
        context_bundles=(),
        result_records=(),
        base_ingested_at_ms=10_000,
    )
    cancelled = initial.model_copy(
        update={
            "record": initial.record.model_copy(
                update={
                    "phase": AgentTaskPhase.CANCELLED,
                    "updated_at_ms": 1_300,
                }
            )
        }
    )

    report = reconcile_retained_trace_authority(
        store=store,
        task_entries=(cancelled,),
        invocation_records=(),
        context_bundles=(),
        result_records=(),
        base_ingested_at_ms=20_000,
    )
    view = store.view(request_id)

    assert report.gap_event_count == 1
    assert view.envelope.disposition == TraceDisposition.INCOMPLETE_GAP
    assert any(
        isinstance(event.details, TraceGapDetails)
        and event.details.gap_code == TraceGapCode.SOURCE_HASH_MISMATCH
        for event in view.events
    )


def test_cancelled_task_overrides_nonrouted_routing_disposition() -> None:
    request_id = uuid4()
    decision = RoutingDecision.model_construct(
        decision_id=uuid4(),
        request_id=request_id,
        state=RoutingState.NEEDS_CLARIFICATION,
        selected_agent_id=None,
        selected_agent_version=None,
        method=None,
        confidence_bps=0,
        candidate_agent_ids=(),
        matched_rule_ids=(),
        classifier_invocation_id=None,
        model_calls=0,
        reason="fixture",
    )
    record = AgentTaskRecord.model_construct(
        request_id=request_id,
        phase=AgentTaskPhase.CANCELLED,
        created_at_ms=1_000,
        updated_at_ms=1_200,
        routing_decision=decision,
    )
    entry = AgentTaskStoreEntryV1.model_construct(
        request_id=request_id,
        task_fingerprint=_SHA_A,
        record=record,
    )
    store = InMemoryTraceStore()

    reconcile_retained_trace_authority(
        store=store,
        task_entries=(entry,),
        invocation_records=(),
        context_bundles=(),
        result_records=(),
        base_ingested_at_ms=10_000,
    )
    view = store.view(request_id)

    assert view.envelope.disposition == TraceDisposition.CANCELLED
    terminal = next(
        event
        for event in view.events
        if event.event_kind == DurableTraceEventKind.TRACE_TERMINAL
    )
    assert terminal.details.disposition == TraceDisposition.CANCELLED
