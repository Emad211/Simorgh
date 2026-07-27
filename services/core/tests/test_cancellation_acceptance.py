from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.cancellation_contracts import (
    AdapterCancellationDisposition,
    CancellationRequesterAuthority,
    InvocationCancellationAcknowledgement,
)
from simorgh_core.agents.cancellation_runtime import (
    CancellationOwnerRegistry,
    InvocationCancellationAdapterRegistry,
)
from simorgh_core.agents.contracts import (
    ExecutionMode,
    InvocationState,
    RiskClass,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.control_plane import AgentTaskControlPlane
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationConflictError,
    InvocationEffect,
    InvocationKind,
)
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.task_store import InMemoryAgentTaskStore
from simorgh_core.agents.tracing import InMemoryTraceSink, TraceEventKind


class FakeCancellationAdapter:
    def __init__(
        self,
        disposition: AdapterCancellationDisposition,
        *,
        release: bool = False,
        observed_at_ms: int = 2_700,
    ) -> None:
        self.disposition = disposition
        self.release = release
        self.observed_at_ms = observed_at_ms
        self.calls = 0

    async def cancel(
        self,
        *,
        invocation_id: UUID,
        cancellation_owner_id: UUID | None,
    ) -> InvocationCancellationAcknowledgement:
        self.calls += 1
        await asyncio.sleep(0)
        return InvocationCancellationAcknowledgement(
            invocation_id=invocation_id,
            cancellation_owner_id=cancellation_owner_id,
            disposition=self.disposition,
            acknowledged_at_ms=self.observed_at_ms,
            usage_reservation_released=self.release,
        )


def _task(*, marker: str = "") -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text=f"ریپازیتوری را بررسی کن {marker}",
        requested_outcome="گزارش",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=1,
            max_tool_calls=4,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_estimated_cost_microusd=10_000,
            max_elapsed_ms=30_000,
            max_retries=1,
            max_parallel_branches=1,
        ),
    )


def _control(
    invocation_store,
    adapters: InvocationCancellationAdapterRegistry,
    *,
    trace_sink: InMemoryTraceSink | None = None,
) -> AgentTaskControlPlane:
    return AgentTaskControlPlane(
        router=SpecialistRouter(registry=default_specialist_registry()),
        store=InMemoryAgentTaskStore(),
        invocation_store=invocation_store,
        cancellation_registry=CancellationOwnerRegistry(invocation_store),
        adapter_cancellation_registry=adapters,
        trace_sink=trace_sink,
        wall_clock_millis=lambda: 3_000,
        monotonic_millis=lambda: 100,
    )


def _reserved_tool(store, task: TaskEnvelope, *, effect=InvocationEffect.READ_ONLY):
    owner_id = uuid4()
    record = store.begin(
        invocation_id=uuid4(),
        request_id=task.request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.fetch-file",
        input_fingerprint="d" * 64,
        kind=InvocationKind.TOOL,
        effect=effect,
        tool_id="github.fetch-file",
        connector_id="github",
        cancellation_owner_id=owner_id,
    ).record
    reserved = store.reserve(
        invocation_id=record.invocation_id,
        usage=UsageVector(tool_calls=1),
    )
    return reserved, owner_id


@pytest.mark.asyncio
async def test_proven_non_entry_cancels_reserved_read_and_releases_usage() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(
        store, wall_clock_millis=lambda: 2_700
    )
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(store, task)
    adapter = FakeCancellationAdapter(
        AdapterCancellationDisposition.PROVEN_NOT_ENTERED,
        release=True,
    )
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )

    cancelled = await control.cancel(request_id=task.request_id, reason="لغو")

    final = store.get(reserved.invocation_id)
    assert final.state == InvocationState.CANCELLED
    assert final.committed_usage == UsageVector()
    assert adapter.calls == 1
    assert cancelled.cancellation_result is not None
    assert cancelled.cancellation_result.reserved_cancelled_count == 1
    assert cancelled.cancellation_result.reserved_uncertain_count == 0
    assert (
        cancelled.cancellation_result.outcomes[0].adapter_disposition
        == AdapterCancellationDisposition.PROVEN_NOT_ENTERED
    )


@pytest.mark.asyncio
async def test_adapter_acceptance_without_proof_remains_unknown_and_conserves_usage() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(store, task)
    adapter = FakeCancellationAdapter(AdapterCancellationDisposition.ACCEPTED)
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )

    cancelled = await control.cancel(request_id=task.request_id, reason="لغو")

    final = store.get(reserved.invocation_id)
    assert final.state == InvocationState.UNKNOWN
    assert final.committed_usage == UsageVector(tool_calls=1)
    assert cancelled.cancellation_result is not None
    assert cancelled.cancellation_result.reserved_uncertain_count == 1


