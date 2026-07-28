from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
    strictest_privacy,
    strictest_retention,
)
from simorgh_core.agents.trace_authority import (
    CorrelatedTraceEvent,
    TracePhase,
    TraceUncertaintyDisposition,
    canonical_trace_event_sha256,
    trace_id_for_request,
)
from simorgh_core.agents.trace_store import TraceStore
from simorgh_core.agents.tracing import TraceEventKind


class TraceQueryError(RuntimeError):
    pass


class TraceIntegrityStatus(StrEnum):
    VALID = "valid"


class ExecutionTraceSummary(BaseModel):
    """Deterministic metadata-only projection over immutable trace events."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    trace_id: UUID
    request_id: UUID
    first_occurred_at_ms: int = Field(ge=0)
    last_occurred_at_ms: int = Field(ge=0)
    event_count: int = Field(ge=1)
    first_sequence: int = Field(ge=1)
    last_sequence: int = Field(ge=1)
    route_covered: bool
    context_covered: bool
    specialist_covered: bool
    model_covered: bool
    tool_covered: bool
    result_covered: bool
    cancellation_covered: bool
    replay_covered: bool
    terminal_covered: bool
    terminal_outcome: str | None = Field(default=None, max_length=128)
    uncertainty: TraceUncertaintyDisposition
    committed_usage: UsageVector
    privacy: PrivacyClassification
    retention: RetentionDisposition
    tainted: bool
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    integrity: TraceIntegrityStatus = TraceIntegrityStatus.VALID

    @model_validator(mode="after")
    def validate_summary(self) -> ExecutionTraceSummary:
        if self.trace_id != trace_id_for_request(self.request_id):
            raise ValueError("trace summary identity does not match request")
        if self.last_occurred_at_ms < self.first_occurred_at_ms:
            raise ValueError("trace summary time range is reversed")
        if self.last_sequence < self.first_sequence:
            raise ValueError("trace summary sequence range is reversed")
        if self.event_count != self.last_sequence - self.first_sequence + 1:
            raise ValueError("trace summary sequence range is not contiguous")
        return self


class TraceQueryService:
    """Bounded metadata-only queries over the durable trace authority."""

    def __init__(self, store: TraceStore) -> None:
        self._store = store

    def events_for_request(
        self,
        request_id: UUID,
    ) -> tuple[CorrelatedTraceEvent, ...]:
        return self._store.for_request(request_id)

    def events_for_trace(
        self,
        trace_id: UUID,
    ) -> tuple[CorrelatedTraceEvent, ...]:
        return self._store.for_trace(trace_id)

    def events_for_invocation(
        self,
        invocation_id: UUID,
    ) -> tuple[CorrelatedTraceEvent, ...]:
        return self._filter(invocation_id=invocation_id)

    def events_for_context(
        self,
        context_bundle_id: UUID,
    ) -> tuple[CorrelatedTraceEvent, ...]:
        return self._filter(context_bundle_id=context_bundle_id)

    def events_for_result(
        self,
        result_id: UUID,
    ) -> tuple[CorrelatedTraceEvent, ...]:
        return self._filter(result_id=result_id)

    def events_for_cancellation(
        self,
        cancellation_id: UUID,
    ) -> tuple[CorrelatedTraceEvent, ...]:
        return self._filter(cancellation_id=cancellation_id)

    def summary_for_request(self, request_id: UUID) -> ExecutionTraceSummary:
        events = self.events_for_request(request_id)
        if not events:
            raise TraceQueryError("request has no correlated trace events")
        return derive_trace_summary(events)

    def _filter(
        self,
        *,
        invocation_id: UUID | None = None,
        context_bundle_id: UUID | None = None,
        result_id: UUID | None = None,
        cancellation_id: UUID | None = None,
    ) -> tuple[CorrelatedTraceEvent, ...]:
        matches = (
            event
            for event in self._store.load()
            if (
                (invocation_id is None or event.invocation_id == invocation_id)
                and (
                    context_bundle_id is None
                    or event.context_bundle_id == context_bundle_id
                )
                and (result_id is None or event.result_id == result_id)
                and (
                    cancellation_id is None
                    or event.cancellation_id == cancellation_id
                )
            )
        )
        return tuple(
            sorted(
                matches,
                key=lambda event: (str(event.trace_id), event.causal_sequence),
            )
        )


def derive_trace_summary(
    events: tuple[CorrelatedTraceEvent, ...]
    | list[CorrelatedTraceEvent],
) -> ExecutionTraceSummary:
    if not events:
        raise TraceQueryError("cannot summarize an empty trace")
    ordered = tuple(sorted(events, key=lambda event: event.causal_sequence))
    trace_id = ordered[0].trace_id
    request_id = ordered[0].request_id
    expected_sequences = tuple(range(1, len(ordered) + 1))
    actual_sequences = tuple(event.causal_sequence for event in ordered)
    if actual_sequences != expected_sequences:
        raise TraceQueryError("trace causal sequence is not contiguous")
    for event in ordered:
        if event.trace_id != trace_id or event.request_id != request_id:
            raise TraceQueryError("trace contains cross-request events")
        if event.canonical_sha256 != canonical_trace_event_sha256(event):
            raise TraceQueryError("trace contains an invalid event hash")

    usage = UsageVector()
    for event in ordered:
        usage = usage.plus(event.usage_delta)
    uncertainty = _strictest_uncertainty(ordered)
    terminal = next(
        (
            event
            for event in reversed(ordered)
            if event.phase == TracePhase.TERMINAL
        ),
        None,
    )
    canonical_sha256 = canonical_fingerprint(
        {
            "trace_id": str(trace_id),
            "request_id": str(request_id),
            "events": [
                {
                    "sequence": event.causal_sequence,
                    "event_id": str(event.event_id),
                    "event_sha256": event.canonical_sha256,
                }
                for event in ordered
            ],
        }
    )
    replay_kinds = {
        TraceEventKind.INVOCATION_REPLAYED,
        TraceEventKind.RESULT_REPLAYED,
        TraceEventKind.CONTEXT_REPLAYED,
        TraceEventKind.CANCELLATION_REPLAYED,
    }
    phases = {event.phase for event in ordered}
    return ExecutionTraceSummary(
        trace_id=trace_id,
        request_id=request_id,
        first_occurred_at_ms=min(event.occurred_at_ms for event in ordered),
        last_occurred_at_ms=max(event.occurred_at_ms for event in ordered),
        event_count=len(ordered),
        first_sequence=ordered[0].causal_sequence,
        last_sequence=ordered[-1].causal_sequence,
        route_covered=TracePhase.ROUTING in phases,
        context_covered=TracePhase.CONTEXT in phases,
        specialist_covered=TracePhase.SPECIALIST in phases,
        model_covered=TracePhase.MODEL in phases,
        tool_covered=TracePhase.TOOL in phases,
        result_covered=TracePhase.RESULT in phases,
        cancellation_covered=TracePhase.CANCELLATION in phases,
        replay_covered=any(event.kind in replay_kinds for event in ordered),
        terminal_covered=terminal is not None,
        terminal_outcome=terminal.outcome if terminal is not None else None,
        uncertainty=uncertainty,
        committed_usage=usage,
        privacy=strictest_privacy(event.privacy for event in ordered),
        retention=strictest_retention(event.retention for event in ordered),
        tainted=any(event.tainted for event in ordered),
        canonical_sha256=canonical_sha256,
    )


def _strictest_uncertainty(
    events: tuple[CorrelatedTraceEvent, ...],
) -> TraceUncertaintyDisposition:
    values = {event.uncertainty for event in events}
    if TraceUncertaintyDisposition.UNKNOWN_SIDE_EFFECT in values:
        return TraceUncertaintyDisposition.UNKNOWN_SIDE_EFFECT
    if TraceUncertaintyDisposition.UNKNOWN in values:
        return TraceUncertaintyDisposition.UNKNOWN
    return TraceUncertaintyDisposition.NONE


__all__ = [
    "ExecutionTraceSummary",
    "TraceIntegrityStatus",
    "TraceQueryError",
    "TraceQueryService",
    "derive_trace_summary",
]
