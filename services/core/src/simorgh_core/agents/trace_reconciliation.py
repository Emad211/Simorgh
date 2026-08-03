from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.contracts import InvocationState, RoutingState
from simorgh_core.agents.invocations import (
    InvocationKind,
    InvocationRecord,
    canonical_fingerprint,
)
from simorgh_core.agents.result_authority import (
    AuthoritativeSpecialistResult,
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_cancellation_projection import (
    CancellationTraceProjection,
    project_task_cancellation,
)
from simorgh_core.agents.trace_child_invocations import (
    ChildTraceProjectionReport,
    project_classifier_invocation,
    project_routed_root_invocations,
    project_specialist_owned_child_invocations,
)
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceContextDetails,
    TraceDisposition,
    TraceEventCandidate,
    TraceEventRecord,
    TraceGapCode,
    TraceGapDetails,
    TraceInvocationDetails,
    TraceResultDetails,
    TraceRoutingDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceTaskDetails,
    TraceTerminalDetails,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_store import (
    TraceClaimKind,
    TraceConflictError,
    TraceStore,
    TraceTerminalError,
)

_REASON_PATTERN = re.compile(r"[^a-z0-9._:/-]+")
_RESOURCE_START_PATTERN = re.compile(r"^[a-z]")


class TraceReconciliationError(RuntimeError):
    """Retained durable authorities could not be projected consistently."""


class TraceReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = "1.0"
    request_count: int = Field(ge=0)
    projected_event_count: int = Field(ge=0)
    replayed_event_count: int = Field(ge=0)
    gap_event_count: int = Field(ge=0)


class _ProjectionCounter:
    def __init__(self, *, base_ingested_at_ms: int) -> None:
        if base_ingested_at_ms < 0:
            raise ValueError("base ingestion time cannot be negative")
        self.base_ingested_at_ms = base_ingested_at_ms
        self.next_offset = 0
        self.projected = 0
        self.replayed = 0
        self.gaps = 0

    def ingestion_time(self) -> int:
        value = self.current_ingestion_time()
        self.next_offset += 1
        return value

    def current_ingestion_time(self) -> int:
        return self.base_ingested_at_ms + self.next_offset

    def absorb(self, report: ChildTraceProjectionReport) -> None:
        self.projected += report.projected_event_count
        self.replayed += report.replayed_event_count
        self.next_offset += report.attempted_event_count

    def record(self, *, kind: TraceClaimKind, gap: bool = False) -> None:
        if kind == TraceClaimKind.NEW:
            self.projected += 1
        else:
            self.replayed += 1
        if gap:
            self.gaps += 1


class _ProjectedSpecialist:
    def __init__(
        self,
        *,
        invocation: InvocationRecord,
        start_event: TraceEventRecord,
        terminal_event: TraceEventRecord | None,
        result_event: TraceEventRecord | None,
        result: AuthoritativeSpecialistResult | None,
    ) -> None:
        self.invocation = invocation
        self.start_event = start_event
        self.terminal_event = terminal_event
        self.result_event = result_event
        self.result = result


def reconcile_retained_trace_authority(
    *,
    store: TraceStore,
    task_entries: Iterable[AgentTaskStoreEntryV1],
    invocation_records: Iterable[InvocationRecord],
    context_bundles: Iterable[SpecialistContextBundle],
    result_records: Iterable[AuthoritativeSpecialistResult],
    base_ingested_at_ms: int,
) -> TraceReconciliationReport:
    """Project retained source authority into an idempotent zero-external trace.

    This function never calls a model, specialist, tool, connector, or provider and
    never reserves or commits usage. Trace rows are projections only; source stores
    remain the sole authorities.
    """

    tasks = _unique_tasks(task_entries)
    invocations = _group_invocations(invocation_records)
    contexts = _group_contexts(context_bundles)
    results = _group_results(result_records)
    counter = _ProjectionCounter(base_ingested_at_ms=base_ingested_at_ms)

    for request_id, entry in sorted(
        tasks.items(),
        key=lambda item: (item[1].record.created_at_ms, str(item[0])),
    ):
        try:
            _reconcile_request(
                store=store,
                entry=entry,
                invocations=tuple(
                    sorted(
                        invocations.get(request_id, ()),
                        key=lambda record: (
                            record.attempt,
                            record.created_at_ms,
                            str(record.invocation_id),
                        ),
                    )
                ),
                contexts=tuple(
                    sorted(
                        contexts.get(request_id, ()),
                        key=lambda bundle: (
                            bundle.compiled_at_ms,
                            str(bundle.context_bundle_id),
                        ),
                    )
                ),
                results=tuple(
                    sorted(
                        results.get(request_id, ()),
                        key=lambda result: (
                            result.completed_at_ms,
                            str(result.result_id),
                        ),
                    )
                ),
                counter=counter,
            )
        except TraceTerminalError:
            _append_source_evolution_gap(
                store=store,
                counter=counter,
                entry=entry,
            )

    orphan_request_ids = sorted(
        (set(invocations) | set(contexts) | set(results)) - set(tasks),
        key=str,
    )
    for request_id in orphan_request_ids:
        sources = (
            *invocations.get(request_id, ()),
            *contexts.get(request_id, ()),
            *results.get(request_id, ()),
        )
        _append_orphan_task_gap(
            store=store,
            counter=counter,
            request_id=request_id,
            occurred_at_ms=_earliest_source_time(sources),
        )

    return TraceReconciliationReport(
        request_count=len(tasks) + len(orphan_request_ids),
        projected_event_count=counter.projected,
        replayed_event_count=counter.replayed,
        gap_event_count=counter.gaps,
    )


def _reconcile_request(
    *,
    store: TraceStore,
    entry: AgentTaskStoreEntryV1,
    invocations: tuple[InvocationRecord, ...],
    contexts: tuple[SpecialistContextBundle, ...],
    results: tuple[AuthoritativeSpecialistResult, ...],
    counter: _ProjectionCounter,
) -> None:
    request_id = entry.request_id
    task_claim = _append(
        store,
        counter,
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=entry.task_fingerprint,
            details=TraceTaskDetails(
                task_fingerprint=entry.task_fingerprint,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=entry.record.created_at_ms,
        ),
    )

    decision = entry.record.routing_decision
    if decision is None:
        cancellation = project_task_cancellation(
            store=store,
            task_entry=entry,
            parent_event=task_claim,
            base_ingested_at_ms=counter.current_ingestion_time(),
        )
        if cancellation is not None:
            counter.absorb(cancellation)
            _append_task_terminal(
                store=store,
                counter=counter,
                entry=entry,
                parent_event_id=cancellation.event.event_id,
                disposition=cancellation.disposition,
                reason_code=cancellation.reason_code,
            )
            return
        if (
            entry.record.phase == AgentTaskPhase.CANCELLED
            and entry.record.cancellation_request is not None
        ):
            if store.view(request_id).envelope.terminal:
                _append_source_evolution_gap(
                    store=store,
                    counter=counter,
                    entry=entry,
                )
            return
        if entry.record.phase == AgentTaskPhase.CANCELLED:
            _append_task_terminal(
                store=store,
                counter=counter,
                entry=entry,
                parent_event_id=task_claim.event_id,
                disposition=TraceDisposition.CANCELLED,
                reason_code=AgentTaskPhase.CANCELLED.value,
            )
            return
        if entry.record.phase != AgentTaskPhase.ROUTING:
            _append_gap(
                store=store,
                counter=counter,
                request_id=request_id,
                task_record=entry.record,
                code=TraceGapCode.MISSING_ROUTING,
                missing_stage=TraceStage.ROUTING,
                missing_source_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            )
        return

    classifier_report = project_classifier_invocation(
        store=store,
        task_entry=entry,
        invocation_records=invocations,
        task_claim_event=task_claim,
        base_ingested_at_ms=counter.current_ingestion_time(),
    )
    counter.absorb(classifier_report)

    routing_hash = canonical_fingerprint(decision)
    routing = _append(
        store,
        counter,
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.ROUTING_DECIDED,
            stage=TraceStage.ROUTING,
            source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            source_authority_id=decision.decision_id,
            source_authority_sha256=routing_hash,
            parent_event_id=task_claim.event_id,
            causation_event_id=task_claim.event_id,
            invocation_id=decision.classifier_invocation_id,
            details=TraceRoutingDetails(
                routing_fingerprint=routing_hash,
                state=decision.state,
                method=decision.method,
                selected_agent_id=decision.selected_agent_id,
                selected_agent_version=decision.selected_agent_version,
            ),
            occurred_at_ms=entry.record.updated_at_ms,
        ),
    )

    if decision.state != RoutingState.ROUTED:
        cancellation = project_task_cancellation(
            store=store,
            task_entry=entry,
            parent_event=routing,
            base_ingested_at_ms=counter.current_ingestion_time(),
        )
        if cancellation is not None:
            counter.absorb(cancellation)
            _append_task_terminal(
                store=store,
                counter=counter,
                entry=entry,
                parent_event_id=cancellation.event.event_id,
                disposition=cancellation.disposition,
                reason_code=cancellation.reason_code,
            )
            return
        if (
            entry.record.phase == AgentTaskPhase.CANCELLED
            and entry.record.cancellation_request is not None
        ):
            if store.view(request_id).envelope.terminal:
                _append_source_evolution_gap(
                    store=store,
                    counter=counter,
                    entry=entry,
                )
            return
        if entry.record.phase in {
            AgentTaskPhase.CANCELLED,
            AgentTaskPhase.EXPIRED,
            AgentTaskPhase.UNKNOWN,
        }:
            disposition = _task_disposition(entry.record.phase)
            reason_code = entry.record.phase.value
        else:
            disposition = _routing_disposition(decision.state)
            reason_code = decision.state.value
        _append_task_terminal(
            store=store,
            counter=counter,
            entry=entry,
            parent_event_id=routing.event_id,
            disposition=disposition,
            reason_code=reason_code,
        )
        return

    direct_report = project_routed_root_invocations(
        store=store,
        task_entry=entry,
        routing_event=routing,
        invocation_records=invocations,
        base_ingested_at_ms=counter.current_ingestion_time(),
    )
    counter.absorb(direct_report)

    context_events, contexts_by_invocation = _project_contexts(
        store=store,
        counter=counter,
        request_id=request_id,
        routing_event_id=routing.event_id,
        contexts=contexts,
    )
    results_by_invocation = _unique_results_by_invocation(results)
    specialists = tuple(
        invocation
        for invocation in invocations
        if invocation.kind == InvocationKind.SPECIALIST
    )
    projected = _project_specialists(
        store=store,
        counter=counter,
        entry=entry,
        specialists=specialists,
        all_invocations=invocations,
        context_events=context_events,
        contexts_by_invocation=contexts_by_invocation,
        results_by_invocation=results_by_invocation,
    )

    specialist_ids = {invocation.invocation_id for invocation in specialists}
    all_invocation_ids = {invocation.invocation_id for invocation in invocations}
    for invocation_id in sorted(set(contexts_by_invocation) - all_invocation_ids, key=str):
        _append_gap(
            store=store,
            counter=counter,
            request_id=request_id,
            task_record=entry.record,
            code=TraceGapCode.MISSING_INVOCATION,
            missing_stage=TraceStage.SPECIALIST,
            missing_source_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
            missing_source_id=invocation_id,
        )
    for result in results:
        if result.invocation_id not in specialist_ids:
            _append_gap(
                store=store,
                counter=counter,
                request_id=request_id,
                task_record=entry.record,
                code=TraceGapCode.MISSING_INVOCATION,
                missing_stage=TraceStage.SPECIALIST,
                missing_source_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
                missing_source_id=result.invocation_id,
            )

    cancellation = project_task_cancellation(
        store=store,
        task_entry=entry,
        parent_event=routing,
        base_ingested_at_ms=counter.current_ingestion_time(),
    )
    if cancellation is not None:
        counter.absorb(cancellation)

    _project_request_terminal(
        store=store,
        counter=counter,
        entry=entry,
        routing_event_id=routing.event_id,
        projected=projected,
        specialists=specialists,
        cancellation=cancellation,
    )