@pytest.mark.asyncio
async def test_mutation_remains_unknown_side_effect_even_with_non_entry_ack() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(
        store, task, effect=InvocationEffect.MUTATION
    )
    adapter = FakeCancellationAdapter(
        AdapterCancellationDisposition.PROVEN_NOT_ENTERED,
        release=True,
    )
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )

    cancelled = await control.cancel(request_id=task.request_id, reason="لغو")

    assert store.get(reserved.invocation_id).state == InvocationState.UNKNOWN_SIDE_EFFECT
    assert cancelled.cancellation_result is not None
    assert cancelled.cancellation_result.reserved_uncertain_count == 1


@pytest.mark.asyncio
async def test_simultaneous_identical_cancellation_calls_adapter_once() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(store, task)
    adapter = FakeCancellationAdapter(AdapterCancellationDisposition.ACCEPTED)
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )
    cancellation_id = uuid4()

    first, second = await asyncio.gather(
        control.cancel(
            request_id=task.request_id,
            reason="لغو همزمان",
            cancellation_id=cancellation_id,
        ),
        control.cancel(
            request_id=task.request_id,
            reason="لغو همزمان",
            cancellation_id=cancellation_id,
        ),
    )

    assert first == second
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_adapter_disable_switch_preserves_conservative_settlement() -> None:
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    adapters.disable()
    task = _task()
    control = _control(store, adapters)
    await control.submit(task)
    reserved, owner_id = _reserved_tool(store, task)
    adapter = FakeCancellationAdapter(
        AdapterCancellationDisposition.PROVEN_NOT_ENTERED,
        release=True,
    )
    adapters.register(
        request_id=task.request_id,
        invocation_id=reserved.invocation_id,
        cancellation_owner_id=owner_id,
        adapter=adapter,
    )

    cancelled = await control.cancel(request_id=task.request_id, reason="لغو")

    assert adapter.calls == 0
    assert store.get(reserved.invocation_id).state == InvocationState.UNKNOWN
    assert cancelled.cancellation_result is not None
    assert (
        cancelled.cancellation_result.outcomes[0].adapter_disposition
        == AdapterCancellationDisposition.NOT_SUPPORTED
    )


def test_parent_child_ownership_survives_sqlite_and_cross_task_parent_fails(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path, wall_clock_millis=lambda: 2_500)
    request_id = uuid4()
    parent = store.begin(
        invocation_id=uuid4(),
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="parent",
        input_fingerprint="e" * 64,
        kind=InvocationKind.SPECIALIST,
    ).record
    parent = store.complete(
        invocation_id=parent.invocation_id,
        result_payload={"ok": True},
    )
    child = store.begin(
        invocation_id=uuid4(),
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="child",
        input_fingerprint="f" * 64,
        kind=InvocationKind.SPECIALIST,
        parent_invocation_id=parent.invocation_id,
        attempt=2,
    ).record
    store.close()

    reopened = SQLiteInvocationStore(
        path, wall_clock_millis=lambda: 3_000, recover_interrupted=False
    )
    assert reopened.get(child.invocation_id).parent_invocation_id == parent.invocation_id
    with pytest.raises(InvocationConflictError, match="another task"):
        reopened.begin(
            invocation_id=uuid4(),
            request_id=uuid4(),
            agent_id="github.read",
            agent_version="1.0.0",
            operation="invalid-child",
            input_fingerprint="1" * 64,
            kind=InvocationKind.SPECIALIST,
            parent_invocation_id=parent.invocation_id,
            attempt=2,
        )
    reopened.close()


@pytest.mark.asyncio
async def test_cancellation_trace_excludes_operator_and_task_content() -> None:
    marker = "PRIVATE_CANCEL_MARKER_6ab"
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    adapters = InvocationCancellationAdapterRegistry(store)
    trace = InMemoryTraceSink()
    task = _task(marker=marker)
    control = _control(store, adapters, trace_sink=trace)
    await control.submit(task)

    await control.cancel(
        request_id=task.request_id,
        reason=f"لغو محرمانه {marker}",
        reason_code="operator_requested",
        requester_authority=CancellationRequesterAuthority.OPERATOR,
    )

    events = [
        event
        for event in trace.for_request(task.request_id)
        if event.kind == TraceEventKind.CANCELLATION_SETTLED
    ]
    assert len(events) == 1
    encoded = events[0].model_dump_json()
    assert marker not in encoded
    assert "لغو محرمانه" not in encoded
    assert events[0].reason == "operator_requested"
