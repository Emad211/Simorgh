from __future__ import annotations

import threading
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from simorgh_core.agents.contracts import InvocationState
from simorgh_core.agents.invocations import InvocationKind
from simorgh_core.agents.result_authority import strictest_privacy, strictest_retention
from simorgh_core.agents.trace_contracts import (
    MAX_TRACE_EVENTS,
    MAX_TRACE_GAPS,
    DurableTraceEventKind,
    DurableTraceReplayDisposition,
    TraceDisposition,
    TraceEnvelope,
    TraceEventCandidate,
    TraceEventRecord,
    TraceGapDetails,
    TraceGapSummary,
    TraceInvocationDetails,
    TraceResultDetails,
    TraceSupersessionDetails,
    TraceTerminalDetails,
    TraceView,
    trace_envelope_canonical_sha256,
    trace_event_manifest_sha256,
    trace_id_for,
)


class TraceStoreError(RuntimeError):
    """Base class for deterministic durable trace-store failures."""


class TraceConflictError(TraceStoreError):
    pass


class TraceNotFoundError(TraceStoreError):
    pass


class TraceCausalityError(TraceStoreError):
    pass


class TraceTerminalError(TraceStoreError):
    pass


class TraceStoreClosedError(TraceStoreError):
    pass


class TraceLimitError(TraceStoreError):
    pass


class TraceClaimKind(StrEnum):
    NEW = "new"
    REPLAY = "replay"


class TraceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: TraceClaimKind
    record: TraceEventRecord


class TraceStore(Protocol):
    def append(
        self,
        candidate: TraceEventCandidate,
        *,
        ingested_at_ms: int,
    ) -> TraceClaim: ...

    def get_event(self, event_id: UUID) -> TraceEventRecord: ...

    def view(self, request_id: UUID) -> TraceView: ...

    def load(self) -> list[TraceEventRecord]: ...

    def close(self) -> None: ...


