from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.contracts import (
    ExecutionMode,
    RiskClass,
    RoutingDecision,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
)
from simorgh_core.agents.control_plane import (
    AgentTaskControlPlane,
    AgentTaskRoutingUnknownError,
    AgentTaskStoreUnavailableError,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.task_store import (
    AgentTaskStoreCorruptionError,
    AgentTaskStoreEntryV1,
    InMemoryAgentTaskStore,
)


def _repository_task(*, request_id: UUID | None = None) -> TaskEnvelope:
    return TaskEnvelope(
        request_id=request_id or uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text="ریپازیتوری GitHub را بررسی کن",
        requested_outcome="گزارش ساختاریافتهٔ وضعیت ریپازیتوری",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=0,
            max_tool_calls=4,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def test_wall_clock_rollback_cannot_reverse_durable_task_chronology() -> None:
    wall_clock_ms = [3_000]
    monotonic_ms = [100]
    store = InMemoryAgentTaskStore()
    task = _repository_task()
    control_plane = AgentTaskControlPlane(
        router=SpecialistRouter(registry=default_specialist_registry()),
        store=store,
        wall_clock_millis=lambda: wall_clock_ms[0],
        monotonic_millis=lambda: monotonic_ms[0],
    )

    routed = asyncio.run(control_plane.submit(task))
    wall_clock_ms[0] = 1_500
    monotonic_ms[0] = 150
    cancelled = asyncio.run(
        control_plane.cancel(
            request_id=task.request_id,
            reason="کاربر مأموریت را لغو کرد",
        )
    )

    assert routed.phase == AgentTaskPhase.ROUTED
    assert cancelled.phase == AgentTaskPhase.CANCELLED
    assert cancelled.updated_at_ms == routed.updated_at_ms
    assert cancelled.updated_at_ms >= cancelled.created_at_ms
    persisted = store.get(task.request_id)
    assert persisted is not None
    assert persisted.record == cancelled


def test_router_failure_during_wall_clock_rollback_still_records_unknown() -> None:
    wall_clock_ms = [5_000]
    store = InMemoryAgentTaskStore()
    task = TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text="این مأموریت عمداً خطای Router ایجاد می‌کند",
        requested_outcome="ثبت fail-closed",
        explicit_task_kind=TaskKind.GENERAL_PLANNING,
        risk_class=RiskClass.PLANNING,
        execution_mode=ExecutionMode.PLAN,
        budget=TaskBudget(max_model_calls=0),
    )
    control_plane = AgentTaskControlPlane(
        router=RollbackFailingRouter(wall_clock_ms),  # type: ignore[arg-type]
        store=store,
        wall_clock_millis=lambda: wall_clock_ms[0],
        monotonic_millis=lambda: 100,
    )

    with pytest.raises(
        AgentTaskRoutingUnknownError,
        match="recorded as unknown",
    ):
        asyncio.run(control_plane.submit(task))

    recovered = asyncio.run(control_plane.get(task.request_id))
    assert recovered.phase == AgentTaskPhase.UNKNOWN
    assert recovered.updated_at_ms == recovered.created_at_ms
    persisted = store.get(task.request_id)
    assert persisted is not None
    assert persisted.record == recovered


def test_coroutine_cancellation_is_recorded_unknown_but_still_propagates() -> None:
    store = InMemoryAgentTaskStore()
    task = _repository_task()
    control_plane = AgentTaskControlPlane(
        router=CancelledRouter(),  # type: ignore[arg-type]
        store=store,
        wall_clock_millis=lambda: 2_000,
        monotonic_millis=lambda: 100,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(control_plane.submit(task))

    recovered = asyncio.run(control_plane.get(task.request_id))
    assert recovered.phase == AgentTaskPhase.UNKNOWN
    assert "coroutine was cancelled" in recovered.detail
    persisted = store.get(task.request_id)
    assert persisted is not None
    assert persisted.record == recovered


def test_durable_write_failure_latches_control_plane_unhealthy() -> None:
    store = ToggleFailingAgentTaskStore()
    task = _repository_task()
    control_plane = AgentTaskControlPlane(
        router=SpecialistRouter(registry=default_specialist_registry()),
        store=store,
        wall_clock_millis=lambda: 2_000,
        monotonic_millis=lambda: 100,
    )
    routed = asyncio.run(control_plane.submit(task))
    assert routed.phase == AgentTaskPhase.ROUTED

    store.fail_upserts = True
    with pytest.raises(
        AgentTaskStoreUnavailableError,
        match="durable agent-task transition failed",
    ):
        asyncio.run(
            control_plane.cancel(
                request_id=task.request_id,
                reason="این لغو عمداً خطای ذخیره‌سازی ایجاد می‌کند",
            )
        )

    for operation in (
        lambda: control_plane.get(task.request_id),
        lambda: control_plane.submit(task),
    ):
        with pytest.raises(
            AgentTaskStoreUnavailableError,
            match="store is unhealthy",
        ):
            asyncio.run(operation())

    persisted = store.delegate.get(task.request_id)
    assert persisted is not None
    assert persisted.record == routed


class RollbackFailingRouter:
    def __init__(self, wall_clock_ms: list[int]) -> None:
        self._wall_clock_ms = wall_clock_ms

    async def route(self, **_kwargs: object) -> RoutingDecision:
        self._wall_clock_ms[0] = 500
        raise RuntimeError("simulated router failure after wall-clock rollback")


class CancelledRouter:
    async def route(self, **_kwargs: object) -> RoutingDecision:
        raise asyncio.CancelledError


class ToggleFailingAgentTaskStore:
    def __init__(self) -> None:
        self.delegate = InMemoryAgentTaskStore()
        self.fail_upserts = False

    def load(self) -> list[AgentTaskStoreEntryV1]:
        return self.delegate.load()

    def get(self, request_id: UUID) -> AgentTaskStoreEntryV1 | None:
        return self.delegate.get(request_id)

    def upsert(self, entry: AgentTaskStoreEntryV1) -> None:
        if self.fail_upserts:
            raise AgentTaskStoreCorruptionError("simulated durable write failure")
        self.delegate.upsert(entry)

    def delete(self, request_id: UUID) -> None:
        self.delegate.delete(request_id)

    def clear(self) -> None:
        self.delegate.clear()

    def close(self) -> None:
        self.delegate.close()