def _project_contexts(
    *,
    store: TraceStore,
    counter: _ProjectionCounter,
    request_id: UUID,
    routing_event_id: UUID,
    contexts: tuple[SpecialistContextBundle, ...],
) -> tuple[dict[UUID, UUID], dict[UUID, SpecialistContextBundle]]:
    events: dict[UUID, UUID] = {}
    bundles: dict[UUID, SpecialistContextBundle] = {}
    for bundle in contexts:
        invocation_id = bundle.specialist_invocation_id
        existing = bundles.get(invocation_id)
        if existing is not None and existing != bundle:
            raise TraceReconciliationError(
                "multiple contexts conflict for one specialist invocation"
            )
        claim = _append(
            store,
            counter,
            new_trace_event_candidate(
                request_id=request_id,
                event_kind=DurableTraceEventKind.CONTEXT_COMPILED,
                stage=TraceStage.CONTEXT,
                source_authority_kind=TraceSourceAuthorityKind.CONTEXT_BUNDLE,
                source_authority_id=bundle.context_bundle_id,
                source_authority_sha256=bundle.canonical_sha256,
                parent_event_id=routing_event_id,
                causation_event_id=routing_event_id,
                invocation_id=invocation_id,
                context_bundle_id=bundle.context_bundle_id,
                privacy=bundle.privacy,
                retention=bundle.retention,
                details=TraceContextDetails(
                    context_bundle_id=bundle.context_bundle_id,
                    context_sha256=bundle.canonical_sha256,
                    source_manifest_sha256=bundle.source_manifest_sha256,
                    section_count=bundle.section_count,
                    omission_count=bundle.omission_count,
                ),
                occurred_at_ms=bundle.compiled_at_ms,
            ),
        )
        events[invocation_id] = claim.event_id
        bundles[invocation_id] = bundle
    return events, bundles


