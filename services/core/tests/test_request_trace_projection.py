from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import simorgh_core.agents.trace_projection as projection_module
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
    task_entry = SimpleNamespace(request_id=request_id)
    task_store = _TaskStore(task_entry)
    invocation_store = _LoadStore(
        (
            SimpleNamespace(request_id=request_id),
            SimpleNamespace(request_id=other_id),
        )
    )
    context_store = _LoadStore(
        (
            SimpleNamespace(request_id=other_id),
            SimpleNamespace(request_id=request_id),
        )
    )
    result_store = _LoadStore(
        (
            SimpleNamespace(request_id=request_id),
            SimpleNamespace(request_id=other_id),
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

    monkeypatch.setattr(
        projection_module,
        "reconcile_retained_trace_authority",
        reconcile,
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
    for key in ("invocation_records", "context_bundles", "result_records"):
        records = captured[key]
        assert isinstance(records, tuple)
        assert len(records) == 1
        assert records[0].request_id == request_id
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
