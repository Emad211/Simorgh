from __future__ import annotations

from uuid import uuid4

from simorgh_core.agents.cancellation_contracts import (
    CancellationDisposition,
    CancellationReplayDisposition,
    CancellationRequesterAuthority,
    TaskCancellationRequest,
    TaskCancellationResult,
)
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_cancellation_projection import (
    project_task_cancellation,
)
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    DurableTraceReplayDisposition,
    TraceCancellationDetails,
    TraceDisposition,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceTaskDetails,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore

_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _task_entry(
    *,
    uncertain: int = 0,
    replay: CancellationReplayDisposition = CancellationReplayDisposition.FRESH,
) -> AgentTaskStoreEntryV1:
    request_id = uuid4()
    private_reason = "private operator reason must not enter trace"
    request = TaskCancellationRequest.model_construct(
        request_id=request_id,
        cancellation_id=uuid4(),
        requested_at_ms=1_100,
        reason_code="operator_requested",
        operator_reason=private_reason,
        requester_authority=CancellationRequesterAuthority.OPERATOR,
        observed_task_phase="routed",
        observed_task_version=1_000,
    )
    result = TaskCancellationResult.model_construct(
        request=request,
        accepted_at_ms=1_200,
        completed_at_ms=1_300,
        ownership_snapshot_sha256=_SHA_B,
        outcomes=(),
        terminal_count=2,
        pending_cancelled_count=1,
        reserved_cancelled_count=1,
        reserved_uncertain_count=uncertain,
        signalled_count=0,
        disposition=(
            CancellationDisposition.PARTIALLY_UNCERTAIN
            if uncertain
            else CancellationDisposition.APPLIED
        ),
        audit_event_id=uuid4(),
        replay=replay,
    )
    return AgentTaskStoreEntryV1.model_construct(
        request_id=request_id,
        task_fingerprint=_SHA_A,
        record=AgentTaskRecord.model_construct(
            request_id=request_id,
            phase=AgentTaskPhase.CANCELLED,
            created_at_ms=1_000,
            updated_at_ms=1_300,
            cancellation_request=request,
            cancellation_result=result,
            cancel_reason=private_reason,
        ),
    )


def _task_claim(store: InMemoryTraceStore, entry: AgentTaskStoreEntryV1):
    return store.append(
        new_trace_event_candidate(
            request_id=entry.request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=entry.request_id,
            source_authority_sha256=entry.task_fingerprint,
            details=TraceTaskDetails(
                task_fingerprint=entry.task_fingerprint,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=1_000,
        ),
        ingested_at_ms=2_000,
    ).record


def test_cancellation_settlement_is_typed_and_privacy_safe() -> None:
    entry = _task_entry()
    store = InMemoryTraceStore()
    parent = _task_claim(store, entry)

    projection = project_task_cancellation(
        store=store,
        task_entry=entry,
        parent_event=parent,
        base_ingested_at_ms=2_100,
    )

    assert projection is not None
    assert projection.disposition == TraceDisposition.CANCELLED
    assert projection.event.event_kind == DurableTraceEventKind.CANCELLATION_SETTLED
    assert projection.event.parent_event_id == parent.event_id
    assert isinstance(projection.event.details, TraceCancellationDetails)
    assert projection.event.details.settled_invocation_count == 4
    assert projection.event.details.uncertain_invocation_count == 0
    serialized = str(store.view(entry.request_id).model_dump(mode="json"))
    assert "private operator reason" not in serialized


def test_uncertain_cancellation_uses_unknown_side_effect_terminal_disposition() -> None:
    entry = _task_entry(uncertain=2)
    store = InMemoryTraceStore()
    parent = _task_claim(store, entry)

    projection = project_task_cancellation(
        store=store,
        task_entry=entry,
        parent_event=parent,
        base_ingested_at_ms=2_100,
    )

    assert projection is not None
    assert projection.disposition == TraceDisposition.UNKNOWN_SIDE_EFFECT
    assert projection.reason_code == "cancellation-partially-uncertain"
    assert projection.event.details.uncertain_invocation_count == 2


def test_replayed_cancellation_links_original_and_adds_no_usage() -> None:
    entry = _task_entry(replay=CancellationReplayDisposition.REPLAYED)
    store = InMemoryTraceStore()
    parent = _task_claim(store, entry)

    projection = project_task_cancellation(
        store=store,
        task_entry=entry,
        parent_event=parent,
        base_ingested_at_ms=2_100,
    )
    events = store.view(entry.request_id).events
    settled = events[1]
    replayed = events[2]

    assert projection is not None
    assert projection.projected_event_count == 2
    assert settled.event_kind == DurableTraceEventKind.CANCELLATION_SETTLED
    assert replayed.event_kind == DurableTraceEventKind.CANCELLATION_REPLAYED
    assert replayed.replay == DurableTraceReplayDisposition.REPLAYED
    assert replayed.replay_of_event_id == settled.event_id
    assert replayed.parent_event_id == settled.event_id
    assert replayed.usage.model_calls == 0
    assert replayed.usage.tool_calls == 0
