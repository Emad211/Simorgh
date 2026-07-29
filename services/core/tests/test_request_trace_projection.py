from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import simorgh_core.agents.trace_projection as projection_module
from simorgh_core.agents.contracts import InvocationState
from simorgh_core.agents.invocations import InvocationKind
from simorgh_core.agents.trace_projection import (
    NullRequestTraceProjector,
    RequestTraceProjectionError,
    RequestTraceProjectorRegistry,
    StoreBackedRequestTraceProjector,
)
from simorgh_core.agents.trace_reconciliation import TraceReconciliationReport


class _TaskStore:
    def __init__(self, entry: object | None) -> None:
        self.entry = entry
        self.requested: list[UUID] = []

    def get(self, request_id: UUID) -> object | None:
        self.requested.append(request_id)
        return self.entry


class _LoadStore:
    def __init__(self, records: tuple[object, ...]) -> None:
        self.records = records
        self.calls = 0

    def load(self) -> list[object]:
        self.calls += 1
        return list(self.records)


class _TraceStore:
    pass


def test_store_backed_projector_filters_every_authority_by_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = uuid4()
    other_id = uuid4()
    invocation_id = uuid4()
    other_invocation_id = uuid4()
    task_entry = SimpleNamespace(request_id=request_id)
    task_store = _TaskStore(task_entry)
    invocation = SimpleNamespace(
        request_id=request_id,
        invocation_id=invocation_id,
        kind=InvocationKind.SPECIALIST,
        state=InvocationState.COMPLETED,
        terminal=True,
        parent_invocation_id=None,
        attempt=1,
        created_at_ms=1_000,
    )
    invocation_store = _LoadStore(
        (
            invocation,
            SimpleNamespace(
                request_id=other_id,
                invocation_id=other_invocation_id,
                kind=InvocationKind.MODEL,
            ),
        )
    )
    context = SimpleNamespace(
        request_id=request_id,
        specialist_invocation_id=invocation_id,
        context_bundle_id=uuid4(),
    )
    context_store = _LoadStore(
        (
            SimpleNamespace(
                request_id=other_id,
                specialist_invocation_id=other_invocation_id,
                context_bundle_id=uuid4(),
            ),
            context,
        )
    )
    result = SimpleNamespace(
        request_id=request_id,
        invocation_id=invocation_id,
        result_id=uuid4(),
    )
    result_store = _LoadStore(
        (
            result,
            SimpleNamespace(
                request_id=other_id,
                invocation_id=other_invocation_id,
                result_id=uuid4(),
            ),
        )
    )
    trace_store = _TraceStore()
    captured: dict[str, object] = {}
    report = TraceReconciliationReport(
        request_count=1,
        projected_event_count=3,
        replayed_event_count=2,
        gap_event_count=0,
    )

    def reconcile(**kwargs: object) -> TraceReconciliationReport:
        captured.update(kwargs)
        return report

    def project_children(**kwargs: object) -> TraceReconciliationReport:
        del kwargs
        return TraceReconciliationReport(
            request_count=1,
            projected_event_count=0,
            replayed_event_count=0,
            gap_event_count=0,
        )

    monkeypatch.setattr(
        projection_module,
        "reconcile_retained_trace_authority",
        reconcile,
    )
    monkeypatch.setattr(
        projection_module,
        "project_correlated_child_invocations",
        project_children,
    )
    projector = StoreBackedRequestTraceProjector(
        task_store=task_store,  # type: ignore[arg-type]
        invocation_store=invocation_store,  # type: ignore[arg-type]
        context_store=context_store,  # type: ignore[arg-type]
        result_store=result_store,  # type: ignore[arg-type]
        trace_store=trace_store,  # type: ignore[arg-type]
        wall_clock_millis=lambda: 9_000,
    )

    actual = projector.project_request(request_id)

    assert actual == report
    assert task_store.requested == [request_id]
    assert captured["store"] is trace_store
    assert captured["task_entries"] == (task_entry,)
    assert captured["invocation_records"] == (invocation,)
    assert captured["context_bundles"] == (context,)
    assert captured["result_records"] == (result,)
    assert captured["base_ingested_at_ms"] == 9_000


def test_projection_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_marker = "private-provider-body"

    def fail(**kwargs: object) -> TraceReconciliationReport:
        del kwargs
        raise ValueError(private_marker)

    monkeypatch.setattr(
        projection_module,
        "reconcile_retained_trace_authority",
        fail,
    )
    projector = StoreBackedRequestTraceProjector(
        task_store=_TaskStore(None),  # type: ignore[arg-type]
        invocation_store=_LoadStore(()),  # type: ignore[arg-type]
        context_store=_LoadStore(()),  # type: ignore[arg-type]
        result_store=_LoadStore(()),  # type: ignore[arg-type]
        trace_store=_TraceStore(),  # type: ignore[arg-type]
    )

    with pytest.raises(
        RequestTraceProjectionError,
        match="durable request trace projection failed",
    ) as error:
        projector.project_request(uuid4())

    assert private_marker not in str(error.value)


def test_projector_registry_defaults_to_noop_and_resets() -> None:
    registry = RequestTraceProjectorRegistry()
    request_id = uuid4()

    initial = registry.current().project_request(request_id)
    assert initial.request_count == 0

    projector = NullRequestTraceProjector()
    registry.configure(projector)
    assert registry.current() is projector

    registry.reset_to_null()
    assert isinstance(registry.current(), NullRequestTraceProjector)