def _project_specialists(
    *,
    store: TraceStore,
    counter: _ProjectionCounter,
    entry: AgentTaskStoreEntryV1,
    specialists: tuple[InvocationRecord, ...],
    all_invocations: tuple[InvocationRecord, ...],
    context_events: dict[UUID, UUID],
    contexts_by_invocation: dict[UUID, SpecialistContextBundle],
    results_by_invocation: dict[UUID, AuthoritativeSpecialistResult],
) -> tuple[_ProjectedSpecialist, ...]:
    pending = list(specialists)
    projected: list[_ProjectedSpecialist] = []
    terminal_events: dict[UUID, TraceEventRecord] = {}
    processed_ids: set[UUID] = set()
    specialist_ids = {record.invocation_id for record in specialists}

    while pending:
        progressed = False
        for invocation in tuple(pending):
            parent_invocation_id = invocation.parent_invocation_id
            if (
                parent_invocation_id is not None
                and parent_invocation_id not in specialist_ids
            ):
                pending.remove(invocation)
                processed_ids.add(invocation.invocation_id)
                progressed = True
                _append_gap(
                    store=store,
                    counter=counter,
                    request_id=entry.request_id,
                    task_record=entry.record,
                    code=TraceGapCode.MISSING_INVOCATION,
                    missing_stage=TraceStage.SPECIALIST,
                    missing_source_kind=(
                        TraceSourceAuthorityKind.INVOCATION_RECORD
                    ),
                    missing_source_id=parent_invocation_id,
                )
                continue
            if (
                parent_invocation_id is not None
                and parent_invocation_id not in processed_ids
            ):
                continue
            pending.remove(invocation)
            processed_ids.add(invocation.invocation_id)
            progressed = True
            if (
                parent_invocation_id is not None
                and parent_invocation_id not in terminal_events
            ):
                _append_gap(
                    store=store,
                    counter=counter,
                    request_id=entry.request_id,
                    task_record=entry.record,
                    code=TraceGapCode.MISSING_PARENT_EVENT,
                    missing_stage=TraceStage.SPECIALIST,
                    missing_source_kind=(
                        TraceSourceAuthorityKind.INVOCATION_RECORD
                    ),
                    missing_source_id=parent_invocation_id,
                )
                continue
            context_event_id = context_events.get(invocation.invocation_id)
            if context_event_id is None:
                _append_gap(
                    store=store,
                    counter=counter,
                    request_id=entry.request_id,
                    task_record=entry.record,
                    code=TraceGapCode.MISSING_CONTEXT,
                    missing_stage=TraceStage.CONTEXT,
                    missing_source_kind=TraceSourceAuthorityKind.CONTEXT_BUNDLE,
                    missing_source_id=invocation.invocation_id,
                )
                continue

            start_parent_id = (
                terminal_events[parent_invocation_id].event_id
                if parent_invocation_id is not None
                else context_event_id
            )
            start = _append(
                store,
                counter,
                new_trace_event_candidate(
                    request_id=entry.request_id,
                    event_kind=DurableTraceEventKind.INVOCATION_STARTED,
                    stage=TraceStage.SPECIALIST,
                    source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
                    source_authority_id=invocation.invocation_id,
                    source_authority_sha256=_invocation_identity_sha256(invocation),
                    parent_event_id=start_parent_id,
                    causation_event_id=context_event_id,
                    invocation_id=invocation.invocation_id,
                    parent_invocation_id=parent_invocation_id,
                    details=TraceInvocationDetails(
                        invocation_kind=invocation.kind,
                        effect=invocation.effect,
                        state=InvocationState.PENDING,
                        operation_id=_safe_resource_id(
                            invocation.operation,
                            prefix="operation",
                        ),
                        input_fingerprint=invocation.input_fingerprint,
                        attempt=invocation.attempt,
                    ),
                    occurred_at_ms=invocation.created_at_ms,
                ),
            )
            child_report = project_specialist_owned_child_invocations(
                store=store,
                specialist_invocation=invocation,
                specialist_start_event=start,
                invocation_records=all_invocations,
                base_ingested_at_ms=counter.current_ingestion_time(),
            )
            counter.absorb(child_report)
            terminal_event: TraceEventRecord | None = None
            result_event: TraceEventRecord | None = None
            result: AuthoritativeSpecialistResult | None = None
            if invocation.terminal:
                terminal_event = _append(
                    store,
                    counter,
                    new_trace_event_candidate(
                        request_id=entry.request_id,
                        event_kind=DurableTraceEventKind.INVOCATION_TERMINAL,
                        stage=TraceStage.SPECIALIST,
                        source_authority_kind=(
                            TraceSourceAuthorityKind.INVOCATION_RECORD
                        ),
                        source_authority_id=invocation.invocation_id,
                        source_authority_sha256=canonical_fingerprint(invocation),
                        parent_event_id=start.event_id,
                        causation_event_id=start.event_id,
                        invocation_id=invocation.invocation_id,
                        parent_invocation_id=parent_invocation_id,
                        usage=invocation.committed_usage,
                        details=TraceInvocationDetails(
                            invocation_kind=invocation.kind,
                            effect=invocation.effect,
                            state=invocation.state,
                            operation_id=_safe_resource_id(
                                invocation.operation,
                                prefix="operation",
                            ),
                            input_fingerprint=invocation.input_fingerprint,
                            attempt=invocation.attempt,
                            result_payload_sha256=(
                                invocation.result_payload_sha256
                            ),
                            failure_code=_safe_optional_resource_id(
                                invocation.failure_code,
                                prefix="failure",
                            ),
                        ),
                        occurred_at_ms=invocation.updated_at_ms,
                    ),
                )
                terminal_events[invocation.invocation_id] = terminal_event
                result = results_by_invocation.get(invocation.invocation_id)
                if invocation.state == InvocationState.COMPLETED:
                    if result is None:
                        _append_gap(
                            store=store,
                            counter=counter,
                            request_id=entry.request_id,
                            task_record=entry.record,
                            code=TraceGapCode.MISSING_RESULT,
                            missing_stage=TraceStage.RESULT,
                            missing_source_kind=(
                                TraceSourceAuthorityKind.RESULT_RECORD
                            ),
                            missing_source_id=invocation.invocation_id,
                        )
                    else:
                        result_event = _append_result(
                            store=store,
                            counter=counter,
                            invocation=invocation,
                            context=contexts_by_invocation[
                                invocation.invocation_id
                            ],
                            terminal_event=terminal_event,
                            result=result,
                        )
            projected.append(
                _ProjectedSpecialist(
                    invocation=invocation,
                    start_event=start,
                    terminal_event=terminal_event,
                    result_event=result_event,
                    result=result,
                )
            )
        if not progressed:
            unresolved = ",".join(
                sorted(str(record.invocation_id) for record in pending)
            )
            raise TraceReconciliationError(
                "specialist retry ancestry is missing or cyclic: " + unresolved
            )
    return tuple(projected)


