from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import (
    ExecutionMode,
    ModelPolicy,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    SideEffectPolicy,
    SpecialistDefinition,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import InMemoryInvocationStore, InvocationPhase
from simorgh_core.agents.registry import SpecialistRegistry
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistExecutionCancelledError,
    SpecialistExecutionOutcome,
    SpecialistExecutionPolicyError,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    SpecialistExecutorRegistry,
    SpecialistReplayDisposition,
    StaticProposalSpecialistExecutor,
)
from simorgh_core.agents.specialist_runtime import SpecialistInvocationInProgressError
from simorgh_core.agents.specialist_service import SpecialistExecutionControlPlane
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord

_CONTEXT_FINGERPRINT = "a" * 64


class StaticTaskReader:
    def __init__(self, record: AgentTaskRecord) -> None:
        self.record = record
        self.calls = 0

    async def get(self, request_id: UUID) -> AgentTaskRecord:
        self.calls += 1
        if request_id != self.record.request_id:
            raise KeyError(request_id)
        return self.record


class BlockingProposalExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def agent_id(self) -> str:
        return "development.planner"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    @property
    def output_contract(self) -> str:
        return "simorgh.typed-plan.v1"

    async def execute(
        self,
        *,
        request: SpecialistExecutionRequest,
        cancellation: SpecialistCancellation,
        budget: BudgetAccount,
    ) -> SpecialistExecutionResult:
        del budget
        self.calls += 1
        self.started.set()
        await self.release.wait()
        cancellation.raise_if_cancelled()
        return SpecialistExecutionResult(
            request_id=request.request_id,
            invocation_id=request.invocation_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            effect=request.effect,
            outcome=SpecialistExecutionOutcome.COMPLETED,
            output_contract=request.output_contract,
            payload={"summary": "blocking fixture"},
            committed_usage=UsageVector(),
            started_at_ms=2_000,
            completed_at_ms=3_000,
        )


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="برنامه توسعه سیمرغ را بساز",
        requested_outcome="برنامه توسعه",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
        allowed_data_sources=frozenset({"github"}),
    )


def _record() -> AgentTaskRecord:
    task = _task()
    decision = RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="development.planner",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="explicit route",
    )
    account = BudgetAccount(
        request_id=task.request_id,
        limits=task.budget,
        monotonic_millis=lambda: 100,
    )
    return AgentTaskRecord(
        request_id=task.request_id,
        phase=AgentTaskPhase.ROUTED,
        created_at_ms=1_500,
        updated_at_ms=1_600,
        task=task,
        routing_decision=decision,
        budget=account.snapshot(),
        detail="routed fixture",
    )


def _static_executor() -> StaticProposalSpecialistExecutor:
    definition = default_specialist_registry().get("development.planner")
    return StaticProposalSpecialistExecutor(
        agent_id=definition.agent_id,
        agent_version=definition.version,
        output_contract=definition.output_contract,
        payload={"summary": "پیشنهاد کنترل‌شده", "steps": ["قرارداد", "تست"]},
        wall_clock_millis=lambda: 2_000,
    )


def _service(
    *,
    record: AgentTaskRecord,
    executors: SpecialistExecutorRegistry,
    store: InMemoryInvocationStore,
    policies: SpecialistRegistry | None = None,
) -> SpecialistExecutionControlPlane:
    return SpecialistExecutionControlPlane(
        task_reader=StaticTaskReader(record),
        policy_registry=policies or default_specialist_registry(),
        executor_registry=executors,
        invocation_store=store,
        wall_clock_millis=lambda: 2_000,
        monotonic_millis=lambda: 100,
    )


@pytest.mark.asyncio
async def test_control_plane_executes_with_core_selected_zero_external_capabilities() -> None:
    record = _record()
    invocation_id = uuid4()
    store = InMemoryInvocationStore()
    service = _service(
        record=record,
        executors=SpecialistExecutorRegistry((_static_executor(),)),
        store=store,
    )

    result = await service.execute(
        request_id=record.request_id,
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
    )

    assert result.outcome == SpecialistExecutionOutcome.COMPLETED
    assert result.committed_usage == UsageVector()
    assert service.get_invocation(invocation_id).state == InvocationPhase.COMPLETED


