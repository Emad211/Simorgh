from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.contracts import InvocationState, RoutingState
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
from simorgh_core.agents.trace_store import TraceClaimKind, TraceStore

_RESOURCE_PATTERN = re.compile(r"[^a-z0-9._:/-]+")
_RESOURCE_START_PATTERN = re.compile(r"^[a-z]")


class ChildTraceProjectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    projected_event_count: int = Field(ge=0)
    replayed_event_count: int = Field(ge=0)

    @property
    def attempted_event_count(self) -> int:
        return self.projected_event_count + self.replayed_event_count


def project_classifier_invocation(
    *,
    store: TraceStore,
    task_entry: AgentTaskStoreEntryV1,
    invocation_records: tuple[InvocationRecord, ...],
    task_claim_event: TraceEventRecord,
    base_ingested_at_ms: int,
) -> ChildTraceProjectionReport:
    """Project the exact durable classifier invocation named by RoutingDecision."""

    decision = task_entry.record.routing_decision
    classifier_id = decision.classifier_invocation_id if decision is not None else None
    if classifier_id is None:
        return _empty_report()
    matches = tuple(
        record
        for record in invocation_records
        if record.invocation_id == classifier_id
        and record.request_id == task_entry.request_id
        and record.kind == InvocationKind.MODEL
    )
    if len(matches) != 1:
        return _empty_report()
    return _project_invocation_chain(
        store=store,
        records=matches,
        root_parent_event=task_claim_event,
        root_parent_invocation_id=None,
        base_ingested_at_ms=base_ingested_at_ms,
    )


def project_routed_root_invocations(
    *,
    store: TraceStore,
    task_entry: AgentTaskStoreEntryV1,
    routing_event: TraceEventRecord,
    invocation_records: tuple[InvocationRecord, ...],
    base_ingested_at_ms: int,
) -> ChildTraceProjectionReport:
    """Project root model/tool calls owned by the exact routed specialist."""

    decision = task_entry.record.routing_decision
    if (
        decision is None
        or decision.state != RoutingState.ROUTED
        or decision.selected_agent_id is None
        or decision.selected_agent_version is None
    ):
        return _empty_report()
    direct = tuple(
        record
        for record in invocation_records
        if record.request_id == task_entry.request_id
        and record.kind in {InvocationKind.MODEL, InvocationKind.TOOL}
        and record.parent_invocation_id is None
        and record.cancellation_owner_id is None
        and record.agent_id == decision.selected_agent_id
        and record.agent_version == decision.selected_agent_version
        and record.invocation_id != decision.classifier_invocation_id
    )
    return _project_invocation_chain(
        store=store,
        records=direct,
        root_parent_event=routing_event,
        root_parent_invocation_id=None,
        base_ingested_at_ms=base_ingested_at_ms,
    )


def project_specialist_owned_child_invocations(
    *,
    store: TraceStore,
    specialist_invocation: InvocationRecord,
    specialist_start_event: TraceEventRecord,
    invocation_records: tuple[InvocationRecord, ...],
    base_ingested_at_ms: int,
) -> ChildTraceProjectionReport:
    """Project model/tool calls owned by exactly one durable specialist owner."""

    owner_id = specialist_invocation.cancellation_owner_id
    if owner_id is None:
        return _empty_report()
    matching_specialists = tuple(
        record
        for record in invocation_records
        if record.request_id == specialist_invocation.request_id
        and record.kind == InvocationKind.SPECIALIST
        and record.cancellation_owner_id == owner_id
    )
    if len(matching_specialists) != 1:
        return _empty_report()
    children = tuple(
        record
        for record in invocation_records
        if record.request_id == specialist_invocation.request_id
        and record.kind in {InvocationKind.MODEL, InvocationKind.TOOL}
        and record.cancellation_owner_id == owner_id
    )
    return _project_invocation_chain(
        store=store,
        records=children,
        root_parent_event=specialist_start_event,
        root_parent_invocation_id=specialist_invocation.invocation_id,
        base_ingested_at_ms=base_ingested_at_ms,
    )


def _project_invocation_chain(
    *,
    store: TraceStore,
    records: tuple[InvocationRecord, ...],
    root_parent_event: TraceEventRecord,
    root_parent_invocation_id: UUID | None,
    base_ingested_at_ms: int,
) -> ChildTraceProjectionReport:
    if base_ingested_at_ms < 0:
        raise ValueError("base ingestion time cannot be negative")
    projected = 0
    replayed = 0
    next_offset = 0
    pending = sorted(
        records,
        key=lambda record: (
            record.attempt,
            record.created_at_ms,
            str(record.invocation_id),
        ),
    )
    terminal_events: dict[UUID, TraceEventRecord] = {}
    while pending:
        progressed = False
        for record in tuple(pending):
            native_parent_id = record.parent_invocation_id
            if native_parent_id is None:
                parent_event = root_parent_event
                trace_parent_id = root_parent_invocation_id
            else:
                candidate_parent = terminal_events.get(native_parent_id)
                if candidate_parent is None:
                    continue
                parent_event = candidate_parent
                trace_parent_id = native_parent_id
            pending.remove(record)
            progressed = True
            start_claim = store.append(
                new_trace_event_candidate(
                    request_id=record.request_id,
                    event_kind=DurableTraceEventKind.INVOCATION_STARTED,
                    stage=_stage_for(record.kind),
                    source_authority_kind=(
                        TraceSourceAuthorityKind.INVOCATION_RECORD
                    ),
                    source_authority_id=record.invocation_id,
                    source_authority_sha256=_invocation_identity_sha256(record),
                    parent_event_id=parent_event.event_id,
                    causation_event_id=parent_event.event_id,
                    invocation_id=record.invocation_id,
                    parent_invocation_id=trace_parent_id,
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
            if not record.terminal:
                continue
            terminal_claim = store.append(
                new_trace_event_candidate(
                    request_id=record.request_id,
                    event_kind=DurableTraceEventKind.INVOCATION_TERMINAL,
                    stage=_stage_for(record.kind),
                    source_authority_kind=(
                        TraceSourceAuthorityKind.INVOCATION_RECORD
                    ),
                    source_authority_id=record.invocation_id,
                    source_authority_sha256=canonical_fingerprint(record),
                    parent_event_id=start_claim.record.event_id,
                    causation_event_id=start_claim.record.event_id,
                    invocation_id=record.invocation_id,
                    parent_invocation_id=trace_parent_id,
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
            terminal_events[record.invocation_id] = terminal_claim.record
        if not progressed:
            break
    return ChildTraceProjectionReport(
        projected_event_count=projected,
        replayed_event_count=replayed,
    )


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


def _empty_report() -> ChildTraceProjectionReport:
    return ChildTraceProjectionReport(
        projected_event_count=0,
        replayed_event_count=0,
    )


__all__ = [
    "ChildTraceProjectionReport",
    "project_classifier_invocation",
    "project_routed_root_invocations",
    "project_specialist_owned_child_invocations",
]
