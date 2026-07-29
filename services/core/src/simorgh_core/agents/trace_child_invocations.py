from __future__ import annotations

import re
from uuid import UUID

from simorgh_core.agents.contracts import InvocationState
from simorgh_core.agents.invocations import (
    InvocationKind,
    InvocationRecord,
    canonical_fingerprint,
)
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceEventRecord,
    TraceInvocationDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_reconciliation import TraceReconciliationReport
from simorgh_core.agents.trace_store import TraceClaimKind, TraceNotFoundError, TraceStore

_RESOURCE_PATTERN = re.compile(r"[^a-z0-9._:/-]+")
_RESOURCE_START_PATTERN = re.compile(r"^[a-z]")


def project_correlated_child_invocations(
    *,
    store: TraceStore,
    task_entry: AgentTaskStoreEntryV1,
    invocation_records: tuple[InvocationRecord, ...],
    base_ingested_at_ms: int,
) -> TraceReconciliationReport:
    """Project classifier and specialist-owned model/tool invocations.

    Correlation is accepted only from durable identities: the routing decision's exact
    classifier invocation ID or one unique specialist cancellation-owner match. Raw
    arguments, model output, connector payload, result payload, and failure detail are
    never copied into trace authority.
    """

    if base_ingested_at_ms < 0:
        raise ValueError("base ingestion time cannot be negative")
    try:
        view = store.view(task_entry.request_id)
    except TraceNotFoundError:
        return _empty_report()

    task_claim = next(
        (
            event
            for event in view.events
            if event.event_kind == DurableTraceEventKind.TASK_CLAIMED
        ),
        None,
    )
    if task_claim is None:
        return _empty_report()

    start_events = {
        event.invocation_id: event
        for event in view.events
        if event.event_kind == DurableTraceEventKind.INVOCATION_STARTED
        and event.invocation_id is not None
    }
    specialist_by_owner = _specialist_invocations_by_owner(invocation_records)
    decision = task_entry.record.routing_decision
    classifier_id = decision.classifier_invocation_id if decision is not None else None

    projected = 0
    replayed = 0
    next_offset = 0
    children = sorted(
        (
            record
            for record in invocation_records
            if record.kind in {InvocationKind.MODEL, InvocationKind.TOOL}
        ),
        key=lambda record: (
            record.created_at_ms,
            str(record.invocation_id),
        ),
    )
    for record in children:
        parent_event, parent_invocation_id = _resolve_parent_event(
            record=record,
            classifier_id=classifier_id,
            task_claim=task_claim,
            start_events=start_events,
            specialist_by_owner=specialist_by_owner,
        )
        if parent_event is None:
            continue

        start_claim = store.append(
            new_trace_event_candidate(
                request_id=record.request_id,
                event_kind=DurableTraceEventKind.INVOCATION_STARTED,
                stage=_stage_for(record.kind),
                source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
                source_authority_id=record.invocation_id,
                source_authority_sha256=_invocation_identity_sha256(record),
                parent_event_id=parent_event.event_id,
                causation_event_id=parent_event.event_id,
                invocation_id=record.invocation_id,
                parent_invocation_id=parent_invocation_id,
                details=TraceInvocationDetails(
                    invocation_kind=record.kind,
                    effect=record.effect,
                    state=InvocationState.PENDING,
                    operation_id=_safe_resource_id(
                        record.operation,
                        prefix="operation",
                    ),
                    input_fingerprint=record.input_fingerprint,
                    attempt=record.attempt,
                ),
                occurred_at_ms=record.created_at_ms,
            ),
            ingested_at_ms=base_ingested_at_ms + next_offset,
        )
        next_offset += 1
        projected, replayed = _count_claim(
            start_claim.kind,
            projected=projected,
            replayed=replayed,
        )
        start_events[record.invocation_id] = start_claim.record

        if not record.terminal:
            continue
        terminal_claim = store.append(
            new_trace_event_candidate(
                request_id=record.request_id,
                event_kind=DurableTraceEventKind.INVOCATION_TERMINAL,
                stage=_stage_for(record.kind),
                source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
                source_authority_id=record.invocation_id,
                source_authority_sha256=canonical_fingerprint(record),
                parent_event_id=start_claim.record.event_id,
                causation_event_id=start_claim.record.event_id,
                invocation_id=record.invocation_id,
                parent_invocation_id=parent_invocation_id,
                usage=record.committed_usage,
                details=TraceInvocationDetails(
                    invocation_kind=record.kind,
                    effect=record.effect,
                    state=record.state,
                    operation_id=_safe_resource_id(
                        record.operation,
                        prefix="operation",
                    ),
                    input_fingerprint=record.input_fingerprint,
                    attempt=record.attempt,
                    result_payload_sha256=record.result_payload_sha256,
                    failure_code=_safe_optional_resource_id(
                        record.failure_code,
                        prefix="failure",
                    ),
                ),
                occurred_at_ms=record.updated_at_ms,
            ),
            ingested_at_ms=base_ingested_at_ms + next_offset,
        )
        next_offset += 1
        projected, replayed = _count_claim(
            terminal_claim.kind,
            projected=projected,
            replayed=replayed,
        )

    return TraceReconciliationReport(
        request_count=1,
        projected_event_count=projected,
        replayed_event_count=replayed,
        gap_event_count=0,
    )