def _append_result(
    *,
    store: TraceStore,
    counter: _ProjectionCounter,
    invocation: InvocationRecord,
    context: SpecialistContextBundle,
    terminal_event: TraceEventRecord,
    result: AuthoritativeSpecialistResult,
) -> TraceEventRecord:
    return _append(
        store,
        counter,
        new_trace_event_candidate(
            request_id=invocation.request_id,
            event_kind=DurableTraceEventKind.RESULT_COMMITTED,
            stage=TraceStage.RESULT,
            source_authority_kind=TraceSourceAuthorityKind.RESULT_RECORD,
            source_authority_id=result.result_id,
            source_authority_sha256=result.canonical_sha256,
            parent_event_id=terminal_event.event_id,
            causation_event_id=terminal_event.event_id,
            invocation_id=invocation.invocation_id,
            context_bundle_id=context.context_bundle_id,
            result_id=result.result_id,
            # Result commit is not another cost-bearing invocation. Usage is
            # recorded once on INVOCATION_TERMINAL and remains zero here.
            privacy=result.privacy,
            retention=result.retention,
            details=TraceResultDetails(
                result_id=result.result_id,
                result_sha256=result.canonical_sha256,
                result_schema_id=result.result_schema_id,
                result_schema_version=result.result_schema_version,
            ),
            occurred_at_ms=result.completed_at_ms,
        ),
    )


