from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from simorgh_core.agents.contracts import (
    InvocationState,
    RoutingState,
)
from simorgh_core.agents.invocations import InvocationRecord
from simorgh_core.agents.sqlite_trace_store import SQLiteTraceStore
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceDisposition,
    TraceEnvelope,
    TraceRoutingDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceTaskDetails,
    TraceTerminalDetails,
    TraceView,
    new_trace_event_candidate,
    trace_id_for,
)
from simorgh_core.agents.trace_retention import (
    RetentionAwareTraceStore,
    protected_trace_request_ids,
    terminal_trace_request_ids_to_prune,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore

_SHA_A = "a" * 64
_SHA_B = "b" * 64


class _StaticProtection:
    def __init__(self, protected: frozenset[UUID] = frozenset()) -> None:
        self._protected = protected

    def protected_request_ids(self) -> frozenset[UUID]:
        return self._protected


class _ChangingProtection:
    def __init__(self, request_id: UUID) -> None:
        self._request_id = request_id
        self._calls = 0

    def protected_request_ids(self) -> frozenset[UUID]:
        self._calls += 1
        if self._calls == 1:
            return frozenset()
        return frozenset({self._request_id})


class _CountingProtection:
    def __init__(self) -> None:
        self.calls = 0

    def protected_request_ids(self) -> frozenset[UUID]:
        self.calls += 1
        return frozenset()


def _view(
    request_id: UUID,
    *,
    terminal: bool,
    last_ingested_at_ms: int,
) -> TraceView:
    envelope = TraceEnvelope.model_construct(
        trace_id=trace_id_for(request_id),
        request_id=request_id,
        terminal=terminal,
        last_ingested_at_ms=last_ingested_at_ms,
        last_sequence=1,
    )
    return TraceView.model_construct(envelope=envelope, events=())


def test_retention_selector_prunes_oldest_terminal_and_protects_authority() -> None:
    oldest = uuid4()
    middle = uuid4()
    newest = uuid4()
    active = uuid4()

    selected = terminal_trace_request_ids_to_prune(
        views=(
            _view(oldest, terminal=True, last_ingested_at_ms=100),
            _view(middle, terminal=True, last_ingested_at_ms=200),
            _view(newest, terminal=True, last_ingested_at_ms=300),
            _view(active, terminal=False, last_ingested_at_ms=50),
        ),
        max_terminal_records=1,
        protected_request_ids=frozenset({middle}),
    )

    assert selected == (oldest,)
    assert middle not in selected
    assert newest not in selected
    assert active not in selected


def test_protection_is_derived_from_nonterminal_task_and_invocation() -> None:
    task_request = uuid4()
    invocation_request = uuid4()
    terminal_request = uuid4()
    task_entry = AgentTaskStoreEntryV1.model_construct(
        request_id=task_request,
        record=AgentTaskRecord.model_construct(
            request_id=task_request,
            phase=AgentTaskPhase.ROUTING,
        ),
    )
    invocation = InvocationRecord.model_construct(
        request_id=invocation_request,
        state=InvocationState.PENDING,
    )
    terminal_invocation = InvocationRecord.model_construct(
        request_id=terminal_request,
        state=InvocationState.COMPLETED,
    )
    stable_task_entry = AgentTaskStoreEntryV1.model_construct(
        request_id=terminal_request,
        record=AgentTaskRecord.model_construct(
            request_id=terminal_request,
            phase=AgentTaskPhase.CANCELLED,
        ),
    )
    routed_request = uuid4()
    routed_task_entry = AgentTaskStoreEntryV1.model_construct(
        request_id=routed_request,
        record=AgentTaskRecord.model_construct(
            request_id=routed_request,
            phase=AgentTaskPhase.ROUTED,
        ),
    )

    protected = protected_trace_request_ids(
        task_entries=(task_entry, stable_task_entry, routed_task_entry),
        invocation_records=(invocation, terminal_invocation),
    )

    assert protected == frozenset({task_request, invocation_request})


def test_current_terminal_claim_is_not_immediately_pruned() -> None:
    request_id = uuid4()
    delegate = InMemoryTraceStore()
    store = RetentionAwareTraceStore(
        delegate,
        protection=_StaticProtection(),
        max_terminal_records=0,
    )
    task = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            details=TraceTaskDetails(
                task_fingerprint=_SHA_A,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=1_000,
        ),
        ingested_at_ms=2_000,
    ).record
    decision_id = uuid4()
    routing = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.ROUTING_DECIDED,
            stage=TraceStage.ROUTING,
            source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            source_authority_id=decision_id,
            source_authority_sha256=_SHA_B,
            parent_event_id=task.event_id,
            details=TraceRoutingDetails(
                routing_fingerprint=_SHA_B,
                state=RoutingState.NEEDS_CLARIFICATION,
            ),
            occurred_at_ms=1_100,
        ),
        ingested_at_ms=2_100,
    ).record
    store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_TERMINAL,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_B,
            parent_event_id=routing.event_id,
            result_id=None,
            details=TraceTerminalDetails(
                disposition=TraceDisposition.NEEDS_CLARIFICATION,
                reason_code="needs_clarification",
            ),
            occurred_at_ms=1_200,
        ),
        ingested_at_ms=2_200,
    )

    assert len(store.load()) == 3
    assert store.prune_terminal() == 1
    assert store.load() == []


