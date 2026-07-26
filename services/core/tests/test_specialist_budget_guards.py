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
from simorgh_core.agents.specialist_control import SpecialistTaskExecutionAdapter
from simorgh_core.agents.specialist_execution import (
    SpecialistCapabilitySet,
    SpecialistExecutionPolicyError,
    SpecialistExecutorRegistry,
    StaticProposalSpecialistExecutor,
)
from simorgh_core.agents.specialist_runtime import SpecialistExecutionRuntime
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord


def _record() -> AgentTaskRecord:
    task = TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="برای توسعه سیمرغ برنامه بساز",
        requested_outcome="برنامه توسعه",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
        allowed_data_sources=frozenset({"github"}),
    )
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


def _adapter() -> tuple[SpecialistTaskExecutionAdapter, InMemoryInvocationStore]:
    definition = default_specialist_registry().get("development.planner")
    executor = StaticProposalSpecialistExecutor(
        agent_id=definition.agent_id,
        agent_version=definition.version,
        output_contract=definition.output_contract,
        payload={"summary": "fixture", "steps": []},
        wall_clock_millis=lambda: 2_000,
    )
    store = InMemoryInvocationStore()
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
async def test_durable_budget_cannot_widen_original_task_budget() -> None:
    record = _record()
    widened_limits = record.budget.limits.model_copy(
        update={"max_model_calls": record.task.budget.max_model_calls + 1}
    )
    widened = record.model_copy(
        update={"budget": record.budget.model_copy(update={"limits": widened_limits})}
    )
    adapter, store = _adapter()

    with pytest.raises(SpecialistExecutionPolicyError, match="exceeds"):
        await adapter.execute_record(
            record=widened,
            invocation_id=uuid4(),
            context_fingerprint="f" * 64,
            capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        )

    assert store.load() == []


@pytest.mark.asyncio
async def test_exhausted_durable_budget_cannot_enter_runtime() -> None:
    record = _record()
    exhausted = record.model_copy(
        update={
            "budget": record.budget.model_copy(
                update={"exhausted_dimension": "model_calls"}
            )
        }
    )
    adapter, store = _adapter()

    with pytest.raises(SpecialistExecutionPolicyError, match="exhausted"):
        await adapter.execute_record(
            record=exhausted,
            invocation_id=uuid4(),
            context_fingerprint="f" * 64,
            capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        )

    assert store.load() == []