def _project_request_terminal(
    *,
    store: TraceStore,
    counter: _ProjectionCounter,
    entry: AgentTaskStoreEntryV1,
    routing_event_id: UUID,
    projected: tuple[_ProjectedSpecialist, ...],
    specialists: tuple[InvocationRecord, ...],
    cancellation: CancellationTraceProjection | None,
) -> None:
    if cancellation is not None:
        _append_task_terminal(
            store=store,
            counter=counter,
            entry=entry,
            parent_event_id=cancellation.event.event_id,
            disposition=cancellation.disposition,
            reason_code=cancellation.reason_code,
        )
        return
    if (
        entry.record.phase == AgentTaskPhase.CANCELLED
        and entry.record.cancellation_request is not None
    ):
        if store.view(entry.request_id).envelope.terminal:
            _append_source_evolution_gap(
                store=store,
                counter=counter,
                entry=entry,
            )
        return
    if not specialists:
        if entry.record.phase in {
            AgentTaskPhase.CANCELLED,
            AgentTaskPhase.EXPIRED,
            AgentTaskPhase.UNKNOWN,
        }:
            _append_task_terminal(
                store=store,
                counter=counter,
                entry=entry,
                parent_event_id=routing_event_id,
                disposition=_task_disposition(entry.record.phase),
                reason_code=entry.record.phase.value,
            )
        return

    final_source = max(
        specialists,
        key=lambda invocation: (
            invocation.attempt,
            invocation.updated_at_ms,
            str(invocation.invocation_id),
        ),
    )
    final = next(
        (
            item
            for item in projected
            if item.invocation.invocation_id == final_source.invocation_id
        ),
        None,
    )
    if final is None or not final.invocation.terminal:
        # A typed source gap may explain why the latest attempt could not be
        # projected. Never let an earlier attempt manufacture request completion.
        return

    if final.result_event is not None and final.result is not None:
        _append_task_terminal(
            store=store,
            counter=counter,
            entry=entry,
            parent_event_id=final.result_event.event_id,
            disposition=TraceDisposition.COMPLETED,
            reason_code="authoritative_result",
            result_id=final.result.result_id,
            privacy=final.result.privacy,
            retention=final.result.retention,
        )
        return

    if final.invocation.state == InvocationState.COMPLETED:
        # A typed MISSING_RESULT gap already records why completion cannot be
        # asserted. Never synthesize a successful request terminal event.
        return
    if final.terminal_event is None:
        raise TraceReconciliationError(
            "terminal invocation has no projected terminal trace event"
        )
    _append_task_terminal(
        store=store,
        counter=counter,
        entry=entry,
        parent_event_id=final.terminal_event.event_id,
        disposition=_invocation_disposition(final.invocation.state),
        reason_code=(
            _safe_optional_resource_id(
                final.invocation.failure_code,
                prefix="failure",
            )
            or final.invocation.state.value
        ),
    )


