from __future__ import annotations

from collections.abc import Iterable
from uuid import NAMESPACE_URL, UUID, uuid5

from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceDisposition,
    TraceEventCandidate,
    TraceEventRecord,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceSupersessionDetails,
    new_trace_event_candidate,
)


def new_trace_superseded_candidate(
    *,
    request_id: UUID,
    previous_status_event: TraceEventRecord,
    source_snapshot_sha256: str,
    resolved_gap_event_ids: Iterable[UUID],
    occurred_at_ms: int,
    parent_event_id: UUID,
) -> TraceEventCandidate:
    """Create one immutable status event that reopens historical terminal state."""

    resolved = _normalized_gap_ids(resolved_gap_event_ids)
    source_id, source_hash = _status_identity(
        request_id=request_id,
        event_kind=DurableTraceEventKind.TRACE_SUPERSEDED,
        previous_status_event_id=previous_status_event.event_id,
        source_snapshot_sha256=source_snapshot_sha256,
        disposition=TraceDisposition.IN_PROGRESS,
        resolved_gap_event_ids=resolved,
    )
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=DurableTraceEventKind.TRACE_SUPERSEDED,
        stage=TraceStage.TERMINAL,
        source_authority_kind=TraceSourceAuthorityKind.TRACE_RECONCILIATION,
        source_authority_id=source_id,
        source_authority_sha256=source_hash,
        parent_event_id=parent_event_id,
        causation_event_id=previous_status_event.event_id,
        occurred_at_ms=occurred_at_ms,
        details=TraceSupersessionDetails(
            previous_status_event_id=previous_status_event.event_id,
            source_snapshot_sha256=source_snapshot_sha256,
            disposition=TraceDisposition.IN_PROGRESS,
            terminal=False,
            reason_code="source-authority-advanced",
            resolved_gap_event_ids=resolved,
        ),
    )


def new_trace_resolved_candidate(
    *,
    request_id: UUID,
    superseded_event: TraceEventRecord,
    source_snapshot_sha256: str,
    disposition: TraceDisposition,
    reason_code: str,
    occurred_at_ms: int,
    parent_event_id: UUID,
    resolved_gap_event_ids: Iterable[UUID] = (),
    result_id: UUID | None = None,
    privacy: PrivacyClassification = PrivacyClassification.INTERNAL,
    retention: RetentionDisposition = RetentionDisposition.PROJECT,
) -> TraceEventCandidate:
    """Create the terminal current-status event for one superseded trace epoch."""

    resolved = _normalized_gap_ids(resolved_gap_event_ids)
    source_id, source_hash = _status_identity(
        request_id=request_id,
        event_kind=DurableTraceEventKind.TRACE_RESOLVED,
        previous_status_event_id=superseded_event.event_id,
        source_snapshot_sha256=source_snapshot_sha256,
        disposition=disposition,
        resolved_gap_event_ids=resolved,
    )
    return new_trace_event_candidate(
        request_id=request_id,
        event_kind=DurableTraceEventKind.TRACE_RESOLVED,
        stage=TraceStage.TERMINAL,
        source_authority_kind=TraceSourceAuthorityKind.TRACE_RECONCILIATION,
        source_authority_id=source_id,
        source_authority_sha256=source_hash,
        parent_event_id=parent_event_id,
        causation_event_id=superseded_event.event_id,
        result_id=result_id,
        occurred_at_ms=occurred_at_ms,
        privacy=privacy,
        retention=retention,
        details=TraceSupersessionDetails(
            previous_status_event_id=superseded_event.event_id,
            source_snapshot_sha256=source_snapshot_sha256,
            disposition=disposition,
            terminal=True,
            reason_code=reason_code,
            resolved_gap_event_ids=resolved,
        ),
    )


def _status_identity(
    *,
    request_id: UUID,
    event_kind: DurableTraceEventKind,
    previous_status_event_id: UUID,
    source_snapshot_sha256: str,
    disposition: TraceDisposition,
    resolved_gap_event_ids: tuple[UUID, ...],
) -> tuple[UUID, str]:
    payload = {
        "request_id": str(request_id),
        "event_kind": event_kind.value,
        "previous_status_event_id": str(previous_status_event_id),
        "source_snapshot_sha256": source_snapshot_sha256,
        "disposition": disposition.value,
        "resolved_gap_event_ids": [str(value) for value in resolved_gap_event_ids],
    }
    source_hash = canonical_fingerprint(payload)
    source_id = uuid5(
        NAMESPACE_URL,
        "simorgh-trace-status:"
        f"{request_id}:{event_kind.value}:{previous_status_event_id}:"
        f"{source_snapshot_sha256}:{disposition.value}:{source_hash}",
    )
    return source_id, source_hash


def _normalized_gap_ids(values: Iterable[UUID]) -> tuple[UUID, ...]:
    return tuple(sorted(set(values), key=str))


__all__ = [
    "new_trace_resolved_candidate",
    "new_trace_superseded_candidate",
]
