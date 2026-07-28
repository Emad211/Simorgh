from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.trace_authority import (
    TraceAttributes,
    TraceCompletenessStatus,
    TraceEventDraft,
    TraceGap,
    TraceGapCode,
    TraceOutcomeCode,
    TraceReasonCode,
    build_trace_projection,
    stored_trace_event,
    trace_event_id_for,
    trace_id_for,
)
from simorgh_core.agents.tracing import CacheDisposition, TraceEventKind


def _draft(
    request_id: UUID,
    *,
    kind: TraceEventKind = TraceEventKind.ROUTING_STARTED,
    logical_identity: str = "routing:start",
    occurred_at_ms: int = 1_000,
    outcome: TraceOutcomeCode = TraceOutcomeCode.STARTED,
    usage_delta: UsageVector | None = None,
    committed_usage: UsageVector | None = None,
) -> TraceEventDraft:
    return TraceEventDraft(
        event_id=trace_event_id_for(
            request_id=request_id,
            kind=kind,
            logical_identity=logical_identity,
        ),
        trace_id=trace_id_for(request_id),
        request_id=request_id,
        kind=kind,
        occurred_at_ms=occurred_at_ms,
        cache=CacheDisposition.NOT_APPLICABLE,
        outcome=outcome,
        reason_code=TraceReasonCode.STARTED_APPROVED_WORK,
        usage_delta=usage_delta or UsageVector(),
        committed_usage=committed_usage,
    )


def test_trace_and_event_identity_are_stable() -> None:
    request_id = uuid4()

    assert trace_id_for(request_id) == trace_id_for(request_id)
    assert trace_event_id_for(
        request_id=request_id,
        kind=TraceEventKind.ROUTING_STARTED,
        logical_identity="routing:start",
    ) == trace_event_id_for(
        request_id=request_id,
        kind=TraceEventKind.ROUTING_STARTED,
        logical_identity="routing:start",
    )


def test_trace_draft_rejects_foreign_trace_identity() -> None:
    request_id = uuid4()
    payload = _draft(request_id).model_dump(mode="json")
    payload["trace_id"] = str(uuid4())

    with pytest.raises(ValidationError, match="trace identity"):
        TraceEventDraft.model_validate(payload)


def test_projection_preserves_sequence_usage_and_terminal_status() -> None:
    request_id = uuid4()
    first = stored_trace_event(_draft(request_id), sequence=1)
    second = stored_trace_event(
        _draft(
            request_id,
            kind=TraceEventKind.RESULT_COMMITTED,
            logical_identity="result:commit",
            occurred_at_ms=900,
            outcome=TraceOutcomeCode.COMPLETED,
            usage_delta=UsageVector(tool_calls=1),
            committed_usage=UsageVector(tool_calls=1),
        ),
        sequence=2,
    )

    projection = build_trace_projection((second, first))

    assert tuple(event.sequence for event in projection.events) == (1, 2)
    assert projection.first_occurred_at_ms == 1_000
    assert projection.last_occurred_at_ms == 900
    assert projection.total_usage_delta == UsageVector(tool_calls=1)
    assert projection.latest_committed_usage == UsageVector(tool_calls=1)
    assert projection.completeness == TraceCompletenessStatus.COMPLETE
    assert len(projection.canonical_sha256) == 64


def test_projection_with_gap_is_explicit_and_hashed() -> None:
    request_id = uuid4()
    event = stored_trace_event(_draft(request_id), sequence=1)
    gap = TraceGap(
        code=TraceGapCode.MISSING_EVENT,
        after_sequence=1,
        expected_kind=TraceEventKind.ROUTING_COMPLETED,
    )

    projection = build_trace_projection((event,), gaps=(gap,))

    assert projection.completeness == TraceCompletenessStatus.GAP_DETECTED
    assert projection.gaps == (gap,)


def test_gap_outcome_requires_typed_gap_attribute() -> None:
    request_id = uuid4()

    with pytest.raises(ValidationError, match="typed gap code"):
        TraceEventDraft(
            event_id=trace_event_id_for(
                request_id=request_id,
                kind=TraceEventKind.TERMINAL,
                logical_identity="gap",
            ),
            trace_id=trace_id_for(request_id),
            request_id=request_id,
            kind=TraceEventKind.TERMINAL,
            occurred_at_ms=1_000,
            outcome=TraceOutcomeCode.GAP_DETECTED,
        )

    accepted = TraceEventDraft(
        event_id=trace_event_id_for(
            request_id=request_id,
            kind=TraceEventKind.TERMINAL,
            logical_identity="gap",
        ),
        trace_id=trace_id_for(request_id),
        request_id=request_id,
        kind=TraceEventKind.TERMINAL,
        occurred_at_ms=1_000,
        outcome=TraceOutcomeCode.GAP_DETECTED,
        attributes=TraceAttributes(gap_code=TraceGapCode.MISSING_EVENT),
    )
    assert accepted.attributes.gap_code == TraceGapCode.MISSING_EVENT