def _append(
    store: TraceStore,
    counter: _ProjectionCounter,
    candidate: TraceEventCandidate,
) -> TraceEventRecord:
    claim = store.append(
        candidate,
        ingested_at_ms=counter.ingestion_time(),
    )
    counter.record(kind=claim.kind)
    return claim.record


def _append_orphan_task_gap(
    *,
    store: TraceStore,
    counter: _ProjectionCounter,
    request_id: UUID,
    occurred_at_ms: int,
) -> None:
    source_id = uuid5(
        NAMESPACE_URL,
        f"simorgh-trace-reconciliation:{request_id}:missing-task",
    )
    source_hash = canonical_fingerprint(
        {
            "request_id": str(request_id),
            "gap_code": TraceGapCode.MISSING_TASK.value,
            "missing_stage": TraceStage.TASK.value,
            "missing_source_kind": TraceSourceAuthorityKind.TASK_RECORD.value,
        }
    )
    claim = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_GAP,
            stage=TraceStage.TERMINAL,
            source_authority_kind=(
                TraceSourceAuthorityKind.TRACE_RECONCILIATION
            ),
            source_authority_id=source_id,
            source_authority_sha256=source_hash,
            details=TraceGapDetails(
                gap_code=TraceGapCode.MISSING_TASK,
                missing_stage=TraceStage.TASK,
                missing_source_kind=TraceSourceAuthorityKind.TASK_RECORD,
            ),
            occurred_at_ms=occurred_at_ms,
        ),
        ingested_at_ms=counter.ingestion_time(),
    )
    counter.record(kind=claim.kind, gap=True)


