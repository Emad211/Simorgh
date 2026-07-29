from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from simorgh_core.agents.context_store import ContextStore
from simorgh_core.agents.invocations import InvocationStore
from simorgh_core.agents.result_store import ResultStore
from simorgh_core.agents.task_store import AgentTaskStore
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
    """Project exactly one request from native durable stores, with zero execution."""

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
            return reconcile_retained_trace_authority(
                store=self._trace_store,
                task_entries=((task_entry,) if task_entry is not None else ()),
                invocation_records=invocation_records,
                context_bundles=context_bundles,
                result_records=result_records,
                base_ingested_at_ms=max(0, int(self._wall_clock_millis())),
            )
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


request_trace_projector_registry = RequestTraceProjectorRegistry()


__all__ = [
    "NullRequestTraceProjector",
    "RequestTraceProjectionError",
    "RequestTraceProjector",
    "RequestTraceProjectorRegistry",
    "StoreBackedRequestTraceProjector",
    "request_trace_projector_registry",
]
