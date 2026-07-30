from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import simorgh_core.agents.trace_projection as projection_module
from simorgh_core.agents.invocations import InvocationKind, InvocationState
from simorgh_core.agents.trace_projection import StoreBackedRequestTraceProjector
from simorgh_core.agents.trace_reconciliation import TraceReconciliationReport

_TERMINAL_INVOCATION_STATES = frozenset(
    {
        InvocationState.COMPLETED,
        InvocationState.FAILED,
        InvocationState.CANCELLED,
        InvocationState.EXPIRED,
        InvocationState.UNKNOWN,
        InvocationState.UNKNOWN_SIDE_EFFECT,
    }
)


class _TaskStore:
    def __init__(self, request_id: UUID) -> None:
        self._entry = SimpleNamespace(request_id=request_id)

    def get(self, request_id: UUID) -> object | None:
        return self._entry if request_id == self._entry.request_id else None


class _LoadStore:
    def __init__(self, records: tuple[object, ...]) -> None:
        self._records = records

    def load(self) -> list[object]:
        return list(self._records)


class _TraceStore:
    pass


def _invocation(
    *,
    request_id: UUID,
    invocation_id: UUID,
    state: InvocationState,
    kind: InvocationKind = InvocationKind.SPECIALIST,
    parent_invocation_id: UUID | None = None,
    attempt: int = 1,
) -> object:
    return SimpleNamespace(
        request_id=request_id,
        invocation_id=invocation_id,
        kind=kind,
        state=state,
        terminal=state in _TERMINAL_INVOCATION_STATES,
        parent_invocation_id=parent_invocation_id,
        attempt=attempt,
        created_at_ms=1_000 + attempt,
    )


def _context(*, request_id: UUID, invocation_id: UUID) -> object:
    return SimpleNamespace(
        request_id=request_id,
        specialist_invocation_id=invocation_id,
        context_bundle_id=uuid4(),
    )


def _result(*, request_id: UUID, invocation_id: UUID) -> object:
    return SimpleNamespace(
        request_id=request_id,
        invocation_id=invocation_id,
        result_id=uuid4(),
    )


def _capture_projection(
    *,
    monkeypatch: pytest.MonkeyPatch,
    request_id: UUID,
    invocations: tuple[object, ...],
    contexts: tuple[object, ...],
    results: tuple[object, ...],
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def reconcile(**kwargs: object) -> TraceReconciliationReport:
        captured.update(kwargs)
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
    projector = StoreBackedRequestTraceProjector(
        task_store=_TaskStore(request_id),  # type: ignore[arg-type]
        invocation_store=_LoadStore(invocations),  # type: ignore[arg-type]
        context_store=_LoadStore(contexts),  # type: ignore[arg-type]
        result_store=_LoadStore(results),  # type: ignore[arg-type]
        trace_store=_TraceStore(),  # type: ignore[arg-type]
        wall_clock_millis=lambda: 5_000,
    )
    projector.project_request(request_id)
    return captured


def test_live_projection_withholds_context_without_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = uuid4()
    invocation_id = uuid4()

    captured = _capture_projection(
        monkeypatch=monkeypatch,
        request_id=request_id,
        invocations=(),
        contexts=(_context(request_id=request_id, invocation_id=invocation_id),),
        results=(),
    )

    assert captured["invocation_records"] == ()
    assert captured["context_bundles"] == ()
    assert captured["result_records"] == ()


def test_live_projection_withholds_completed_specialist_until_result_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    invocation = _invocation(
        request_id=request_id,
        invocation_id=invocation_id,
        state=InvocationState.COMPLETED,
    )
    context = _context(request_id=request_id, invocation_id=invocation_id)

    captured = _capture_projection(
        monkeypatch=monkeypatch,
        request_id=request_id,
        invocations=(invocation,),
        contexts=(context,),
        results=(),
    )

    assert captured["invocation_records"] == ()
    assert captured["context_bundles"] == ()
    assert captured["result_records"] == ()


def test_live_projection_includes_pending_specialist_after_context_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    invocation = _invocation(
        request_id=request_id,
        invocation_id=invocation_id,
        state=InvocationState.PENDING,
    )
    context = _context(request_id=request_id, invocation_id=invocation_id)

    captured = _capture_projection(
        monkeypatch=monkeypatch,
        request_id=request_id,
        invocations=(invocation,),
        contexts=(context,),
        results=(),
    )

    assert captured["invocation_records"] == (invocation,)
    assert captured["context_bundles"] == (context,)
    assert captured["result_records"] == ()


def test_live_projection_includes_completed_specialist_with_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    invocation = _invocation(
        request_id=request_id,
        invocation_id=invocation_id,
        state=InvocationState.COMPLETED,
    )
    context = _context(request_id=request_id, invocation_id=invocation_id)
    result = _result(request_id=request_id, invocation_id=invocation_id)

    captured = _capture_projection(
        monkeypatch=monkeypatch,
        request_id=request_id,
        invocations=(invocation,),
        contexts=(context,),
        results=(result,),
    )

    assert captured["invocation_records"] == (invocation,)
    assert captured["context_bundles"] == (context,)
    assert captured["result_records"] == (result,)


def test_live_projection_waits_for_retry_parent_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = uuid4()
    parent_id = uuid4()
    retry_id = uuid4()
    parent = _invocation(
        request_id=request_id,
        invocation_id=parent_id,
        state=InvocationState.PENDING,
    )
    retry = _invocation(
        request_id=request_id,
        invocation_id=retry_id,
        state=InvocationState.PENDING,
        parent_invocation_id=parent_id,
        attempt=2,
    )
    parent_context = _context(request_id=request_id, invocation_id=parent_id)
    retry_context = _context(request_id=request_id, invocation_id=retry_id)

    captured = _capture_projection(
        monkeypatch=monkeypatch,
        request_id=request_id,
        invocations=(parent, retry),
        contexts=(parent_context, retry_context),
        results=(),
    )

    assert captured["invocation_records"] == (parent,)
    assert captured["context_bundles"] == (parent_context,)
    assert captured["result_records"] == ()


def test_live_projection_preserves_non_specialist_invocations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = uuid4()
    model = _invocation(
        request_id=request_id,
        invocation_id=uuid4(),
        state=InvocationState.COMPLETED,
        kind=InvocationKind.MODEL,
    )

    captured = _capture_projection(
        monkeypatch=monkeypatch,
        request_id=request_id,
        invocations=(model,),
        contexts=(),
        results=(),
    )

    assert captured["invocation_records"] == (model,)