def _resolve_parent_event(
    *,
    record: InvocationRecord,
    classifier_id: UUID | None,
    task_claim: TraceEventRecord,
    start_events: dict[UUID, TraceEventRecord],
    specialist_by_owner: dict[UUID, InvocationRecord],
) -> tuple[TraceEventRecord | None, UUID | None]:
    if classifier_id == record.invocation_id:
        return task_claim, None
    owner_id = record.cancellation_owner_id
    if owner_id is None:
        return None, None
    specialist = specialist_by_owner.get(owner_id)
    if specialist is None:
        return None, None
    return start_events.get(specialist.invocation_id), specialist.invocation_id


def _specialist_invocations_by_owner(
    records: tuple[InvocationRecord, ...],
) -> dict[UUID, InvocationRecord]:
    indexed: dict[UUID, InvocationRecord] = {}
    ambiguous: set[UUID] = set()
    for record in records:
        owner_id = record.cancellation_owner_id
        if record.kind != InvocationKind.SPECIALIST or owner_id is None:
            continue
        existing = indexed.get(owner_id)
        if existing is not None and existing.invocation_id != record.invocation_id:
            ambiguous.add(owner_id)
            continue
        indexed[owner_id] = record
    for owner_id in ambiguous:
        indexed.pop(owner_id, None)
    return indexed


def _invocation_identity_sha256(record: InvocationRecord) -> str:
    return canonical_fingerprint(
        {
            "schema_version": record.schema_version,
            "invocation_id": str(record.invocation_id),
            "request_id": str(record.request_id),
            "agent_id": record.agent_id,
            "agent_version": record.agent_version,
            "operation": record.operation,
            "input_fingerprint": record.input_fingerprint,
            "kind": record.kind.value,
            "effect": record.effect.value,
            "provider_id": record.provider_id,
            "model_id": record.model_id,
            "tool_id": record.tool_id,
            "connector_id": record.connector_id,
            "parent_invocation_id": (
                str(record.parent_invocation_id)
                if record.parent_invocation_id is not None
                else None
            ),
            "cancellation_owner_id": (
                str(record.cancellation_owner_id)
                if record.cancellation_owner_id is not None
                else None
            ),
            "attempt": record.attempt,
            "created_at_ms": record.created_at_ms,
        }
    )


def _stage_for(kind: InvocationKind) -> TraceStage:
    if kind == InvocationKind.MODEL:
        return TraceStage.MODEL
    if kind == InvocationKind.TOOL:
        return TraceStage.TOOL
    raise ValueError("child trace projection requires model or tool invocation")


def _safe_resource_id(value: str, *, prefix: str) -> str:
    normalized = _RESOURCE_PATTERN.sub("-", value.strip().casefold()).strip("._:/-")
    if not normalized:
        normalized = prefix
    if _RESOURCE_START_PATTERN.match(normalized) is None:
        normalized = f"{prefix}-{normalized}"
    return normalized[:128].rstrip("._:/-") or prefix


def _safe_optional_resource_id(value: str | None, *, prefix: str) -> str | None:
    return None if value is None else _safe_resource_id(value, prefix=prefix)


def _count_claim(
    kind: TraceClaimKind,
    *,
    projected: int,
    replayed: int,
) -> tuple[int, int]:
    if kind == TraceClaimKind.NEW:
        return projected + 1, replayed
    return projected, replayed + 1


def _empty_report() -> TraceReconciliationReport:
    return TraceReconciliationReport(
        request_count=0,
        projected_event_count=0,
        replayed_event_count=0,
        gap_event_count=0,
    )


__all__ = ["project_correlated_child_invocations"]