def _earliest_source_time(sources: tuple[object, ...]) -> int:
    values: list[int] = []
    for source in sources:
        for field in (
            "created_at_ms",
            "compiled_at_ms",
            "completed_at_ms",
            "updated_at_ms",
        ):
            value = getattr(source, field, None)
            if isinstance(value, int) and value >= 0:
                values.append(value)
                break
    return min(values, default=0)


def _append_gap(
    *,
    store: TraceStore,
    counter: _ProjectionCounter,
    request_id: UUID,
    task_record: AgentTaskRecord,
    code: TraceGapCode,
    missing_stage: TraceStage,
    missing_source_kind: TraceSourceAuthorityKind,
    missing_source_id: UUID | None = None,
) -> None:
    source_id = uuid5(
        NAMESPACE_URL,
        "simorgh-trace-reconciliation:"
        f"{request_id}:{code.value}:{missing_source_kind.value}:"
        f"{missing_source_id or 'none'}",
    )
    source_hash = canonical_fingerprint(
        {
            "request_id": str(request_id),
            "gap_code": code.value,
            "missing_stage": missing_stage.value,
            "missing_source_kind": missing_source_kind.value,
            "missing_source_id": (
                str(missing_source_id) if missing_source_id is not None else None
            ),
        }
    )
    claim = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_GAP,
            stage=TraceStage.TERMINAL,
            source_authority_kind=(
                TraceSourceAuthorityKind.TRACE_RECONCILIATION
            ),
            source_authority_id=source_id,
            source_authority_sha256=source_hash,
            details=TraceGapDetails(
                gap_code=code,
                missing_stage=missing_stage,
                missing_source_kind=missing_source_kind,
                missing_source_id=missing_source_id,
            ),
            occurred_at_ms=task_record.updated_at_ms,
        ),
        ingested_at_ms=counter.ingestion_time(),
    )
    counter.record(kind=claim.kind, gap=True)


def _append_task_terminal(
    *,
    store: TraceStore,
    counter: _ProjectionCounter,
    entry: AgentTaskStoreEntryV1,
    parent_event_id: UUID,
    disposition: TraceDisposition,
    reason_code: str,
    result_id: UUID | None = None,
    privacy: PrivacyClassification = PrivacyClassification.INTERNAL,
    retention: RetentionDisposition = RetentionDisposition.PROJECT,
) -> None:
    try:
        claim = store.append(
            new_trace_event_candidate(
                request_id=entry.request_id,
                event_kind=DurableTraceEventKind.TRACE_TERMINAL,
                stage=TraceStage.TERMINAL,
                source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
                source_authority_id=entry.request_id,
                # The immutable task fingerprint is stable across later
                # budget/detail reconciliation. Parent and typed details bind
                # the terminal source.
                source_authority_sha256=entry.task_fingerprint,
                parent_event_id=parent_event_id,
                causation_event_id=parent_event_id,
                result_id=result_id,
                privacy=privacy,
                retention=retention,
                details=TraceTerminalDetails(
                    disposition=disposition,
                    reason_code=_safe_resource_id(
                        reason_code,
                        prefix="terminal",
                    ),
                ),
                occurred_at_ms=entry.record.updated_at_ms,
            ),
            ingested_at_ms=counter.ingestion_time(),
        )
    except TraceConflictError:
        _append_source_evolution_gap(
            store=store,
            counter=counter,
            entry=entry,
        )
        return
    counter.record(kind=claim.kind)


def _append_source_evolution_gap(
    *,
    store: TraceStore,
    counter: _ProjectionCounter,
    entry: AgentTaskStoreEntryV1,
) -> None:
    """Preserve immutable history when retained authority advances after terminal."""

    _append_gap(
        store=store,
        counter=counter,
        request_id=entry.request_id,
        task_record=entry.record,
        code=TraceGapCode.SOURCE_HASH_MISMATCH,
        missing_stage=TraceStage.TERMINAL,
        missing_source_kind=TraceSourceAuthorityKind.TASK_RECORD,
        missing_source_id=entry.request_id,
    )


def _unique_tasks(
    entries: Iterable[AgentTaskStoreEntryV1],
) -> dict[UUID, AgentTaskStoreEntryV1]:
    unique: dict[UUID, AgentTaskStoreEntryV1] = {}
    for entry in entries:
        existing = unique.get(entry.request_id)
        if existing is not None and existing != entry:
            raise TraceReconciliationError(
                "multiple durable task entries conflict for one request"
            )
        unique[entry.request_id] = entry
    return unique


