from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.invocations import InvocationRecord, canonical_fingerprint
from simorgh_core.agents.result_authority import (
    AuthoritativeSpecialistResult,
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceDisposition,
    TraceEventRecord,
    TraceGapCode,
    TraceGapDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_source_evolution import (
    active_trace_supersession_event,
    resolvable_gap_event_ids,
    source_authority_snapshot_sha256,
    terminal_trace_status_event,
)
from simorgh_core.agents.trace_store import TraceClaim, TraceStore
from simorgh_core.agents.trace_supersession import (
    new_trace_resolved_candidate,
    new_trace_superseded_candidate,
)


def open_source_evolution_epoch(
    *,
    store: TraceStore,
    entry: AgentTaskStoreEntryV1,
    invocations: tuple[InvocationRecord, ...],
    contexts: tuple[SpecialistContextBundle, ...],
    results: tuple[AuthoritativeSpecialistResult, ...],
    base_ingested_at_ms: int,
) -> tuple[TraceClaim, TraceClaim]:
    """Append/replay one source-mismatch gap and typed nonterminal supersession."""

    if base_ingested_at_ms < 0:
        raise ValueError("base ingestion time cannot be negative")
    view = store.view(entry.request_id)
    previous_status = terminal_trace_status_event(view)
    if previous_status is None:
        raise RuntimeError(
            "source evolution requires an existing terminal trace status"
        )
    snapshot = source_authority_snapshot_sha256(
        entry=entry,
        invocations=invocations,
        contexts=contexts,
        results=results,
    )
    gap_source_id = uuid5(
        NAMESPACE_URL,
        "simorgh-trace-source-evolution:"
        f"{entry.request_id}:{previous_status.event_id}:{snapshot}",
    )
    gap_hash = canonical_fingerprint(
        {
            "request_id": str(entry.request_id),
            "previous_status_event_id": str(previous_status.event_id),
            "source_snapshot_sha256": snapshot,
            "gap_code": TraceGapCode.SOURCE_HASH_MISMATCH.value,
        }
    )
    gap_claim = store.append(
        new_trace_event_candidate(
            request_id=entry.request_id,
            event_kind=DurableTraceEventKind.TRACE_GAP,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TRACE_RECONCILIATION,
            source_authority_id=gap_source_id,
            source_authority_sha256=gap_hash,
            parent_event_id=previous_status.event_id,
            causation_event_id=previous_status.event_id,
            details=TraceGapDetails(
                gap_code=TraceGapCode.SOURCE_HASH_MISMATCH,
                missing_stage=TraceStage.TERMINAL,
                missing_source_kind=TraceSourceAuthorityKind.TASK_RECORD,
                missing_source_id=entry.request_id,
            ),
            occurred_at_ms=entry.record.updated_at_ms,
        ),
        ingested_at_ms=base_ingested_at_ms,
    )
    current_view = store.view(entry.request_id)
    resolved = set(
        resolvable_gap_event_ids(
            view=current_view,
            entry=entry,
            invocations=invocations,
            contexts=contexts,
            results=results,
        )
    )
    resolved.add(gap_claim.record.event_id)
    superseded_claim = store.append(
        new_trace_superseded_candidate(
            request_id=entry.request_id,
            previous_status_event=previous_status,
            source_snapshot_sha256=snapshot,
            resolved_gap_event_ids=resolved,
            occurred_at_ms=entry.record.updated_at_ms,
            parent_event_id=gap_claim.record.event_id,
        ),
        ingested_at_ms=base_ingested_at_ms + 1,
    )
    return gap_claim, superseded_claim


def append_current_trace_resolution(
    *,
    store: TraceStore,
    entry: AgentTaskStoreEntryV1,
    invocations: tuple[InvocationRecord, ...],
    contexts: tuple[SpecialistContextBundle, ...],
    results: tuple[AuthoritativeSpecialistResult, ...],
    parent_event_id: UUID,
    disposition: TraceDisposition,
    reason_code: str,
    occurred_at_ms: int,
    ingested_at_ms: int,
    result_id: UUID | None = None,
    privacy: PrivacyClassification = PrivacyClassification.INTERNAL,
    retention: RetentionDisposition = RetentionDisposition.PROJECT,
) -> TraceClaim | None:
    """Append/replay terminal resolution when the trace has a supersession epoch."""

    view = store.view(entry.request_id)
    superseded = active_trace_supersession_event(view)
    if superseded is None:
        return None
    snapshot = source_authority_snapshot_sha256(
        entry=entry,
        invocations=invocations,
        contexts=contexts,
        results=results,
    )
    resolved = resolvable_gap_event_ids(
        view=view,
        entry=entry,
        invocations=invocations,
        contexts=contexts,
        results=results,
    )
    return store.append(
        new_trace_resolved_candidate(
            request_id=entry.request_id,
            superseded_event=superseded,
            source_snapshot_sha256=snapshot,
            disposition=disposition,
            reason_code=reason_code,
            occurred_at_ms=occurred_at_ms,
            parent_event_id=parent_event_id,
            resolved_gap_event_ids=resolved,
            result_id=result_id,
            privacy=privacy,
            retention=retention,
        ),
        ingested_at_ms=ingested_at_ms,
    )


__all__ = [
    "append_current_trace_resolution",
    "open_source_evolution_epoch",
]
