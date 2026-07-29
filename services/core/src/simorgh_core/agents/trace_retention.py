from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from simorgh_core.agents.invocations import InvocationRecord, InvocationStore
from simorgh_core.agents.task_store import AgentTaskStore, AgentTaskStoreEntryV1
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceEventCandidate,
    TraceEventRecord,
    TraceView,
)
from simorgh_core.agents.trace_store import (
    TraceClaim,
    TraceClaimKind,
    TraceNotFoundError,
    TraceStore,
)

DEFAULT_MAX_TERMINAL_TRACE_RECORDS = 10_000


class TraceRetentionError(RuntimeError):
    """Bounded trace retention could not be applied safely."""


class MutableTraceStore(TraceStore, Protocol):
    def delete_trace(self, request_id: UUID) -> int: ...


class TraceProtectionAuthority(Protocol):
    def protected_request_ids(self) -> frozenset[UUID]: ...


class StoreBackedTraceProtection:
    """Derive retention protection only from durable task/invocation authority."""

    def __init__(
        self,
        *,
        task_store: AgentTaskStore,
        invocation_store: InvocationStore,
    ) -> None:
        self._task_store = task_store
        self._invocation_store = invocation_store

    def protected_request_ids(self) -> frozenset[UUID]:
        return protected_trace_request_ids(
            task_entries=self._task_store.load(),
            invocation_records=self._invocation_store.load(),
        )


def protected_trace_request_ids(
    *,
    task_entries: Iterable[AgentTaskStoreEntryV1],
    invocation_records: Iterable[InvocationRecord],
) -> frozenset[UUID]:
    """Protect every request with nonterminal task or invocation authority."""

    protected = {
        entry.request_id
        for entry in task_entries
        if not entry.record.terminal
    }
    protected.update(
        record.request_id
        for record in invocation_records
        if not record.terminal
    )
    return frozenset(protected)


def terminal_trace_request_ids_to_prune(
    *,
    views: Iterable[TraceView],
    max_terminal_records: int,
    protected_request_ids: frozenset[UUID] = frozenset(),
) -> tuple[UUID, ...]:
    """Select oldest unprotected terminal traces beyond the configured ceiling."""

    if max_terminal_records < 0:
        raise ValueError("max_terminal_records cannot be negative")

    unique: dict[UUID, TraceView] = {}
    for view in views:
        request_id = view.envelope.request_id
        existing = unique.get(request_id)
        if existing is not None and existing != view:
            raise TraceRetentionError(
                "multiple trace views conflict for one request identity"
            )
        unique[request_id] = view

    terminal = sorted(
        (
            view
            for request_id, view in unique.items()
            if view.envelope.terminal
            and request_id not in protected_request_ids
        ),
        key=lambda view: (
            view.envelope.last_ingested_at_ms,
            view.envelope.last_sequence,
            str(view.envelope.trace_id),
        ),
        reverse=True,
    )
    retained = {
        view.envelope.request_id
        for view in terminal[:max_terminal_records]
    }
    return tuple(
        view.envelope.request_id
        for view in reversed(terminal)
        if view.envelope.request_id not in retained
    )


class RetentionAwareTraceStore:
    """Trace-store wrapper that prunes only proven terminal, unprotected traces."""

    def __init__(
        self,
        store: MutableTraceStore,
        *,
        protection: TraceProtectionAuthority,
        max_terminal_records: int = DEFAULT_MAX_TERMINAL_TRACE_RECORDS,
    ) -> None:
        if max_terminal_records < 0:
            raise ValueError("max_terminal_records cannot be negative")
        self._store = store
        self._protection = protection
        self._max_terminal_records = max_terminal_records

    def append(
        self,
        candidate: TraceEventCandidate,
        *,
        ingested_at_ms: int,
    ) -> TraceClaim:
        claim = self._store.append(candidate, ingested_at_ms=ingested_at_ms)
        if (
            claim.kind == TraceClaimKind.NEW
            and candidate.event_kind
            in {
                DurableTraceEventKind.TRACE_GAP,
                DurableTraceEventKind.TRACE_TERMINAL,
            }
        ):
            self.prune_terminal(
                additionally_protected=frozenset({claim.record.request_id})
            )
        return claim

    def get_event(self, event_id: UUID) -> TraceEventRecord:
        return self._store.get_event(event_id)

    def view(self, request_id: UUID) -> TraceView:
        return self._store.view(request_id)

    def load(self) -> list[TraceEventRecord]:
        return self._store.load()

    def prune_terminal(
        self,
        *,
        additionally_protected: frozenset[UUID] = frozenset(),
    ) -> int:
        records = self._store.load()
        request_ids = _request_ids(records)
        views = tuple(self._store.view(request_id) for request_id in request_ids)
        protected = self._protection.protected_request_ids().union(
            additionally_protected
        )
        selected = terminal_trace_request_ids_to_prune(
            views=views,
            max_terminal_records=self._max_terminal_records,
            protected_request_ids=protected,
        )
        deleted_traces = 0
        for request_id in selected:
            current_protected = self._protection.protected_request_ids().union(
                additionally_protected
            )
            if request_id in current_protected:
                continue
            try:
                current_view = self._store.view(request_id)
            except TraceNotFoundError:
                continue
            if not current_view.envelope.terminal:
                continue
            if self._store.delete_trace(request_id) > 0:
                deleted_traces += 1
        return deleted_traces

    def close(self) -> None:
        self._store.close()


def _request_ids(records: Iterable[TraceEventRecord]) -> tuple[UUID, ...]:
    return tuple(
        sorted({record.request_id for record in records}, key=str)
    )


__all__ = [
    "DEFAULT_MAX_TERMINAL_TRACE_RECORDS",
    "MutableTraceStore",
    "RetentionAwareTraceStore",
    "StoreBackedTraceProtection",
    "TraceProtectionAuthority",
    "TraceRetentionError",
    "protected_trace_request_ids",
    "terminal_trace_request_ids_to_prune",
]