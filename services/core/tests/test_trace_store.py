from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.contracts import (
    InvocationState,
    RoutingMethod,
    RoutingState,
    UsageVector,
)
from simorgh_core.agents.invocations import InvocationEffect, InvocationKind
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    DurableTraceReplayDisposition,
    TraceContextDetails,
    TraceDisposition,
    TraceEventCandidate,
    TraceGapCode,
    TraceGapDetails,
    TraceInvocationDetails,
    TraceResultDetails,
    TraceRoutingDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceTaskDetails,
    TraceTerminalDetails,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_store import (
    InMemoryTraceStore,
    TraceCausalityError,
    TraceClaimKind,
    TraceConflictError,
    TraceStoreClosedError,
    TraceTerminalError,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64
_SHA_E = "e" * 64
_SHA_F = "f" * 64


def _task_event(
    request_id: UUID,
    *,
    occurred_at_ms: int = 1_000,
    source_sha256: str = _SHA_A,
    privacy: PrivacyClassification = PrivacyClassification.INTERNAL,
    retention: RetentionDisposition = RetentionDisposition.PROJECT,
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
        privacy=privacy,
        retention=retention,
    )


def _routing_event(
    request_id: UUID,
    *,
    parent_event_id: UUID,
    decision_id: UUID | None = None,
) -> TraceEventCandidate:
    decision_id = decision_id or uuid4()
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


def _context_event(
    request_id: UUID,
    *,
    parent_event_id: UUID,
    context_id: UUID | None = None,
    replay: bool = False,
    replay_of_event_id: UUID | None = None,
) -> TraceEventCandidate:
    context_id = context_id or uuid4()
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=(
            DurableTraceEventKind.CONTEXT_REPLAYED
            if replay
            else DurableTraceEventKind.CONTEXT_COMPILED
        ),
        stage=TraceStage.CONTEXT,
        source_authority_kind=TraceSourceAuthorityKind.CONTEXT_BUNDLE,
        source_authority_id=context_id,
        source_authority_sha256=_SHA_C,
        parent_event_id=parent_event_id,
        causation_event_id=parent_event_id,
        replay_of_event_id=replay_of_event_id,
        context_bundle_id=context_id,
        replay=(
            DurableTraceReplayDisposition.REPLAYED
            if replay
            else DurableTraceReplayDisposition.FRESH
        ),
        details=TraceContextDetails(
            context_bundle_id=context_id,
            context_sha256=_SHA_C,
            source_manifest_sha256=_SHA_D,
            section_count=3,
            omission_count=0,
        ),
        occurred_at_ms=1_200 if not replay else 1_700,
    )


def _specialist_start(
    request_id: UUID,
    *,
    parent_event_id: UUID,
    invocation_id: UUID | None = None,
) -> TraceEventCandidate:
    invocation_id = invocation_id or uuid4()
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=DurableTraceEventKind.INVOCATION_STARTED,
        stage=TraceStage.SPECIALIST,
        source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
        source_authority_id=invocation_id,
        source_authority_sha256=_SHA_D,
        parent_event_id=parent_event_id,
        causation_event_id=parent_event_id,
        invocation_id=invocation_id,
        details=TraceInvocationDetails(
            invocation_kind=InvocationKind.SPECIALIST,
            effect=InvocationEffect.PROPOSAL,
            state=InvocationState.PENDING,
            operation_id="specialist.execute",
            input_fingerprint=_SHA_D,
        ),
        occurred_at_ms=1_300,
    )


def _specialist_terminal(
    request_id: UUID,
    *,
    parent_event_id: UUID,
    invocation_id: UUID,
    state: InvocationState = InvocationState.COMPLETED,
) -> TraceEventCandidate:
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=DurableTraceEventKind.INVOCATION_TERMINAL,
        stage=TraceStage.SPECIALIST,
        source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
        source_authority_id=invocation_id,
        source_authority_sha256=_SHA_E,
        parent_event_id=parent_event_id,
        causation_event_id=parent_event_id,
        invocation_id=invocation_id,
        details=TraceInvocationDetails(
            invocation_kind=InvocationKind.SPECIALIST,
            effect=InvocationEffect.PROPOSAL,
            state=state,
            operation_id="specialist.execute",
            input_fingerprint=_SHA_D,
            result_payload_sha256=(_SHA_E if state == InvocationState.COMPLETED else None),
            failure_code=(None if state == InvocationState.COMPLETED else "failed"),
        ),
        occurred_at_ms=1_400,
    )


