from __future__ import annotations

from typing import Any
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
    UsageVector,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import InMemoryInvocationStore, InvocationPhase
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistCapabilitySet,
    SpecialistExecutionOutcome,
    SpecialistExecutionPolicyError,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    SpecialistExecutorRegistry,
)
from simorgh_core.agents.specialist_runtime import (
    SpecialistExecutionExpiredError,
    SpecialistExecutionRuntime,
)


class RecordingProposalExecutor:
    def __init__(
        self,
        *,
        agent_id: str = "development.planner",
        agent_version: str = "1.0.0",
        output_contract: str = "development.plan.v1",
        monotonic_clock: dict[str, int] | None = None,
        expire_during_execution: bool = False,
    ) -> None:
        self._agent_id = agent_id
        self._agent_version = agent_version
        self._output_contract = output_contract
        self._monotonic_clock = monotonic_clock
        self._expire_during_execution = expire_during_execution
        self.calls = 0

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def agent_version(self) -> str:
        return self._agent_version

    @property
    def output_contract(self) -> str:
        return self._output_contract

    async def execute(
        self,
        *,
        request: SpecialistExecutionRequest,
        cancellation: SpecialistCancellation,
        budget: BudgetAccount,
    ) -> SpecialistExecutionResult:
        del budget
        self.calls += 1
        cancellation.raise_if_cancelled()
        if self._expire_during_execution and self._monotonic_clock is not None:
            self._monotonic_clock["now"] = request.effective_budget.max_elapsed_ms + 1
        return SpecialistExecutionResult(
            request_id=request.request_id,
            invocation_id=request.invocation_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            effect=request.effect,
            outcome=SpecialistExecutionOutcome.COMPLETED,
            output_contract=request.output_contract,
            payload={"summary": "fixture", "steps": []},
            committed_usage=UsageVector(),
            started_at_ms=2_000,
            completed_at_ms=2_000,
        )


def _execution_inputs() -> tuple[
    TaskEnvelope,
    RoutingDecision,
    Any,
]:
    definition = default_specialist_registry().get("development.planner")
    task = TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="برای توسعه سیمرغ برنامه بساز",
        requested_outcome="برنامه توسعه",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
        allowed_data_sources=frozenset(),
        budget=definition.budget_ceiling,
    )
    decision = RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id=definition.agent_id,
        selected_agent_version=definition.version,
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="explicit route",
    )
    return task, decision, definition


@pytest.mark.parametrize(
    ("agent_id", "agent_version", "output_contract"),
    (
        ("bad/agent", "1.0.0", "development.plan.v1"),
        ("development.planner", "version-one", "development.plan.v1"),
        ("development.planner", "1.0.0", "Bad Contract!"),
    ),
)
def test_registry_rejects_invalid_executor_identity(
    agent_id: str,
    agent_version: str,
    output_contract: str,
) -> None:
    executor = RecordingProposalExecutor(
        agent_id=agent_id,
        agent_version=agent_version,
        output_contract=output_contract,
    )

    with pytest.raises(SpecialistExecutionPolicyError, match="invalid"):
        SpecialistExecutorRegistry((executor,))


def test_cancellation_preserves_first_reason() -> None:
    cancellation = SpecialistCancellation()

    cancellation.cancel("first reason")
    cancellation.cancel("second reason")

    assert cancellation.cancelled
    assert cancellation.reason == "first reason"


@pytest.mark.asyncio
async def test_elapsed_budget_blocks_executor_entry_and_expires_claim() -> None:
    task, decision, definition = _execution_inputs()
    clock = {"now": 0}
    budget = BudgetAccount(
        request_id=task.request_id,
        limits=definition.budget_ceiling,
        monotonic_millis=lambda: clock["now"],
    )
    clock["now"] = definition.budget_ceiling.max_elapsed_ms + 1
    executor = RecordingProposalExecutor()
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    runtime = SpecialistExecutionRuntime(
        executor_registry=SpecialistExecutorRegistry((executor,)),
        invocation_store=store,
        wall_clock_millis=lambda: 2_000,
    )
    invocation_id = uuid4()

    with pytest.raises(SpecialistExecutionExpiredError, match="elapsed"):
        await runtime.execute(
            task=task,
            decision=decision,
            definition=definition,
            invocation_id=invocation_id,
            context_fingerprint="a" * 64,
            capabilities=SpecialistCapabilitySet(proposal_allowed=True),
            budget=budget,
        )

    assert executor.calls == 0
    assert store.get(invocation_id).state == InvocationPhase.EXPIRED


@pytest.mark.asyncio
async def test_elapsed_budget_during_execution_prevents_success() -> None:
    task, decision, definition = _execution_inputs()
    clock = {"now": 0}
    budget = BudgetAccount(
        request_id=task.request_id,
        limits=definition.budget_ceiling,
        monotonic_millis=lambda: clock["now"],
    )
    executor = RecordingProposalExecutor(
        monotonic_clock=clock,
        expire_during_execution=True,
    )
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    runtime = SpecialistExecutionRuntime(
        executor_registry=SpecialistExecutorRegistry((executor,)),
        invocation_store=store,
        wall_clock_millis=lambda: 2_000,
    )
    invocation_id = uuid4()

    with pytest.raises(SpecialistExecutionExpiredError, match="elapsed"):
        await runtime.execute(
            task=task,
            decision=decision,
            definition=definition,
            invocation_id=invocation_id,
            context_fingerprint="b" * 64,
            capabilities=SpecialistCapabilitySet(proposal_allowed=True),
            budget=budget,
        )

    assert executor.calls == 1
    assert store.get(invocation_id).state == InvocationPhase.EXPIRED
