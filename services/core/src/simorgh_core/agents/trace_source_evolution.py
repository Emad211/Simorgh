from __future__ import annotations

from uuid import UUID

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.invocations import InvocationRecord, canonical_fingerprint
from simorgh_core.agents.result_authority import AuthoritativeSpecialistResult
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceEventRecord,
    TraceGapCode,
    TraceSupersessionDetails,
    TraceTerminalDetails,
    TraceView,
)


def source_authority_snapshot_sha256(
    *,
    entry: AgentTaskStoreEntryV1,
    invocations: tuple[InvocationRecord, ...],
    contexts: tuple[SpecialistContextBundle, ...],
    results: tuple[AuthoritativeSpecialistResult, ...],
) -> str:
    """Hash safe source identities and hashes without retaining private bodies."""

    decision = entry.record.routing_decision
    cancellation_request = entry.record.cancellation_request
    cancellation_result = entry.record.cancellation_result
    return canonical_fingerprint(
        {
            "request_id": str(entry.request_id),
            "task_fingerprint": entry.task_fingerprint,
            "task_phase": entry.record.phase.value,
            "task_updated_at_ms": entry.record.updated_at_ms,
            "routing_sha256": (
                canonical_fingerprint(decision) if decision is not None else None
            ),
            "cancellation_request_sha256": (
                canonical_fingerprint(cancellation_request)
                if cancellation_request is not None
                else None
            ),
            "cancellation_result_sha256": (
                canonical_fingerprint(cancellation_result)
                if cancellation_result is not None
                else None
            ),
            "invocations": [
                {
                    "invocation_id": str(record.invocation_id),
                    "canonical_sha256": canonical_fingerprint(record),
                }
                for record in sorted(invocations, key=lambda item: str(item.invocation_id))
            ],
            "contexts": [
                {
                    "context_bundle_id": str(bundle.context_bundle_id),
                    "canonical_sha256": bundle.canonical_sha256,
                }
                for bundle in sorted(
                    contexts,
                    key=lambda item: str(item.context_bundle_id),
                )
            ],
            "results": [
                {
                    "result_id": str(result.result_id),
                    "canonical_sha256": result.canonical_sha256,
                }
                for result in sorted(results, key=lambda item: str(item.result_id))
            ],
        }
    )


def latest_trace_status_event(view: TraceView) -> TraceEventRecord | None:
    return next(
        (
            event
            for event in reversed(view.events)
            if event.event_kind
            in {
                DurableTraceEventKind.TRACE_TERMINAL,
                DurableTraceEventKind.TRACE_SUPERSEDED,
                DurableTraceEventKind.TRACE_RESOLVED,
            }
        ),
        None,
    )


def active_trace_supersession_event(view: TraceView) -> TraceEventRecord | None:
    status = latest_trace_status_event(view)
    if status is None:
        return None
    if (
        status.event_kind == DurableTraceEventKind.TRACE_SUPERSEDED
        and isinstance(status.details, TraceSupersessionDetails)
        and not status.details.terminal
    ):
        return status
    if (
        status.event_kind == DurableTraceEventKind.TRACE_RESOLVED
        and isinstance(status.details, TraceSupersessionDetails)
    ):
        previous_id = status.details.previous_status_event_id
        return next(
            (
                event
                for event in view.events
                if event.event_id == previous_id
                and event.event_kind == DurableTraceEventKind.TRACE_SUPERSEDED
                and isinstance(event.details, TraceSupersessionDetails)
            ),
            None,
        )
    return None


def terminal_trace_status_event(view: TraceView) -> TraceEventRecord | None:
    status = latest_trace_status_event(view)
    if status is None:
        return None
    if isinstance(status.details, TraceTerminalDetails):
        return status
    if isinstance(status.details, TraceSupersessionDetails) and status.details.terminal:
        return status
    return None


def resolvable_gap_event_ids(
    *,
    view: TraceView,
    entry: AgentTaskStoreEntryV1,
    invocations: tuple[InvocationRecord, ...],
    contexts: tuple[SpecialistContextBundle, ...],
    results: tuple[AuthoritativeSpecialistResult, ...],
) -> tuple[UUID, ...]:
    """Return unresolved historical gaps proven satisfied by current authority."""

    unresolved = set(view.envelope.unresolved_gap_event_ids)
    if not unresolved:
        return ()
    invocation_by_id = {record.invocation_id: record for record in invocations}
    context_invocation_ids = {
        bundle.specialist_invocation_id for bundle in contexts
    }
    result_invocation_ids = {result.invocation_id for result in results}
    decision = entry.record.routing_decision
    resolved: list[UUID] = []
    for gap in view.envelope.gaps:
        if gap.gap_event_id not in unresolved:
            continue
        source_id = gap.missing_source_id
        if gap.code == TraceGapCode.SOURCE_HASH_MISMATCH:
            resolved.append(gap.gap_event_id)
        elif gap.code == TraceGapCode.MISSING_TASK:
            resolved.append(gap.gap_event_id)
        elif gap.code == TraceGapCode.MISSING_ROUTING and decision is not None:
            resolved.append(gap.gap_event_id)
        elif (
            gap.code == TraceGapCode.MISSING_CONTEXT
            and source_id in context_invocation_ids
        ):
            resolved.append(gap.gap_event_id)
        elif (
            gap.code == TraceGapCode.MISSING_INVOCATION
            and source_id in invocation_by_id
        ):
            resolved.append(gap.gap_event_id)
        elif (
            gap.code == TraceGapCode.MISSING_RESULT
            and source_id in result_invocation_ids
        ):
            resolved.append(gap.gap_event_id)
        elif gap.code == TraceGapCode.MISSING_PARENT_EVENT:
            parent = invocation_by_id.get(source_id)
            if parent is not None and parent.terminal:
                resolved.append(gap.gap_event_id)
    return tuple(sorted(resolved, key=str))


__all__ = [
    "active_trace_supersession_event",
    "latest_trace_status_event",
    "resolvable_gap_event_ids",
    "source_authority_snapshot_sha256",
    "terminal_trace_status_event",
]