def _result_event(
    request_id: UUID,
    *,
    parent_event_id: UUID,
    invocation_id: UUID,
    result_id: UUID | None = None,
    replay: bool = False,
    replay_of_event_id: UUID | None = None,
) -> TraceEventCandidate:
    result_id = result_id or uuid4()
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=(
            DurableTraceEventKind.RESULT_REPLAYED
            if replay
            else DurableTraceEventKind.RESULT_COMMITTED
        ),
        stage=TraceStage.RESULT,
        source_authority_kind=TraceSourceAuthorityKind.RESULT_RECORD,
        source_authority_id=result_id,
        source_authority_sha256=_SHA_F,
        parent_event_id=parent_event_id,
        causation_event_id=parent_event_id,
        replay_of_event_id=replay_of_event_id,
        invocation_id=invocation_id,
        result_id=result_id,
        replay=(
            DurableTraceReplayDisposition.REPLAYED
            if replay
            else DurableTraceReplayDisposition.FRESH
        ),
        details=TraceResultDetails(
            result_id=result_id,
            result_sha256=_SHA_F,
            result_schema_id="simorgh.specialist-plan-result",
            result_schema_version="1.0",
        ),
        occurred_at_ms=1_500 if not replay else 1_800,
    )


def _terminal_event(
    request_id: UUID,
    *,
    parent_event_id: UUID,
    result_id: UUID,
    disposition: TraceDisposition = TraceDisposition.COMPLETED,
) -> TraceEventCandidate:
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=DurableTraceEventKind.TRACE_TERMINAL,
        stage=TraceStage.TERMINAL,
        source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
        source_authority_id=request_id,
        source_authority_sha256=_SHA_F,
        parent_event_id=parent_event_id,
        causation_event_id=parent_event_id,
        result_id=result_id,
        details=TraceTerminalDetails(
            disposition=disposition,
            reason_code="completed",
        ),
        occurred_at_ms=1_600,
    )


def _append_chain(store: InMemoryTraceStore, request_id: UUID) -> dict[str, UUID]:
    task = store.append(_task_event(request_id), ingested_at_ms=2_000).record
    routing = store.append(
        _routing_event(request_id, parent_event_id=task.event_id),
        ingested_at_ms=2_010,
    ).record
    context = store.append(
        _context_event(request_id, parent_event_id=routing.event_id),
        ingested_at_ms=2_020,
    ).record
    specialist_start = store.append(
        _specialist_start(request_id, parent_event_id=context.event_id),
        ingested_at_ms=2_030,
    ).record
    specialist_terminal = store.append(
        _specialist_terminal(
            request_id,
            parent_event_id=specialist_start.event_id,
            invocation_id=specialist_start.invocation_id,
        ),
        ingested_at_ms=2_040,
    ).record
    result = store.append(
        _result_event(
            request_id,
            parent_event_id=specialist_terminal.event_id,
            invocation_id=specialist_start.invocation_id,
        ),
        ingested_at_ms=2_050,
    ).record
    terminal = store.append(
        _terminal_event(
            request_id,
            parent_event_id=result.event_id,
            result_id=result.result_id,
        ),
        ingested_at_ms=2_060,
    ).record
    return {
        "task": task.event_id,
        "routing": routing.event_id,
        "context": context.event_id,
        "specialist_start": specialist_start.event_id,
        "specialist_terminal": specialist_terminal.event_id,
        "result": result.event_id,
        "terminal": terminal.event_id,
    }


def test_event_identity_and_hash_ignore_observation_time() -> None:
    request_id = uuid4()
    first = _task_event(request_id, occurred_at_ms=1_000)
    second = _task_event(request_id, occurred_at_ms=9_999)

    assert first.event_id == second.event_id
    assert first.canonical_sha256 == second.canonical_sha256


def test_exact_duplicate_is_idempotent_and_preserves_original_sequence() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    first = store.append(_task_event(request_id), ingested_at_ms=2_000)
    duplicate = store.append(
        _task_event(request_id, occurred_at_ms=7_000),
        ingested_at_ms=9_000,
    )

    assert first.kind == TraceClaimKind.NEW
    assert duplicate.kind == TraceClaimKind.REPLAY
    assert duplicate.record == first.record
    assert duplicate.record.sequence == 1
    assert duplicate.record.ingested_at_ms == 2_000


def test_changed_source_content_under_same_event_identity_conflicts() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    store.append(_task_event(request_id), ingested_at_ms=2_000)

    with pytest.raises(TraceConflictError, match="immutable event identity"):
        store.append(
            _task_event(request_id, source_sha256=_SHA_B),
            ingested_at_ms=2_100,
        )


def test_complete_zero_external_chain_builds_ordered_terminal_view() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    event_ids = _append_chain(store, request_id)

    view = store.view(request_id)

    assert view.envelope.disposition == TraceDisposition.COMPLETED
    assert view.envelope.terminal is True
    assert view.envelope.event_count == 7
    assert [event.sequence for event in view.events] == list(range(1, 8))
    assert view.events[-1].event_id == event_ids["terminal"]
    assert view.envelope.gap_count == 0


def test_cross_request_parent_is_rejected() -> None:
    first_request = uuid4()
    second_request = uuid4()
    store = InMemoryTraceStore()
    first_task = store.append(
        _task_event(first_request),
        ingested_at_ms=2_000,
    ).record
    store.append(_task_event(second_request), ingested_at_ms=2_010)

    with pytest.raises(TraceCausalityError, match="another trace"):
        store.append(
            _routing_event(
                second_request,
                parent_event_id=first_task.event_id,
            ),
            ingested_at_ms=2_020,
        )