def _group_invocations(
    records: Iterable[InvocationRecord],
) -> dict[UUID, list[InvocationRecord]]:
    grouped: dict[UUID, list[InvocationRecord]] = {}
    identities: dict[UUID, InvocationRecord] = {}
    for record in records:
        existing = identities.get(record.invocation_id)
        if existing is not None and existing != record:
            raise TraceReconciliationError(
                "multiple invocation records conflict for one invocation identity"
            )
        identities[record.invocation_id] = record
        grouped.setdefault(record.request_id, []).append(record)
    return grouped


def _group_contexts(
    records: Iterable[SpecialistContextBundle],
) -> dict[UUID, list[SpecialistContextBundle]]:
    grouped: dict[UUID, list[SpecialistContextBundle]] = {}
    identities: dict[UUID, SpecialistContextBundle] = {}
    for record in records:
        existing = identities.get(record.context_bundle_id)
        if existing is not None and existing != record:
            raise TraceReconciliationError(
                "multiple context records conflict for one context identity"
            )
        identities[record.context_bundle_id] = record
        grouped.setdefault(record.request_id, []).append(record)
    return grouped


def _group_results(
    records: Iterable[AuthoritativeSpecialistResult],
) -> dict[UUID, list[AuthoritativeSpecialistResult]]:
    grouped: dict[UUID, list[AuthoritativeSpecialistResult]] = {}
    identities: dict[UUID, AuthoritativeSpecialistResult] = {}
    for record in records:
        existing = identities.get(record.result_id)
        if existing is not None and existing != record:
            raise TraceReconciliationError(
                "multiple result records conflict for one result identity"
            )
        identities[record.result_id] = record
        grouped.setdefault(record.request_id, []).append(record)
    return grouped


def _unique_results_by_invocation(
    results: tuple[AuthoritativeSpecialistResult, ...],
) -> dict[UUID, AuthoritativeSpecialistResult]:
    indexed: dict[UUID, AuthoritativeSpecialistResult] = {}
    for result in results:
        existing = indexed.get(result.invocation_id)
        if existing is not None and existing != result:
            raise TraceReconciliationError(
                "multiple authoritative results conflict for one invocation"
            )
        indexed[result.invocation_id] = result
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


def _safe_resource_id(value: str, *, prefix: str) -> str:
    normalized = _REASON_PATTERN.sub("-", value.strip().casefold()).strip("._:/-")
    if not normalized:
        normalized = prefix
    if _RESOURCE_START_PATTERN.match(normalized) is None:
        normalized = f"{prefix}-{normalized}"
    return normalized[:128].rstrip("._:/-") or prefix


def _safe_optional_resource_id(value: str | None, *, prefix: str) -> str | None:
    return None if value is None else _safe_resource_id(value, prefix=prefix)


def _routing_disposition(state: RoutingState) -> TraceDisposition:
    if state == RoutingState.ROUTED:
        raise TraceReconciliationError(
            "routed decision does not have a terminal routing disposition"
        )
    return {
        RoutingState.NEEDS_CLARIFICATION: TraceDisposition.NEEDS_CLARIFICATION,
        RoutingState.NEEDS_ESCALATION: TraceDisposition.NEEDS_ESCALATION,
        RoutingState.BUDGET_EXHAUSTED: TraceDisposition.BUDGET_EXHAUSTED,
        RoutingState.POLICY_BLOCKED: TraceDisposition.POLICY_BLOCKED,
        RoutingState.CONTRACT_INVALID: TraceDisposition.CONTRACT_INVALID,
    }[state]


def _task_disposition(phase: AgentTaskPhase) -> TraceDisposition:
    return {
        AgentTaskPhase.CANCELLED: TraceDisposition.CANCELLED,
        AgentTaskPhase.EXPIRED: TraceDisposition.EXPIRED,
        AgentTaskPhase.UNKNOWN: TraceDisposition.UNKNOWN,
    }[phase]


def _invocation_disposition(state: InvocationState) -> TraceDisposition:
    return {
        InvocationState.FAILED: TraceDisposition.FAILED,
        InvocationState.CANCELLED: TraceDisposition.CANCELLED,
        InvocationState.EXPIRED: TraceDisposition.EXPIRED,
        InvocationState.UNKNOWN: TraceDisposition.UNKNOWN,
        InvocationState.UNKNOWN_SIDE_EFFECT: TraceDisposition.UNKNOWN_SIDE_EFFECT,
    }[state]


__all__ = [
    "TraceReconciliationError",
    "TraceReconciliationReport",
    "reconcile_retained_trace_authority",
]