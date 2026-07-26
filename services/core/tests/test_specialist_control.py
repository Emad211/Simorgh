from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    TaskEnvelope,
    TaskKind,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import InMemoryInvocationStore
from simorgh_core.agents.specialist_control import (
    SpecialistTaskExecutionAdapter,
    SpecialistTaskNotExecutableError,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistCapabilitySet,
    SpecialistExecutionPolicyError,
    SpecialistExecutorRegistry,
    SpecialistReplayDisposition,
    StaticProposalSpecialistExecutor,
)
from simorgh_core.agents.specialist_runtime import SpecialistExecutionRuntime
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord

_CONTEXT_FINGERPRINT = "f" * 64


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="برای نسخه بعدی سیمرغ برنامه توسعه بساز",
        requested_outcome="برنامه توسعه تایپ‌شده",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
        allowed_data_sources=frozenset({"github"}),
    )


def _decision(task: TaskEnvelope, *, version: str = "1.0.0") -> RoutingDecision:
    return RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="development.planner",
        selected_agent_version=version,
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="explicit development route",
    )


def _routed_record(task: TaskEnvelope, *, version: str = "1.0.0") -> AgentTaskRecord:
    definition = default_specialist_registry().get("development.planner")
    limits = definition.budget_ceiling.model_copy(
        update={
            "max_model_calls": 0,
            "max_tool_calls": 0,
            "max_estimated_cost_microusd": 0,
            "max_elapsed_ms": 30_000,
        }
    )
    account = BudgetAccount(
        request_id=task.request_id,
        limits=limits,
        monotonic_millis=lambda: 100,
    )
    return AgentTaskRecord(
        request_id=task.request_id,
        phase=AgentTaskPhase.ROUTED,
        created_at_ms=1_500,
        updated_at_ms=1_600,
        task=task,
        routing_decision=_decision(task, version=version),
        budget=account.snapshot(),
        detail="routed fixture",
    )


def _adapter() -> tuple[SpecialistTaskExecutionAdapter, InMemoryInvocationStore]:
    definition = default_specialist_registry().get("development.planner")
    executor = StaticProposalSpecialistExecutor(
        agent_id=definition.agent_id,
        agent_version=definition.version,
        output_contract=definition.output_contract,
        payload={"summary": "پیشنهاد محلی", "steps": ["قرارداد", "تست"]},
        wall_clock_millis=lambda: 2_000,
    )
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    runtime = SpecialistExecutionRuntime(
        executor_registry=SpecialistExecutorRegistry((executor,)),
        invocation_store=store,
        wall_clock_millis=lambda: 2_000,
    )
    return (
        SpecialistTaskExecutionAdapter(
            policy_registry=default_specialist_registry(),
            runtime=runtime,
            monotonic_millis=lambda: 100,
        ),
        store,
    )


@pytest.mark.asyncio
async def test_routed_record_executes_with_durable_budget_limits_and_replays() -> None:
    task = _task()
    record = _routed_record(task)
    invocation_id = uuid4()
    adapter, _store = _adapter()
    capabilities = SpecialistCapabilitySet(proposal_allowed=True)

    first = await adapter.execute_record(
        record=record,
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
        capabilities=capabilities,
    )
    replay = await adapter.execute_record(
        record=record,
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
        capabilities=capabilities,
    )

    assert first.replay == SpecialistReplayDisposition.FRESH
    assert replay.replay == SpecialistReplayDisposition.REPLAYED
    assert replay.payload == first.payload


@pytest.mark.asyncio
async def test_non_routed_record_cannot_enter_specialist_runtime() -> None:
    task = _task()
    account = BudgetAccount(
        request_id=task.request_id,
        limits=task.budget,
        monotonic_millis=lambda: 100,
    )
    record = AgentTaskRecord(
        request_id=task.request_id,
        phase=AgentTaskPhase.EXPIRED,
        created_at_ms=1_500,
        updated_at_ms=1_600,
        task=task,
        budget=account.snapshot(),
        detail="expired fixture",
    )
    adapter, store = _adapter()

    with pytest.raises(SpecialistTaskNotExecutableError, match="cannot execute"):
        await adapter.execute_record(
            record=record,
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        )

    assert store.load() == []


@pytest.mark.asyncio
async def test_durable_route_version_must_match_active_policy() -> None:
    task = _task()
    record = _routed_record(task, version="2.0.0")
    adapter, store = _adapter()

    with pytest.raises(SpecialistExecutionPolicyError, match="version does not match"):
        await adapter.execute_record(
            record=record,
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        )

    assert store.load() == []


@pytest.mark.asyncio
async def test_cancelled_task_record_cannot_enter_runtime() -> None:
    task = _task()
    routed = _routed_record(task)
    cancelled_account = BudgetAccount.restore(
        routed.budget,
        monotonic_millis=lambda: 100,
    )
    cancelled_account.cancel()
    cancelled = AgentTaskRecord(
        request_id=task.request_id,
        phase=AgentTaskPhase.CANCELLED,
        created_at_ms=routed.created_at_ms,
        updated_at_ms=routed.updated_at_ms + 1,
        task=task,
        routing_decision=routed.routing_decision,
        budget=cancelled_account.snapshot(),
        cancel_reason="لغو کاربر",
        detail="لغو کاربر",
    )
    adapter, store = _adapter()

    with pytest.raises(SpecialistTaskNotExecutableError, match="cannot execute"):
        await adapter.execute_record(
            record=cancelled,
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        )

    assert store.load() == []


@pytest.mark.asyncio
async def test_adapter_preserves_capability_widening_rejection() -> None:
    task = _task()
    record = _routed_record(task)
    adapter, store = _adapter()

    with pytest.raises(SpecialistExecutionPolicyError, match="connectors exceed"):
        await adapter.execute_record(
            record=record,
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=SpecialistCapabilitySet(
                proposal_allowed=True,
                connector_ids=frozenset({"gmail"}),
            ),
        )

    assert store.load() == []
