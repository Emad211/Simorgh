from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Protocol
from uuid import UUID

from simorgh_core.agents.cancellation_runtime import (
    CancellationOwnerRegistry,
    CancellationRegistrationBlockedError,
    cancellation_owner_registry,
)
from simorgh_core.agents.contracts import SideEffectPolicy
from simorgh_core.agents.invocations import InvocationRecord, InvocationStore
from simorgh_core.agents.registry import SpecialistRegistry
from simorgh_core.agents.specialist_control import SpecialistTaskExecutionAdapter
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistCapabilitySet,
    SpecialistExecutionCancelledError,
    SpecialistExecutionPolicyError,
    SpecialistExecutionResult,
    SpecialistExecutorRegistry,
    stable_specialist_cancellation_owner_id,
)
from simorgh_core.agents.specialist_runtime import (
    SpecialistExecutionRuntime,
    SpecialistInvocationInProgressError,
)
from simorgh_core.agents.task_state import AgentTaskRecord


class AgentTaskReader(Protocol):
    async def get(self, request_id: UUID) -> AgentTaskRecord: ...


class SpecialistExecutionControlPlane:
    """Resolve durable routed tasks and execute one zero-external specialist safely."""

    def __init__(
        self,
        *,
        task_reader: AgentTaskReader,
        policy_registry: SpecialistRegistry,
        executor_registry: SpecialistExecutorRegistry,
        invocation_store: InvocationStore,
        cancellation_registry: CancellationOwnerRegistry | None = None,
        wall_clock_millis: Callable[[], int] | None = None,
        monotonic_millis: Callable[[], int] | None = None,
    ) -> None:
        runtime = SpecialistExecutionRuntime(
            executor_registry=executor_registry,
            invocation_store=invocation_store,
            wall_clock_millis=wall_clock_millis,
        )
        self._tasks = task_reader
        self._policies = policy_registry
        self._invocations = invocation_store
        self._cancellation_owners = (
            cancellation_registry or cancellation_owner_registry
        )
        self._adapter = SpecialistTaskExecutionAdapter(
            policy_registry=policy_registry,
            runtime=runtime,
            monotonic_millis=monotonic_millis,
        )
        self._lock = RLock()
        self._active: dict[UUID, SpecialistCancellation] = {}

    async def execute(
        self,
        *,
        request_id: UUID,
        invocation_id: UUID,
        context_fingerprint: str,
    ) -> SpecialistExecutionResult:
        record = await self._tasks.get(request_id)
        capabilities = self._local_capabilities(record)
        owner_id = stable_specialist_cancellation_owner_id(
            request_id=request_id, invocation_id=invocation_id
        )
        token = SpecialistCancellation(owner_id=owner_id)
        with self._lock:
            if invocation_id in self._active:
                raise SpecialistInvocationInProgressError(
                    f"specialist invocation {invocation_id} is already active"
                )
            self._active[invocation_id] = token
        try:
            try:
                self._cancellation_owners.register(
                    request_id=request_id,
                    owner_id=owner_id,
                    target=token,
                )
            except CancellationRegistrationBlockedError as exc:
                raise SpecialistExecutionCancelledError(
                    "durable task cancellation blocks specialist entry"
                ) from exc
            return await self._adapter.execute_record(
                record=record,
                invocation_id=invocation_id,
                context_fingerprint=context_fingerprint,
                capabilities=capabilities,
                cancellation=token,
            )
        finally:
            self._cancellation_owners.unregister(
                request_id=request_id,
                owner_id=owner_id,
                target=token,
            )
            with self._lock:
                self._active.pop(invocation_id, None)

    def cancel_active(
        self,
        *,
        invocation_id: UUID,
        reason: str,
    ) -> bool:
        with self._lock:
            token = self._active.get(invocation_id)
            if token is None:
                return False
            token.cancel(reason)
            return True

    def get_invocation(self, invocation_id: UUID) -> InvocationRecord:
        return self._invocations.get(invocation_id)

    def _local_capabilities(self, record: AgentTaskRecord) -> SpecialistCapabilitySet:
        decision = record.routing_decision
        if decision is None or decision.selected_agent_id is None:
            raise SpecialistExecutionPolicyError(
                "durable task has no selected specialist identity"
            )
        definition = self._policies.get(decision.selected_agent_id)
        if definition.side_effect_policy == SideEffectPolicy.TYPED_EXECUTOR_ONLY:
            raise SpecialistExecutionPolicyError(
                "typed mutation specialist execution is not enabled in this runtime"
            )
        return SpecialistCapabilitySet(
            proposal_allowed=(
                definition.side_effect_policy == SideEffectPolicy.PROPOSE_ONLY
            )
        )
