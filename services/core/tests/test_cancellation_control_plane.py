from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.cancellation_contracts import (
    CancellationRequesterAuthority,
    CancellationSignalDisposition,
)
from simorgh_core.agents.cancellation_runtime import (
    CancellationOwnerRegistry,
    CancellationRegistrationBlockedError,
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
from simorgh_core.agents.control_plane import (
    AgentTaskConflictError,
    AgentTaskControlPlane,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationCancellationFencedError,
    InvocationEffect,
    InvocationKind,
)
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.task_store import (
    InMemoryAgentTaskStore,
    SQLiteAgentTaskStore,
)


class SignalTarget:
    def __init__(self) -> None:
        self.calls = 0
        self.reasons: list[str] = []

    def cancel(self, reason: str) -> None:
        self.calls += 1
        self.reasons.append(reason)


def _task(*, request_id: UUID | None = None, marker: str = "") -> TaskEnvelope:
    return TaskEnvelope(
        request_id=request_id or uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text=f"ریپازیتوری GitHub را بررسی کن {marker}",
        requested_outcome="گزارش ساختاریافته",
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
  max_retries=0,
  max_parallel_branches=1,
        ),
    )


def _control_plane(
    *,
    task_store=None,
    invocation_store=None,
    registry=None,
) -> AgentTaskControlPlane:
    invocations = invocation_store or InMemoryInvocationStore(
        wall_clock_millis=lambda: 2_500
    )
    owners = registry or CancellationOwnerRegistry(invocations)
    return AgentTaskControlPlane(
        router=SpecialistRouter(registry=default_specialist_registry()),
        store=task_store or InMemoryAgentTaskStore(),
        invocation_store=invocations,
        cancellation_registry=owners,
        wall_clock_millis=lambda: 2_000,
        monotonic_millis=lambda: 100,
    )


def _begin_owned(
    store,
    *,
    request_id: UUID,
    kind: InvocationKind,
    effect: InvocationEffect,
    owner_id: UUID | None = None,
):
    kwargs = {}
    usage = UsageVector()
    if kind == InvocationKind.MODEL:
        kwargs = {"provider_id": "fake", "model_id": "fake-model"}
    elif kind == InvocationKind.TOOL:
        kwargs = {"tool_id": "github.fetch-file", "connector_id": "github"}
    record = store.begin(
        invocation_id=uuid4(),
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation=f"test:{kind.value}",
        input_fingerprint=({
            InvocationKind.MODEL: "a",
            InvocationKind.TOOL: "b",
            InvocationKind.SPECIALIST: "c",
        }[kind] * 64),
        kind=kind,
        effect=effect,
        cancellation_owner_id=owner_id,
        **kwargs,
    ).record
    if kind == InvocationKind.MODEL:
        usage = UsageVector(model_calls=1, input_tokens=10, output_tokens=10)
    elif kind == InvocationKind.TOOL:
        usage = UsageVector(tool_calls=1)
    return record, usage


def test_native_cancellation_propagates_across_all_invocation_kinds() -> None:
    task_store = InMemoryAgentTaskStore()
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    owners = CancellationOwnerRegistry(invocation_store)
    control = _control_plane(
        task_store=task_store,
        invocation_store=invocation_store,
        registry=owners,
    )
    task = _task(marker="PRIVATE_TASK_MARKER_7f1")
    routed = asyncio.run(control.submit(task))
    owner_id = uuid4()
    target = SignalTarget()
    specialist, _ = _begin_owned(
        invocation_store,
        request_id=task.request_id,
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.READ_ONLY,
        owner_id=owner_id,
    )
    model, model_usage = _begin_owned(
        invocation_store,
        request_id=task.request_id,
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
    )
    tool, tool_usage = _begin_owned(
        invocation_store,
        request_id=task.request_id,
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
    )
    invocation_store.reserve(invocation_id=model.invocation_id, usage=model_usage)
    invocation_store.reserve(invocation_id=tool.invocation_id, usage=tool_usage)
    owners.register(request_id=task.request_id, owner_id=owner_id, target=target)

    cancelled = asyncio.run(
        control.cancel(
  request_id=task.request_id,
  reason="کاربر لغو کرد",
  requester_authority=CancellationRequesterAuthority.OPERATOR,
        )
    )

    assert routed.phase == AgentTaskPhase.ROUTED
    assert cancelled.phase == AgentTaskPhase.CANCELLED
    assert cancelled.cancellation_request is not None
    assert cancelled.cancellation_result is not None
    assert cancelled.cancellation_result.pending_cancelled_count == 1
    assert cancelled.cancellation_result.reserved_uncertain_count == 2
    assert cancelled.cancellation_result.signalled_count == 1
    assert target.calls == 1
    assert invocation_store.get(specialist.invocation_id).state == InvocationState.CANCELLED
    assert invocation_store.get(model.invocation_id).state == InvocationState.UNKNOWN
    assert invocation_store.get(tool.invocation_id).state == InvocationState.UNKNOWN
    assert invocation_store.get(model.invocation_id).committed_usage == model_usage
    assert invocation_store.get(tool.invocation_id).committed_usage == tool_usage
    assert "PRIVATE_TASK_MARKER_7f1" not in cancelled.cancellation_result.model_dump_json()