class InMemoryTraceStore:
    """Strict process-local authority for immutable causally ordered trace events."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: dict[UUID, TraceEventRecord] = {}
        self._trace_events: dict[UUID, list[UUID]] = {}
        self._closed = False

    def append(
        self,
        candidate: TraceEventCandidate,
        *,
        ingested_at_ms: int,
    ) -> TraceClaim:
        validated = TraceEventCandidate.model_validate(
            candidate.model_dump(mode="json")
        )
        if ingested_at_ms < 0:
            raise ValueError("trace ingestion time cannot be negative")
        with self._lock:
            self._require_open_locked()
            existing = self._events.get(validated.event_id)
            if existing is not None:
                _require_same_event(existing, validated)
                return TraceClaim(kind=TraceClaimKind.REPLAY, record=existing)

            trace_event_ids = self._trace_events.get(validated.trace_id, [])
            trace_events = [self._events[event_id] for event_id in trace_event_ids]
            _require_appendable(trace_events, validated)
            _require_existing_references(self._events, validated)
            _require_replay_semantics(self._events, validated)
            _require_stage_causality(self._events, validated)

            record = TraceEventRecord.model_validate(
                {
                    **validated.model_dump(mode="json"),
                    "sequence": len(trace_events) + 1,
                    "ingested_at_ms": ingested_at_ms,
                }
            )
            self._events[record.event_id] = record
            self._trace_events.setdefault(record.trace_id, []).append(record.event_id)
            return TraceClaim(kind=TraceClaimKind.NEW, record=record)

    def get_event(self, event_id: UUID) -> TraceEventRecord:
        with self._lock:
            self._require_open_locked()
            record = self._events.get(event_id)
            if record is None:
                raise TraceNotFoundError(f"trace event {event_id} does not exist")
            return record

    def view(self, request_id: UUID) -> TraceView:
        trace_id = trace_id_for(request_id)
        with self._lock:
            self._require_open_locked()
            event_ids = self._trace_events.get(trace_id)
            if not event_ids:
                raise TraceNotFoundError(f"request {request_id} has no durable trace")
            events = tuple(self._events[event_id] for event_id in event_ids)
            return _build_trace_view(request_id=request_id, events=events)

    def load(self) -> list[TraceEventRecord]:
        with self._lock:
            self._require_open_locked()
            records: list[TraceEventRecord] = []
            for trace_id in sorted(self._trace_events, key=str):
                records.extend(
                    self._events[event_id]
                    for event_id in self._trace_events[trace_id]
                )
            return records

    def delete_trace(self, request_id: UUID) -> int:
        with self._lock:
            self._require_open_locked()
            trace_id = trace_id_for(request_id)
            event_ids = self._trace_events.pop(trace_id, None)
            if event_ids is None:
                return 0
            for event_id in event_ids:
                self._events.pop(event_id, None)
            return len(event_ids)

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _require_open_locked(self) -> None:
        if self._closed:
            raise TraceStoreClosedError("trace store is closed")


def _require_same_event(
    existing: TraceEventRecord,
    candidate: TraceEventCandidate,
) -> None:
    if existing.canonical_sha256 != candidate.canonical_sha256:
        raise TraceConflictError(
            "changed trace content conflicts with immutable event identity"
        )
    if existing.trace_id != candidate.trace_id or existing.request_id != candidate.request_id:
        raise TraceConflictError("trace event identity was transferred across requests")


def _require_appendable(
    existing: list[TraceEventRecord],
    candidate: TraceEventCandidate,
) -> None:
    if len(existing) >= MAX_TRACE_EVENTS:
        raise TraceLimitError("trace event count exceeds durable trace limit")
    if candidate.event_kind == DurableTraceEventKind.TRACE_GAP:
        gap_count = sum(
            event.event_kind == DurableTraceEventKind.TRACE_GAP
            for event in existing
        )
        if gap_count >= MAX_TRACE_GAPS:
            raise TraceLimitError("trace gap count exceeds durable trace limit")

    if not existing:
        if candidate.event_kind not in {
            DurableTraceEventKind.TASK_CLAIMED,
            DurableTraceEventKind.TRACE_GAP,
        }:
            raise TraceCausalityError(
                "first durable trace event must claim the task or record a gap"
            )
        return

    status_event = _latest_status_event(existing)
    if status_event is None or not _status_event_is_terminal(status_event):
        return
    if candidate.replay == DurableTraceReplayDisposition.REPLAYED:
        return
    if candidate.event_kind in {
        DurableTraceEventKind.TRACE_GAP,
        DurableTraceEventKind.TRACE_SUPERSEDED,
    }:
        return
    raise TraceTerminalError("fresh event cannot extend a terminal durable trace")


def _latest_status_event(
    events: list[TraceEventRecord] | tuple[TraceEventRecord, ...],
) -> TraceEventRecord | None:
    return next(
        (
            event
            for event in reversed(events)
            if event.event_kind
            in {
                DurableTraceEventKind.TRACE_TERMINAL,
                DurableTraceEventKind.TRACE_SUPERSEDED,
                DurableTraceEventKind.TRACE_RESOLVED,
            }
        ),
        None,
    )


def _status_event_is_terminal(event: TraceEventRecord) -> bool:
    if isinstance(event.details, TraceTerminalDetails):
        return True
    if isinstance(event.details, TraceSupersessionDetails):
        return event.details.terminal
    raise TraceCausalityError("trace status event has invalid typed details")


def _require_existing_references(
    events: dict[UUID, TraceEventRecord],
    candidate: TraceEventCandidate,
) -> None:
    for label, reference in (
        ("parent", candidate.parent_event_id),
        ("causation", candidate.causation_event_id),
        ("replay origin", candidate.replay_of_event_id),
    ):
        if reference is None:
            continue
        existing = events.get(reference)
        if existing is None:
            raise TraceCausalityError(f"trace {label} event does not exist")
        if existing.trace_id != candidate.trace_id:
            raise TraceCausalityError(f"trace {label} event belongs to another trace")
        if existing.request_id != candidate.request_id:
            raise TraceCausalityError(f"trace {label} event belongs to another request")


def _require_replay_semantics(
    events: dict[UUID, TraceEventRecord],
    candidate: TraceEventCandidate,
) -> None:
    replay_kinds = {
        DurableTraceEventKind.INVOCATION_REPLAYED,
        DurableTraceEventKind.CONTEXT_REPLAYED,
        DurableTraceEventKind.RESULT_REPLAYED,
        DurableTraceEventKind.CANCELLATION_REPLAYED,
    }
    if candidate.event_kind in replay_kinds:
        if candidate.replay != DurableTraceReplayDisposition.REPLAYED:
            raise TraceCausalityError("replay event kind requires replay disposition")
    elif candidate.replay == DurableTraceReplayDisposition.REPLAYED:
        raise TraceCausalityError("fresh event kind cannot use replay disposition")

    if candidate.replay != DurableTraceReplayDisposition.REPLAYED:
        return
    if candidate.replay_of_event_id is None:
        raise TraceCausalityError("replay event requires original event identity")
    original = events[candidate.replay_of_event_id]
    if original.replay != DurableTraceReplayDisposition.FRESH:
        raise TraceCausalityError("replay origin must be an original fresh event")
    if original.source_authority_kind != candidate.source_authority_kind:
        raise TraceCausalityError("replay source authority kind changed")
    if original.source_authority_id != candidate.source_authority_id:
        raise TraceCausalityError("replay source authority identity changed")
    expected_original_kind = {
        DurableTraceEventKind.INVOCATION_REPLAYED: (
            DurableTraceEventKind.INVOCATION_TERMINAL
        ),
        DurableTraceEventKind.CONTEXT_REPLAYED: DurableTraceEventKind.CONTEXT_COMPILED,
        DurableTraceEventKind.RESULT_REPLAYED: DurableTraceEventKind.RESULT_COMMITTED,
        DurableTraceEventKind.CANCELLATION_REPLAYED: (
            DurableTraceEventKind.CANCELLATION_SETTLED
        ),
    }[candidate.event_kind]
    if original.event_kind != expected_original_kind:
        raise TraceCausalityError("replay origin has the wrong event kind")


def _require_stage_causality(
    events: dict[UUID, TraceEventRecord],
    candidate: TraceEventCandidate,
) -> None:
    parent = (
        events.get(candidate.parent_event_id)
        if candidate.parent_event_id is not None
        else None
    )
    if candidate.event_kind == DurableTraceEventKind.TASK_CLAIMED:
        if parent is not None:
            raise TraceCausalityError("task claim cannot have a parent event")
        return
    if candidate.event_kind == DurableTraceEventKind.TRACE_GAP:
        return
    if parent is None:
        raise TraceCausalityError("durable trace event requires an existing parent")

    if candidate.event_kind == DurableTraceEventKind.ROUTING_DECIDED:
        _require_parent_kind(parent, DurableTraceEventKind.TASK_CLAIMED)
        return
    if candidate.event_kind == DurableTraceEventKind.CONTEXT_COMPILED:
        _require_parent_kind(parent, DurableTraceEventKind.ROUTING_DECIDED)
        return
    if candidate.event_kind == DurableTraceEventKind.INVOCATION_STARTED:
        if not isinstance(candidate.details, TraceInvocationDetails):
            raise TraceCausalityError("invocation start requires invocation details")
        if candidate.details.invocation_kind == InvocationKind.SPECIALIST:
            if candidate.parent_invocation_id is None:
                if parent.event_kind not in {
                    DurableTraceEventKind.CONTEXT_COMPILED,
                    DurableTraceEventKind.CONTEXT_REPLAYED,
                }:
                    raise TraceCausalityError(
                        "specialist invocation must follow context authority"
                    )
            else:
                if (
                    parent.event_kind
                    != DurableTraceEventKind.INVOCATION_TERMINAL
                    or parent.invocation_id != candidate.parent_invocation_id
                ):
                    raise TraceCausalityError(
                        "specialist retry must follow its terminal parent invocation"
                    )
                if candidate.causation_event_id is None:
                    raise TraceCausalityError(
                        "specialist retry requires its own context causation"
                    )
                causation = events.get(candidate.causation_event_id)
                if (
                    causation is None
                    or causation.event_kind
                    not in {
                        DurableTraceEventKind.CONTEXT_COMPILED,
                        DurableTraceEventKind.CONTEXT_REPLAYED,
                    }
                    or causation.invocation_id != candidate.invocation_id
                ):
                    raise TraceCausalityError(
                        "specialist retry requires its own context causation"
                    )
        return
    if candidate.event_kind == DurableTraceEventKind.INVOCATION_TERMINAL:
        _require_parent_kind(parent, DurableTraceEventKind.INVOCATION_STARTED)
        if parent.invocation_id != candidate.invocation_id:
            raise TraceCausalityError("terminal invocation changed invocation identity")
        return
    if candidate.event_kind == DurableTraceEventKind.RESULT_COMMITTED:
        _require_completed_specialist_parent(parent, candidate)
        return
    if candidate.event_kind == DurableTraceEventKind.RESULT_REPLAYED:
        _require_parent_kind(parent, DurableTraceEventKind.RESULT_COMMITTED)
        if parent.result_id != candidate.result_id:
            raise TraceCausalityError("result replay changed result identity")
        return
    if candidate.event_kind in {
        DurableTraceEventKind.INVOCATION_REPLAYED,
        DurableTraceEventKind.CONTEXT_REPLAYED,
        DurableTraceEventKind.CANCELLATION_REPLAYED,
    }:
        if candidate.replay_of_event_id != parent.event_id:
            raise TraceCausalityError("replay parent must be the original event")
        return
    if candidate.event_kind == DurableTraceEventKind.TRACE_SUPERSEDED:
        if not isinstance(candidate.details, TraceSupersessionDetails):
            raise TraceCausalityError(
                "trace superseded event requires supersession details"
            )
        previous = events.get(candidate.details.previous_status_event_id)
        if previous is None or not _status_event_is_terminal(previous):
            raise TraceCausalityError(
                "trace supersession requires previous terminal status"
            )
        if candidate.causation_event_id != previous.event_id:
            raise TraceCausalityError(
                "trace supersession causation must equal previous status"
            )
        _require_resolved_gap_events(events, candidate.details.resolved_gap_event_ids)
        if (
            parent.event_kind == DurableTraceEventKind.TRACE_GAP
            and parent.event_id
            not in candidate.details.resolved_gap_event_ids
        ):
            raise TraceCausalityError(
                "trace supersession gap parent must be explicitly resolved"
            )
        return
    if candidate.event_kind == DurableTraceEventKind.TRACE_RESOLVED:
        if not isinstance(candidate.details, TraceSupersessionDetails):
            raise TraceCausalityError(
                "trace resolved event requires supersession details"
            )
        previous = events.get(candidate.details.previous_status_event_id)
        if (
            previous is None
            or previous.event_kind != DurableTraceEventKind.TRACE_SUPERSEDED
            or _status_event_is_terminal(previous)
        ):
            raise TraceCausalityError(
                "trace resolution requires previous nonterminal supersession"
            )
        if candidate.causation_event_id != previous.event_id:
            raise TraceCausalityError(
                "trace resolution causation must equal superseded status"
            )
        _require_resolved_gap_events(events, candidate.details.resolved_gap_event_ids)
        return
    if candidate.event_kind == DurableTraceEventKind.TRACE_TERMINAL:
        if not isinstance(candidate.details, TraceTerminalDetails):
            raise TraceCausalityError("terminal trace requires terminal details")
        if candidate.details.disposition == TraceDisposition.COMPLETED:
            if parent.event_kind not in {
                DurableTraceEventKind.RESULT_COMMITTED,
                DurableTraceEventKind.RESULT_REPLAYED,
            }:
                raise TraceCausalityError(
                    "completed trace requires authoritative result parent"
                )
            if candidate.result_id != parent.result_id:
                raise TraceCausalityError("terminal trace changed result identity")
        return


def _require_resolved_gap_events(
    events: dict[UUID, TraceEventRecord],
    gap_event_ids: tuple[UUID, ...],
) -> None:
    for gap_event_id in gap_event_ids:
        gap_event = events.get(gap_event_id)
        if gap_event is None or not isinstance(gap_event.details, TraceGapDetails):
            raise TraceCausalityError(
                "trace status can resolve only existing gap events"
            )


def _require_parent_kind(
    parent: TraceEventRecord,
    expected: DurableTraceEventKind,
) -> None:
    if parent.event_kind != expected:
        raise TraceCausalityError(
            f"trace parent must be {expected.value}, not {parent.event_kind.value}"
        )


def _require_completed_specialist_parent(
    parent: TraceEventRecord,
    candidate: TraceEventCandidate,
) -> None:
    _require_parent_kind(parent, DurableTraceEventKind.INVOCATION_TERMINAL)
    details = parent.details
    if not isinstance(details, TraceInvocationDetails):
        raise TraceCausalityError("result parent has no invocation details")
    if details.invocation_kind != InvocationKind.SPECIALIST:
        raise TraceCausalityError("result parent is not a specialist invocation")
    if details.state != InvocationState.COMPLETED:
        raise TraceCausalityError("result parent specialist is not completed")
    if parent.invocation_id != candidate.invocation_id:
        raise TraceCausalityError("result changed specialist invocation identity")
    if not isinstance(candidate.details, TraceResultDetails):
        raise TraceCausalityError("result event requires result details")


def _build_trace_view(
    *,
    request_id: UUID,
    events: tuple[TraceEventRecord, ...],
) -> TraceView:
    gaps = tuple(
        TraceGapSummary(
            gap_event_id=event.event_id,
            code=event.details.gap_code,
            missing_stage=event.details.missing_stage,
            missing_source_kind=event.details.missing_source_kind,
            missing_source_id=event.details.missing_source_id,
        )
        for event in events
        if isinstance(event.details, TraceGapDetails)
    )
    resolved_gap_event_ids = {
        gap_event_id
        for event in events
        if isinstance(event.details, TraceSupersessionDetails)
        for gap_event_id in event.details.resolved_gap_event_ids
    }
    unresolved_gap_event_ids = tuple(
        gap.gap_event_id
        for gap in gaps
        if gap.gap_event_id not in resolved_gap_event_ids
    )
    status_event = _latest_status_event(events)
    if unresolved_gap_event_ids:
        disposition = TraceDisposition.INCOMPLETE_GAP
        terminal = True
    elif status_event is None:
        disposition = TraceDisposition.IN_PROGRESS
        terminal = False
    elif isinstance(status_event.details, TraceTerminalDetails):
        disposition = status_event.details.disposition
        terminal = True
    elif isinstance(status_event.details, TraceSupersessionDetails):
        disposition = status_event.details.disposition
        terminal = status_event.details.terminal
    else:
        raise TraceCausalityError("trace status event has invalid details")

    provisional = TraceEnvelope.model_construct(
        schema_version="1.0",
        trace_id=trace_id_for(request_id),
        request_id=request_id,
        canonical_sha256="0" * 64,
        disposition=disposition,
        terminal=terminal,
        event_count=len(events),
        first_sequence=events[0].sequence,
        last_sequence=events[-1].sequence,
        first_observed_at_ms=min(event.occurred_at_ms for event in events),
        last_observed_at_ms=max(event.occurred_at_ms for event in events),
        last_ingested_at_ms=max(event.ingested_at_ms for event in events),
        event_manifest_sha256=trace_event_manifest_sha256(events),
        privacy=strictest_privacy(event.privacy for event in events),
        retention=strictest_retention(event.retention for event in events),
        gap_count=len(gaps),
        gaps=gaps,
        unresolved_gap_count=len(unresolved_gap_event_ids),
        unresolved_gap_event_ids=unresolved_gap_event_ids,
    )
    envelope = TraceEnvelope.model_validate(
        {
            **provisional.model_dump(mode="json"),
            "canonical_sha256": trace_envelope_canonical_sha256(provisional),
        }
    )
    return TraceView(envelope=envelope, events=events)


__all__ = [
    "InMemoryTraceStore",
    "TraceCausalityError",
    "TraceClaim",
    "TraceClaimKind",
    "TraceConflictError",
    "TraceLimitError",
    "TraceNotFoundError",
    "TraceStore",
    "TraceStoreClosedError",
    "TraceStoreError",
    "TraceTerminalError",
]