def test_retention_rechecks_protection_immediately_before_delete() -> None:
    request_id = uuid4()
    delegate = InMemoryTraceStore()
    store = RetentionAwareTraceStore(
        delegate,
        protection=_StaticProtection(),
        max_terminal_records=0,
    )
    task = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            details=TraceTaskDetails(
                task_fingerprint=_SHA_A,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=1_000,
        ),
        ingested_at_ms=2_000,
    ).record
    decision_id = uuid4()
    routing = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.ROUTING_DECIDED,
            stage=TraceStage.ROUTING,
            source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            source_authority_id=decision_id,
            source_authority_sha256=_SHA_B,
            parent_event_id=task.event_id,
            details=TraceRoutingDetails(
                routing_fingerprint=_SHA_B,
                state=RoutingState.NEEDS_CLARIFICATION,
            ),
            occurred_at_ms=1_100,
        ),
        ingested_at_ms=2_100,
    ).record
    store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_TERMINAL,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            parent_event_id=routing.event_id,
            details=TraceTerminalDetails(
                disposition=TraceDisposition.NEEDS_CLARIFICATION,
                reason_code="needs_clarification",
            ),
            occurred_at_ms=1_200,
        ),
        ingested_at_ms=2_200,
    )
    guarded = RetentionAwareTraceStore(
        delegate,
        protection=_ChangingProtection(request_id),
        max_terminal_records=0,
    )

    assert guarded.prune_terminal() == 0
    assert len(guarded.load()) == 3


def test_nonterminal_appends_do_not_trigger_full_retention_scan() -> None:
    request_id = uuid4()
    protection = _CountingProtection()
    store = RetentionAwareTraceStore(
        InMemoryTraceStore(),
        protection=protection,
        max_terminal_records=10,
    )
    task = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            details=TraceTaskDetails(
                task_fingerprint=_SHA_A,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=1_000,
        ),
        ingested_at_ms=2_000,
    ).record
    decision_id = uuid4()
    routing = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.ROUTING_DECIDED,
            stage=TraceStage.ROUTING,
            source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            source_authority_id=decision_id,
            source_authority_sha256=_SHA_B,
            parent_event_id=task.event_id,
            details=TraceRoutingDetails(
                routing_fingerprint=_SHA_B,
                state=RoutingState.NEEDS_CLARIFICATION,
            ),
            occurred_at_ms=1_100,
        ),
        ingested_at_ms=2_100,
    ).record

    assert protection.calls == 0

    store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_TERMINAL,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            parent_event_id=routing.event_id,
            details=TraceTerminalDetails(
                disposition=TraceDisposition.NEEDS_CLARIFICATION,
                reason_code="needs_clarification",
            ),
            occurred_at_ms=1_200,
        ),
        ingested_at_ms=2_200,
    )

    assert protection.calls == 1


def test_sqlite_retention_prunes_terminal_trace_after_reopen(tmp_path: Path) -> None:
    request_id = uuid4()
    path = tmp_path / "traces.sqlite3"
    delegate = SQLiteTraceStore(path)
    store = RetentionAwareTraceStore(
        delegate,
        protection=_StaticProtection(),
        max_terminal_records=0,
    )
    task = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            details=TraceTaskDetails(
                task_fingerprint=_SHA_A,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=1_000,
        ),
        ingested_at_ms=2_000,
    ).record
    decision_id = uuid4()
    routing = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.ROUTING_DECIDED,
            stage=TraceStage.ROUTING,
            source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            source_authority_id=decision_id,
            source_authority_sha256=_SHA_B,
            parent_event_id=task.event_id,
            details=TraceRoutingDetails(
                routing_fingerprint=_SHA_B,
                state=RoutingState.NEEDS_CLARIFICATION,
            ),
            occurred_at_ms=1_100,
        ),
        ingested_at_ms=2_100,
    ).record
    store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TRACE_TERMINAL,
            stage=TraceStage.TERMINAL,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            parent_event_id=routing.event_id,
            details=TraceTerminalDetails(
                disposition=TraceDisposition.NEEDS_CLARIFICATION,
                reason_code="needs_clarification",
            ),
            occurred_at_ms=1_200,
        ),
        ingested_at_ms=2_200,
    )
    store.close()

    reopened = RetentionAwareTraceStore(
        SQLiteTraceStore(path),
        protection=_StaticProtection(),
        max_terminal_records=0,
    )
    assert len(reopened.load()) == 3
    assert reopened.prune_terminal() == 1
    assert reopened.load() == []
    reopened.close()