def test_identical_cancellation_is_exact_replay_and_changed_identity_conflicts() -> None:
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    control = _control_plane(invocation_store=invocation_store)
    task = _task()
    asyncio.run(control.submit(task))
    cancellation_id = uuid4()

    first = asyncio.run(
        control.cancel(
  request_id=task.request_id,
  reason="لغو ثابت",
  cancellation_id=cancellation_id,
        )
    )
    replay = asyncio.run(
        control.cancel(
  request_id=task.request_id,
  reason="لغو ثابت",
  cancellation_id=cancellation_id,
        )
    )

    assert replay == first
    with pytest.raises(AgentTaskConflictError, match="different content"):
        asyncio.run(
  control.cancel(
      request_id=task.request_id,
      reason="محتوای تغییرکرده",
      cancellation_id=cancellation_id,
  )
        )


def test_late_owner_registration_is_signalled_before_execution() -> None:
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    owners = CancellationOwnerRegistry(invocation_store)
    control = _control_plane(invocation_store=invocation_store, registry=owners)
    task = _task()
    asyncio.run(control.submit(task))
    asyncio.run(control.cancel(request_id=task.request_id, reason="لغو"))
    target = SignalTarget()

    with pytest.raises(CancellationRegistrationBlockedError, match="late owner"):
        owners.register(
  request_id=task.request_id,
  owner_id=uuid4(),
  target=target,
        )

    assert target.calls == 1


def test_duplicate_owner_signal_is_attempted_at_most_once() -> None:
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_500)
    owners = CancellationOwnerRegistry(invocation_store)
    request_id = uuid4()
    owner_id = uuid4()
    target = SignalTarget()
    owners.register(request_id=request_id, owner_id=owner_id, target=target)

    first = owners.signal_request(request_id=request_id, reason="لغو")
    second = owners.signal_request(request_id=request_id, reason="لغو دوباره")

    assert first[owner_id] == CancellationSignalDisposition.SIGNALLED
    assert second[owner_id] == CancellationSignalDisposition.ALREADY_SIGNALLED
    assert target.calls == 1


def test_cancelled_task_and_fence_survive_sqlite_reopen(tmp_path: Path) -> None:
    task_path = tmp_path / "tasks.sqlite3"
    invocation_path = tmp_path / "invocations.sqlite3"
    task_store = SQLiteAgentTaskStore(task_path)
    invocation_store = SQLiteInvocationStore(
        invocation_path, wall_clock_millis=lambda: 2_500
    )
    owners = CancellationOwnerRegistry(invocation_store)
    control = _control_plane(
        task_store=task_store,
        invocation_store=invocation_store,
        registry=owners,
    )
    task = _task()
    asyncio.run(control.submit(task))
    asyncio.run(control.cancel(request_id=task.request_id, reason="لغو پایدار"))
    task_store.close()
    invocation_store.close()

    reopened_tasks = SQLiteAgentTaskStore(task_path)
    reopened_invocations = SQLiteInvocationStore(
        invocation_path, wall_clock_millis=lambda: 3_000
    )
    recovered = _control_plane(
        task_store=reopened_tasks,
        invocation_store=reopened_invocations,
        registry=CancellationOwnerRegistry(reopened_invocations),
    )
    record = asyncio.run(recovered.get(task.request_id))

    assert record.phase == AgentTaskPhase.CANCELLED
    assert record.cancellation_result is not None
    assert reopened_invocations.get_cancellation_fence(task.request_id) is not None
    with pytest.raises(InvocationCancellationFencedError):
        _begin_owned(
  reopened_invocations,
  request_id=task.request_id,
  kind=InvocationKind.SPECIALIST,
  effect=InvocationEffect.READ_ONLY,
        )
    reopened_tasks.close()
    reopened_invocations.close()
