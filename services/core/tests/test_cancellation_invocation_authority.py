from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.cancellation_contracts import (
    CancellationRequesterAuthority,
    TaskCancellationRequest,
)
from simorgh_core.agents.contracts import InvocationState, UsageVector
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationCancellationConflictError,
    InvocationCancellationFencedError,
    InvocationEffect,
    InvocationKind,
    InvocationStore,
)


def _cancellation(
    request_id: UUID,
    *,
    cancellation_id: UUID | None = None,
    reason: str = "operator requested cancellation",
) -> TaskCancellationRequest:
    return TaskCancellationRequest(
        request_id=request_id,
        cancellation_id=cancellation_id or uuid4(),
        requested_at_ms=10,
        reason_code="operator_requested",
        operator_reason=reason,
        requester_authority=CancellationRequesterAuthority.OPERATOR,
        observed_task_phase="routed",
        observed_task_version=1,
    )


def _begin_tool(
    store: InvocationStore,
    *,
    request_id: UUID,
    invocation_id: UUID | None = None,
    effect: InvocationEffect = InvocationEffect.READ_ONLY,
    owner_id: UUID | None = None,
):
    return store.begin(
        invocation_id=invocation_id or uuid4(),
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.fetch-file",
        input_fingerprint="a" * 64,
        kind=InvocationKind.TOOL,
        effect=effect,
        tool_id="github.fetch-file",
        connector_id="github",
        cancellation_owner_id=owner_id,
    ).record


def test_fence_captures_deterministic_owned_invocations_and_owner_identity() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 20)
    request_id = uuid4()
    owner_id = uuid4()
    first = _begin_tool(store, request_id=request_id, owner_id=owner_id)
    second = _begin_tool(store, request_id=request_id)

    fence = store.accept_cancellation(_cancellation(request_id))

    assert [item.invocation_id for item in fence.owned_invocations] == [
        first.invocation_id,
        second.invocation_id,
    ]
    assert fence.owned_invocations[0].cancellation_owner_id == owner_id
    assert store.list_owned(request_id=request_id) == (first, second)


def test_fence_blocks_new_begin_and_existing_reservation() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 20)
    request_id = uuid4()
    pending = _begin_tool(store, request_id=request_id)
    store.accept_cancellation(_cancellation(request_id))

    with pytest.raises(InvocationCancellationFencedError, match="admission"):
        _begin_tool(store, request_id=request_id)
    with pytest.raises(InvocationCancellationFencedError, match="reservation"):
        store.reserve(invocation_id=pending.invocation_id, usage=UsageVector(tool_calls=1))

    settled = store.settle_cancellation(request_id)
    assert settled[0].state == InvocationState.CANCELLED
    assert settled[0].committed_usage == UsageVector()


def test_reserved_read_and_mutation_settle_with_conserved_uncertainty() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 20)
    request_id = uuid4()
    read = _begin_tool(store, request_id=request_id)
    mutation = _begin_tool(
        store,
        request_id=request_id,
        effect=InvocationEffect.MUTATION,
    )
    store.reserve(invocation_id=read.invocation_id, usage=UsageVector(tool_calls=1))
    store.reserve(invocation_id=mutation.invocation_id, usage=UsageVector(tool_calls=1))
    store.accept_cancellation(_cancellation(request_id))

    by_id = {
        record.invocation_id: record
        for record in store.settle_cancellation(request_id)
    }

    assert by_id[read.invocation_id].state == InvocationState.UNKNOWN
    assert by_id[mutation.invocation_id].state == InvocationState.UNKNOWN_SIDE_EFFECT
    assert by_id[read.invocation_id].committed_usage == UsageVector(tool_calls=1)
    assert by_id[mutation.invocation_id].committed_usage == UsageVector(tool_calls=1)


def test_completed_invocation_is_immutable_during_task_cancellation() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 20)
    request_id = uuid4()
    record = _begin_tool(store, request_id=request_id)
    store.reserve(invocation_id=record.invocation_id, usage=UsageVector(tool_calls=1))
    completed = store.complete(
        invocation_id=record.invocation_id,
        result_payload={"ok": True},
        committed_usage=UsageVector(tool_calls=1),
    )
    store.accept_cancellation(_cancellation(request_id))

    settled = store.settle_cancellation(request_id)

    assert settled == (completed,)
    assert settled[0].state == InvocationState.COMPLETED
    assert settled[0].committed_usage == UsageVector(tool_calls=1)


def test_exact_cancellation_replays_and_changed_content_conflicts() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 20)
    request_id = uuid4()
    cancellation_id = uuid4()
    request = _cancellation(request_id, cancellation_id=cancellation_id)

    first = store.accept_cancellation(request)
    replay = store.accept_cancellation(request)

    assert replay == first
    with pytest.raises(InvocationCancellationConflictError, match="different content"):
        store.accept_cancellation(
  _cancellation(
      request_id,
      cancellation_id=cancellation_id,
      reason="changed request content",
  )
        )


def test_cancellation_does_not_cross_task_boundary() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 20)
    cancelled_request = uuid4()
    other_request = uuid4()
    cancelled = _begin_tool(store, request_id=cancelled_request)
    other = _begin_tool(store, request_id=other_request)
    store.accept_cancellation(_cancellation(cancelled_request))

    store.settle_cancellation(cancelled_request)
    reserved_other = store.reserve(
        invocation_id=other.invocation_id,
        usage=UsageVector(tool_calls=1),
    )

    assert store.get(cancelled.invocation_id).state == InvocationState.CANCELLED
    assert reserved_other.state == InvocationState.RESERVED


def test_sqlite_reopen_preserves_fence_and_blocks_future_work(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    request_id = uuid4()
    first = SQLiteInvocationStore(path, wall_clock_millis=lambda: 20)
    pending = _begin_tool(first, request_id=request_id, owner_id=uuid4())
    fence = first.accept_cancellation(_cancellation(request_id))
    first.close()

    reopened = SQLiteInvocationStore(path, wall_clock_millis=lambda: 30)

    assert reopened.get_cancellation_fence(request_id) == fence
    assert reopened.get(pending.invocation_id).state == InvocationState.CANCELLED
    with pytest.raises(InvocationCancellationFencedError):
        _begin_tool(reopened, request_id=request_id)
    reopened.close()


def test_sqlite_fence_exact_replay_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    request_id = uuid4()
    cancellation_id = uuid4()
    request = _cancellation(request_id, cancellation_id=cancellation_id)
    first = SQLiteInvocationStore(path, wall_clock_millis=lambda: 20)
    created = first.accept_cancellation(request)
    first.close()

    reopened = SQLiteInvocationStore(path, wall_clock_millis=lambda: 30)
    replayed = reopened.accept_cancellation(request)

    assert replayed == created
    assert replayed.ownership_snapshot_sha256 == created.ownership_snapshot_sha256
    reopened.close()
