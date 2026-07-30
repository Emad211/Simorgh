from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict

from simorgh_core.agents.cancellation_contracts import (
    CancellationReplayDisposition,
    TaskCancellationResult,
    canonical_cancellation_hash,
)
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_child_invocations import ChildTraceProjectionReport
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    DurableTraceReplayDisposition,
    TraceCancellationDetails,
    TraceDisposition,
    TraceEventCandidate,
    TraceEventRecord,
    TraceSourceAuthorityKind,
    TraceStage,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_store import TraceClaimKind, TraceStore


class CancellationTraceProjection(ChildTraceProjectionReport):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event: TraceEventRecord
    disposition: TraceDisposition
    reason_code: str


def project_task_cancellation(
    *,
    store: TraceStore,
    task_entry: AgentTaskStoreEntryV1,
    parent_event: TraceEventRecord,
    base_ingested_at_ms: int,
) -> CancellationTraceProjection | None:
    """Project one typed cancellation settlement from durable task authority."""

    result = task_entry.record.cancellation_result
    if result is None:
        return None
    if base_ingested_at_ms < 0:
        raise ValueError("base ingestion time cannot be negative")

    original = result.model_copy(
        update={"replay": CancellationReplayDisposition.FRESH}
    )
    original_claim = store.append(
        _candidate(
            result=original,
            event_kind=DurableTraceEventKind.CANCELLATION_SETTLED,
            parent_event=parent_event,
        ),
        ingested_at_ms=base_ingested_at_ms,
    )
    projected, replayed = _count_claim(original_claim.kind)
    final_event = original_claim.record

    if result.replayed:
        replay_claim = store.append(
            _candidate(
                result=result,
                event_kind=DurableTraceEventKind.CANCELLATION_REPLAYED,
                parent_event=original_claim.record,
                replay_of_event_id=original_claim.record.event_id,
                replay=DurableTraceReplayDisposition.REPLAYED,
            ),
            ingested_at_ms=base_ingested_at_ms + 1,
        )
        if replay_claim.kind == TraceClaimKind.NEW:
            projected += 1
        else:
            replayed += 1
        final_event = replay_claim.record

    uncertain = result.reserved_uncertain_count
    return CancellationTraceProjection(
        projected_event_count=projected,
        replayed_event_count=replayed,
        event=final_event,
        disposition=(
            TraceDisposition.UNKNOWN_SIDE_EFFECT
            if uncertain
            else TraceDisposition.CANCELLED
        ),
        reason_code=(
            "cancellation-partially-uncertain"
            if uncertain
            else "cancellation-settled"
        ),
    )


def _candidate(
    *,
    result: TaskCancellationResult,
    event_kind: DurableTraceEventKind,
    parent_event: TraceEventRecord,
    replay_of_event_id: UUID | None = None,
    replay: DurableTraceReplayDisposition = DurableTraceReplayDisposition.FRESH,
) -> TraceEventCandidate:
    cancellation_hash = canonical_cancellation_hash(result)
    return new_trace_event_candidate(
        request_id=result.request.request_id,
        event_kind=event_kind,
        stage=TraceStage.CANCELLATION,
        source_authority_kind=TraceSourceAuthorityKind.CANCELLATION_RECORD,
        source_authority_id=result.audit_event_id,
        source_authority_sha256=cancellation_hash,
        parent_event_id=parent_event.event_id,
        causation_event_id=parent_event.event_id,
        replay_of_event_id=replay_of_event_id,
        replay=replay,
        occurred_at_ms=result.completed_at_ms,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
        details=TraceCancellationDetails(
            cancellation_id=result.request.cancellation_id,
            cancellation_sha256=cancellation_hash,
            settled_invocation_count=(
                result.terminal_count
                + result.pending_cancelled_count
                + result.reserved_cancelled_count
            ),
            uncertain_invocation_count=result.reserved_uncertain_count,
        ),
    )


def _count_claim(kind: TraceClaimKind) -> tuple[int, int]:
    if kind == TraceClaimKind.NEW:
        return 1, 0
    return 0, 1


__all__ = ["CancellationTraceProjection", "project_task_cancellation"]