def test_result_requires_completed_specialist_parent() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    task = store.append(_task_event(request_id), ingested_at_ms=2_000).record
    routing = store.append(
        _routing_event(request_id, parent_event_id=task.event_id),
        ingested_at_ms=2_010,
    ).record
    context = store.append(
        _context_event(request_id, parent_event_id=routing.event_id),
        ingested_at_ms=2_020,
    ).record
    start = store.append(
        _specialist_start(request_id, parent_event_id=context.event_id),
        ingested_at_ms=2_030,
    ).record
    failed = store.append(
        _specialist_terminal(
            request_id,
            parent_event_id=start.event_id,
            invocation_id=start.invocation_id,
            state=InvocationState.FAILED,
        ),
        ingested_at_ms=2_040,
    ).record

    with pytest.raises(TraceCausalityError, match="not completed"):
        store.append(
            _result_event(
                request_id,
                parent_event_id=failed.event_id,
                invocation_id=start.invocation_id,
            ),
            ingested_at_ms=2_050,
        )


def test_replay_links_original_and_adds_zero_usage() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    task = store.append(_task_event(request_id), ingested_at_ms=2_000).record
    routing = store.append(
        _routing_event(request_id, parent_event_id=task.event_id),
        ingested_at_ms=2_010,
    ).record
    context = store.append(
        _context_event(request_id, parent_event_id=routing.event_id),
        ingested_at_ms=2_020,
    ).record

    replay = store.append(
        _context_event(
            request_id,
            parent_event_id=context.event_id,
            context_id=context.context_bundle_id,
            replay=True,
            replay_of_event_id=context.event_id,
        ),
        ingested_at_ms=2_030,
    ).record

    assert replay.replay == DurableTraceReplayDisposition.REPLAYED
    assert replay.replay_of_event_id == context.event_id
    assert replay.usage == UsageVector()

    with pytest.raises(ValidationError, match="cannot report new usage"):
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.CONTEXT_REPLAYED,
            stage=TraceStage.CONTEXT,
            source_authority_kind=TraceSourceAuthorityKind.CONTEXT_BUNDLE,
            source_authority_id=context.context_bundle_id,
            source_authority_sha256=_SHA_C,
            parent_event_id=context.event_id,
            replay_of_event_id=context.event_id,
            context_bundle_id=context.context_bundle_id,
            replay=DurableTraceReplayDisposition.REPLAYED,
            usage=UsageVector(tool_calls=1),
            details=TraceContextDetails(
                context_bundle_id=context.context_bundle_id,
                context_sha256=_SHA_C,
                source_manifest_sha256=_SHA_D,
                section_count=3,
                omission_count=0,
            ),
            occurred_at_ms=3_000,
        )


def test_terminal_trace_rejects_new_fresh_work_but_allows_gap() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    event_ids = _append_chain(store, request_id)

    with pytest.raises(TraceTerminalError, match="terminal durable trace"):
        store.append(
            _routing_event(
                request_id,
                parent_event_id=event_ids["task"],
            ),
            ingested_at_ms=3_000,
        )

    gap_source_id = uuid4()
    gap = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_GAP,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TRACE_RECONCILIATION,
            source_authority_id=gap_source_id,
            source_authority_sha256=_SHA_A,
            details=TraceGapDetails(
                gap_code=TraceGapCode.MISSING_RESULT,
                missing_stage=TraceStage.RESULT,
                missing_source_kind=TraceSourceAuthorityKind.RESULT_RECORD,
            ),
            occurred_at_ms=3_100,
        ),
        ingested_at_ms=3_110,
    ).record

    view = store.view(request_id)
    assert gap.sequence == 8
    assert view.envelope.disposition == TraceDisposition.INCOMPLETE_GAP
    assert view.envelope.gap_count == 1


def test_view_composes_strictest_privacy_and_retention() -> None:
    request_id = uuid4()
    store = InMemoryTraceStore()
    task = store.append(
        _task_event(
            request_id,
            privacy=PrivacyClassification.SENSITIVE,
            retention=RetentionDisposition.LEGAL_HOLD,
        ),
        ingested_at_ms=2_000,
    ).record
    store.append(
        _routing_event(request_id, parent_event_id=task.event_id),
        ingested_at_ms=2_010,
    )

    view = store.view(request_id)

    assert view.envelope.privacy == PrivacyClassification.SENSITIVE
    assert view.envelope.retention == RetentionDisposition.LEGAL_HOLD
    assert view.envelope.disposition == TraceDisposition.IN_PROGRESS
    assert view.envelope.terminal is False


def test_closed_store_fails_closed() -> None:
    store = InMemoryTraceStore()
    store.close()

    with pytest.raises(TraceStoreClosedError, match="closed"):
        store.append(_task_event(uuid4()), ingested_at_ms=2_000)