@pytest.mark.asyncio
async def test_control_plane_replays_without_current_executor_registry() -> None:
    record = _record()
    invocation_id = uuid4()
    store = InMemoryInvocationStore()
    first_service = _service(
        record=record,
        executors=SpecialistExecutorRegistry((_static_executor(),)),
        store=store,
    )
    first = await first_service.execute(
        request_id=record.request_id,
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
    )
    replay_service = _service(
        record=record,
        executors=SpecialistExecutorRegistry(),
        store=store,
    )

    replay = await replay_service.execute(
        request_id=record.request_id,
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
    )

    assert first.replay == SpecialistReplayDisposition.FRESH
    assert replay.replay == SpecialistReplayDisposition.REPLAYED
    assert replay.payload == first.payload


@pytest.mark.asyncio
async def test_active_cancellation_reaches_executor_and_durable_invocation() -> None:
    record = _record()
    invocation_id = uuid4()
    executor = BlockingProposalExecutor()
    store = InMemoryInvocationStore()
    service = _service(
        record=record,
        executors=SpecialistExecutorRegistry((executor,)),
        store=store,
    )

    running = asyncio.create_task(
        service.execute(
            request_id=record.request_id,
            invocation_id=invocation_id,
            context_fingerprint=_CONTEXT_FINGERPRINT,
        )
    )
    await executor.started.wait()
    assert service.cancel_active(
        invocation_id=invocation_id,
        reason="لغو کاربر",
    )
    executor.release.set()

    with pytest.raises(SpecialistExecutionCancelledError, match="لغو کاربر"):
        await running

    assert store.get(invocation_id).state == InvocationPhase.CANCELLED
    assert not service.cancel_active(invocation_id=invocation_id, reason="دوباره")


@pytest.mark.asyncio
async def test_duplicate_active_invocation_is_rejected_before_second_executor_entry() -> None:
    record = _record()
    invocation_id = uuid4()
    executor = BlockingProposalExecutor()
    store = InMemoryInvocationStore()
    service = _service(
        record=record,
        executors=SpecialistExecutorRegistry((executor,)),
        store=store,
    )

    first = asyncio.create_task(
        service.execute(
            request_id=record.request_id,
            invocation_id=invocation_id,
            context_fingerprint=_CONTEXT_FINGERPRINT,
        )
    )
    await executor.started.wait()

    with pytest.raises(SpecialistInvocationInProgressError, match="already active"):
        await service.execute(
            request_id=record.request_id,
            invocation_id=invocation_id,
            context_fingerprint=_CONTEXT_FINGERPRINT,
        )

    executor.release.set()
    await first
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_typed_executor_policy_is_not_enabled_by_control_plane() -> None:
    task = TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="عملیات تایپ‌شده موبایل",
        requested_outcome="fixture",
        explicit_task_kind=TaskKind.MOBILE_OPERATION_PLANNING,
        execution_mode=ExecutionMode.EXECUTE_TYPED,
        risk_class="external_mutation",
    )
    definition = SpecialistDefinition(
        agent_id="mobile.executor",
        version="1.0.0",
        display_name="Disabled typed executor fixture",
        task_kinds=frozenset({TaskKind.MOBILE_OPERATION_PLANNING}),
        locale_prefixes=frozenset({"fa"}),
        input_contract="simorgh.task.v1",
        output_contract="simorgh.mobile-result.v1",
        model_policy=ModelPolicy(),
        budget_ceiling=TaskBudget(
            max_model_calls=0,
            max_tool_calls=0,
            max_input_tokens=0,
            max_output_tokens=0,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
        side_effect_policy=SideEffectPolicy.TYPED_EXECUTOR_ONLY,
    )
    decision = RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id=definition.agent_id,
        selected_agent_version=definition.version,
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="typed fixture",
    )
    account = BudgetAccount(
        request_id=task.request_id,
        limits=task.budget,
        monotonic_millis=lambda: 100,
    )
    record = AgentTaskRecord(
        request_id=task.request_id,
        phase=AgentTaskPhase.ROUTED,
        created_at_ms=1_500,
        updated_at_ms=1_600,
        task=task,
        routing_decision=decision,
        budget=account.snapshot(),
        detail="typed fixture",
    )
    store = InMemoryInvocationStore()
    service = _service(
        record=record,
        executors=SpecialistExecutorRegistry(),
        store=store,
        policies=SpecialistRegistry((definition,)),
    )

    with pytest.raises(SpecialistExecutionPolicyError, match="not enabled"):
        await service.execute(
            request_id=record.request_id,
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
        )

    assert store.load() == []
