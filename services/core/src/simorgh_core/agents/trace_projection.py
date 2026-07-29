from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.context_store import ContextStore
from simorgh_core.agents.contracts import InvocationState
from simorgh_core.agents.invocations import (
    InvocationKind,
    InvocationRecord,
    InvocationStore,
)
from simorgh_core.agents.result_authority import AuthoritativeSpecialistResult
from simorgh_core.agents.result_store import ResultStore
from simorgh_core.agents.task_store import AgentTaskStore
from simorgh_core.agents.trace_child_invocations import (
    project_correlated_child_invocations,
)
from simorgh_core.agents.trace_reconciliation import (
    TraceReconciliationReport,
    reconcile_retained_trace_authority,
)
from simorgh_core.agents.trace_store import TraceStore


class RequestTraceProjectionError(RuntimeError):
    """One request could not be projected from retained durable authority."""


class RequestTraceProjector(Protocol):
    def project_request(self, request_id: UUID) -> TraceReconciliationReport: ...


class NullRequestTraceProjector:
    """No-op projector used before Core lifespan configures durable authority."""

    def project_request(self, request_id: UUID) -> TraceReconciliationReport:
        del request_id
        return TraceReconciliationReport(
            request_count=0,
            projected_event_count=0,
            replayed_event_count=0,
            gap_event_count=0,
        )


class StoreBackedRequestTraceProjector:
    """Project one live request without converting transient incompleteness to gaps."""

    def __init__(
        self,
        *,
        task_store: AgentTaskStore,
        invocation_store: InvocationStore,
        context_store: ContextStore,
        result_store: ResultStore,
        trace_store: TraceStore,
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        self._task_store = task_store
        self._invocation_store = invocation_store
        self._context_store = context_store
        self._result_store = result_store
        self._trace_store = trace_store
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )

    def project_request(self, request_id: UUID) -> TraceReconciliationReport:
        try:
            task_entry = self._task_store.get(request_id)
            invocation_records = tuple(
                record
                for record in self._invocation_store.load()
                if record.request_id == request_id
            )
            context_bundles = tuple(
                bundle
                for bundle in self._context_store.load()
                if bundle.request_id == request_id
            )
            result_records = tuple(
                result
                for result in self._result_store.load()
                if result.request_id == request_id
            )
            (
                live_invocations,
                live_contexts,
                live_results,
            ) = _live_projection_authorities(
                invocation_records=invocation_records,
                context_bundles=context_bundles,
                result_records=result_records,
            )
            observed_at_ms = max(0, int(self._wall_clock_millis()))
            base_report = reconcile_retained_trace_authority(
                store=self._trace_store,
                task_entries=((task_entry,) if task_entry is not None else ()),
                invocation_records=live_invocations,
                context_bundles=live_contexts,
                result_records=live_results,
                base_ingested_at_ms=observed_at_ms,
            )
            if task_entry is None:
                return base_report
            child_report = project_correlated_child_invocations(
                store=self._trace_store,
                task_entry=task_entry,
                invocation_records=invocation_records,
                base_ingested_at_ms=(
                    observed_at_ms
                    + base_report.projected_event_count
                    + base_report.replayed_event_count
                    + 1
                ),
            )
            return _combine_reports(base_report, child_report)
        except RequestTraceProjectionError:
            raise
        except Exception as exc:
            raise RequestTraceProjectionError(
                "durable request trace projection failed"
            ) from exc


class RequestTraceProjectorRegistry:
    """Process-wide projector pointer configured once per Core lifespan."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._projector: RequestTraceProjector = NullRequestTraceProjector()

    def current(self) -> RequestTraceProjector:
        with self._lock:
            return self._projector

    def configure(self, projector: RequestTraceProjector) -> None:
        with self._lock:
            self._projector = projector

    def reset_to_null(self) -> None:
        self.configure(NullRequestTraceProjector())


def _live_projection_authorities(
    *,
    invocation_records: tuple[InvocationRecord, ...],
    context_bundles: tuple[SpecialistContextBundle, ...],
    result_records: tuple[AuthoritativeSpecialistResult, ...],
) -> tuple[
    tuple[InvocationRecord, ...],
    tuple[SpecialistContextBundle, ...],
    tuple[AuthoritativeSpecialistResult, ...],
]:
    """Return only source sets that form a complete live causal prefix.

    Native stores remain authoritative for every intermediate state. A live projection
    waits rather than emitting immutable missing-context/result/parent gaps while a
    producer is still committing the next authority. Startup reconciliation continues
    to receive the complete retained stores and records genuine durable gaps.
    """

    contexts_by_invocation: dict[UUID, SpecialistContextBundle] = {}
    for bundle in context_bundles:
        existing_context = contexts_by_invocation.get(
            bundle.specialist_invocation_id
        )
        if existing_context is not None and existing_context != bundle:
            raise RequestTraceProjectionError(
                "conflicting live contexts exist for one specialist invocation"
            )
        contexts_by_invocation[bundle.specialist_invocation_id] = bundle

    results_by_invocation: dict[UUID, AuthoritativeSpecialistResult] = {}
    for result in result_records:
        existing_result = results_by_invocation.get(result.invocation_id)
        if existing_result is not None and existing_result != result:
            raise RequestTraceProjectionError(
                "conflicting live results exist for one specialist invocation"
            )
        results_by_invocation[result.invocation_id] = result

    specialists = sorted(
        (
            record
            for record in invocation_records
            if record.kind == InvocationKind.SPECIALIST
        ),
        key=lambda record: (
            record.attempt,
            record.created_at_ms,
            str(record.invocation_id),
        ),
    )
    selected: dict[UUID, InvocationRecord] = {}
    pending = list(specialists)
    while pending:
        progressed = False
        for record in tuple(pending):
            parent_id = record.parent_invocation_id
            if parent_id is not None:
                parent = selected.get(parent_id)
                if parent is None or not parent.terminal:
                    continue
            if record.invocation_id not in contexts_by_invocation:
                continue
            if (
                record.terminal
                and record.state == InvocationState.COMPLETED
                and record.invocation_id not in results_by_invocation
            ):
                continue
            selected[record.invocation_id] = record
            pending.remove(record)
            progressed = True
        if not progressed:
            break

    selected_ids = frozenset(selected)
    live_invocations = tuple(
        record
        for record in invocation_records
        if record.kind != InvocationKind.SPECIALIST
        or record.invocation_id in selected_ids
    )
    live_contexts = tuple(
        contexts_by_invocation[invocation_id]
        for invocation_id in sorted(selected_ids, key=str)
    )
    live_results = tuple(
        results_by_invocation[invocation_id]
        for invocation_id in sorted(selected_ids, key=str)
        if invocation_id in results_by_invocation
    )
    return live_invocations, live_contexts, live_results


def _combine_reports(
    first: TraceReconciliationReport,
    second: TraceReconciliationReport,
) -> TraceReconciliationReport:
    return TraceReconciliationReport(
        request_count=max(first.request_count, second.request_count),
        projected_event_count=(
            first.projected_event_count + second.projected_event_count
        ),
        replayed_event_count=(
            first.replayed_event_count + second.replayed_event_count
        ),
        gap_event_count=first.gap_event_count + second.gap_event_count,
    )


request_trace_projector_registry = RequestTraceProjectorRegistry()


__all__ = [
    "NullRequestTraceProjector",
    "RequestTraceProjectionError",
    "RequestTraceProjector",
    "RequestTraceProjectorRegistry",
    "StoreBackedRequestTraceProjector",
    "request_trace_projector_registry",
]
