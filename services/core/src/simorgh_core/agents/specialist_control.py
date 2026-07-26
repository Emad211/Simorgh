from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import RoutingState
from simorgh_core.agents.registry import SpecialistRegistry
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistCapabilitySet,
    SpecialistExecutionPolicyError,
    SpecialistExecutionResult,
)
from simorgh_core.agents.specialist_runtime import SpecialistExecutionRuntime
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord


class SpecialistTaskAdapterError(RuntimeError):
    """Base class for routed-task to specialist-execution adapter failures."""


class SpecialistTaskNotExecutableError(SpecialistTaskAdapterError):
    pass


class SpecialistTaskExecutionAdapter:
    """Derive specialist execution only from one durable routed task record."""

    def __init__(
        self,
        *,
        policy_registry: SpecialistRegistry,
        runtime: SpecialistExecutionRuntime,
        monotonic_millis: Callable[[], int] | None = None,
    ) -> None:
        self._policies = policy_registry
        self._runtime = runtime
        self._monotonic_millis = monotonic_millis

    async def execute_record(
        self,
        *,
        record: AgentTaskRecord,
        invocation_id: UUID,
        context_fingerprint: str,
        capabilities: SpecialistCapabilitySet,
        cancellation: SpecialistCancellation | None = None,
    ) -> SpecialistExecutionResult:
        if record.phase != AgentTaskPhase.ROUTED:
            raise SpecialistTaskNotExecutableError(
                f"agent task in phase {record.phase.value} cannot execute a specialist"
            )
        decision = record.routing_decision
        if decision is None or decision.state != RoutingState.ROUTED:
            raise SpecialistTaskNotExecutableError(
                "routed task record does not contain a routed decision"
            )
        agent_id = decision.selected_agent_id
        agent_version = decision.selected_agent_version
        if agent_id is None or agent_version is None:
            raise SpecialistTaskNotExecutableError(
                "routed decision has no exact specialist identity"
            )
        definition = self._policies.get(agent_id)
        if definition.version != agent_version:
            raise SpecialistExecutionPolicyError(
                "durable route version does not match the active compiled specialist policy"
            )
        if record.budget.cancelled:
            raise SpecialistTaskNotExecutableError(
                "cancelled task budget cannot enter specialist execution"
            )

        budget = BudgetAccount.restore(
            record.budget,
            monotonic_millis=self._monotonic_millis,
        )
        # The durable routing control plane may tighten elapsed or usage limits before execution.
        # Preserve those authoritative limits in the derived execution identity.
        execution_task = record.task.model_copy(
            update={"budget": record.budget.limits}
        )
        return await self._runtime.execute(
            task=execution_task,
            decision=decision,
            definition=definition,
            invocation_id=invocation_id,
            context_fingerprint=context_fingerprint,
            capabilities=capabilities,
            budget=budget,
            cancellation=cancellation,
        )
