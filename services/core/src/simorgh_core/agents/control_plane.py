from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.budget import BudgetAccount, BudgetSnapshot
from simorgh_core.agents.contracts import RoutingDecision, RoutingState, TaskBudget, TaskEnvelope
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.router import SpecialistRouter


class AgentTaskControlPlaneError(RuntimeError):
    """Base class for typed specialist task control-plane failures."""


class AgentTaskConflictError(AgentTaskControlPlaneError):
    pass


class AgentTaskNotFoundError(AgentTaskControlPlaneError):
    pass


class AgentTaskPhase(StrEnum):
    ROUTING = "routing"
    ROUTED = "routed"
    NEEDS_CLARIFICATION = "needs_clarification"
    NEEDS_ESCALATION = "needs_escalation"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_BLOCKED = "policy_blocked"
    CONTRACT_INVALID = "contract_invalid"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


_DECISION_PHASES = {
    RoutingState.ROUTED: AgentTaskPhase.ROUTED,
    RoutingState.NEEDS_CLARIFICATION: AgentTaskPhase.NEEDS_CLARIFICATION,
    RoutingState.NEEDS_ESCALATION: AgentTaskPhase.NEEDS_ESCALATION,
    RoutingState.BUDGET_EXHAUSTED: AgentTaskPhase.BUDGET_EXHAUSTED,
    RoutingState.POLICY_BLOCKED: AgentTaskPhase.POLICY_BLOCKED,
    RoutingState.CONTRACT_INVALID: AgentTaskPhase.CONTRACT_INVALID,
}


class AgentTaskRecord(BaseModel):
    """Operator-visible task state; private trace payloads remain in the trace sink."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    phase: AgentTaskPhase
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    task: TaskEnvelope
    routing_decision: RoutingDecision | None = None
    budget: BudgetSnapshot
    cancel_reason: str | None = Field(default=None, max_length=1_000)
    detail: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_phase_shape(self) -> Self:
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms cannot precede created_at_ms")
        if self.task.request_id != self.request_id:
            raise ValueError("task request_id does not match record request_id")
        if self.budget.request_id != self.request_id:
            raise ValueError("budget request_id does not match record request_id")

        if self.phase == AgentTaskPhase.ROUTING:
            if self.routing_decision is not None:
                raise ValueError("routing phase cannot already contain a decision")
        elif self.phase in {AgentTaskPhase.CANCELLED, AgentTaskPhase.EXPIRED}:
            pass
        else:
            decision = self.routing_decision
            if decision is None:
                raise ValueError("routed terminal phase requires a routing decision")
            if decision.request_id != self.request_id:
                raise ValueError("routing decision request_id does not match record")
            if _DECISION_PHASES[decision.state] != self.phase:
                raise ValueError("record phase does not match routing decision state")

        if self.phase == AgentTaskPhase.CANCELLED:
            if self.cancel_reason is None:
                raise ValueError("cancelled task requires a cancel reason")
        elif self.cancel_reason is not None:
            raise ValueError("non-cancelled task cannot contain a cancel reason")
        return self


@dataclass(slots=True)
class _MutableTaskState:
    task: TaskEnvelope
    fingerprint: str
    account: BudgetAccount
    record: AgentTaskRecord
    cancelled: bool = False
    cancel_reason: str | None = None


class AgentTaskControlPlane:
    """Idempotent route/status/cancel foundation for one primary specialist per task."""

    def __init__(
        self,
        *,
        router: SpecialistRouter,
        wall_clock_millis: Callable[[], int] | None = None,
        monotonic_millis: Callable[[], int] | None = None,
    ) -> None:
        self._router = router
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )
        self._monotonic_millis = monotonic_millis
        self._lock = RLock()
        self._states: dict[UUID, _MutableTaskState] = {}

    async def submit(self, task: TaskEnvelope) -> AgentTaskRecord:
        fingerprint = _task_fingerprint(task)
        with self._lock:
            existing = self._states.get(task.request_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise AgentTaskConflictError(
                        f"request_id {task.request_id} was reused with different task content"
                    )
                return existing.record

            now = self._now_ms()
            effective_budget = _effective_budget(task=task, now_ms=now)
            account = BudgetAccount(
                request_id=task.request_id,
                limits=effective_budget,
                monotonic_millis=self._monotonic_millis,
            )
            if task.deadline_at_ms is not None and task.deadline_at_ms <= now:
                record = AgentTaskRecord(
                    request_id=task.request_id,
                    phase=AgentTaskPhase.EXPIRED,
                    created_at_ms=now,
                    updated_at_ms=now,
                    task=task,
                    budget=account.snapshot(),
                    detail="task deadline elapsed before routing began",
                )
                self._states[task.request_id] = _MutableTaskState(
                    task=task,
                    fingerprint=fingerprint,
                    account=account,
                    record=record,
                )
                return record

            state = _MutableTaskState(
                task=task,
                fingerprint=fingerprint,
                account=account,
                record=AgentTaskRecord(
                    request_id=task.request_id,
                    phase=AgentTaskPhase.ROUTING,
                    created_at_ms=now,
                    updated_at_ms=now,
                    task=task,
                    budget=account.snapshot(),
                ),
            )
            self._states[task.request_id] = state

        decision = await self._router.route(task=task, budget=account)
        with self._lock:
            current = self._states[task.request_id]
            if current.cancelled:
                return current.record
            current.record = AgentTaskRecord(
                request_id=task.request_id,
                phase=_DECISION_PHASES[decision.state],
                created_at_ms=current.record.created_at_ms,
                updated_at_ms=self._now_ms(),
                task=task,
                routing_decision=decision,
                budget=account.snapshot(),
                detail=decision.reason,
            )
            return current.record

    async def get(self, request_id: UUID) -> AgentTaskRecord:
        with self._lock:
            state = self._states.get(request_id)
            if state is None:
                raise AgentTaskNotFoundError(f"agent task {request_id} was not found")
            return state.record

    async def cancel(
        self,
        *,
        request_id: UUID,
        reason: str,
    ) -> AgentTaskRecord:
        normalized_reason = reason.strip() or "operator requested cancellation"
        with self._lock:
            state = self._states.get(request_id)
            if state is None:
                raise AgentTaskNotFoundError(f"agent task {request_id} was not found")
            if state.record.phase in {AgentTaskPhase.CANCELLED, AgentTaskPhase.EXPIRED}:
                return state.record
            state.cancelled = True
            state.cancel_reason = normalized_reason[:1_000]
            state.account.cancel()
            state.record = AgentTaskRecord(
                request_id=request_id,
                phase=AgentTaskPhase.CANCELLED,
                created_at_ms=state.record.created_at_ms,
                updated_at_ms=self._now_ms(),
                task=state.task,
                routing_decision=state.record.routing_decision,
                budget=state.account.snapshot(),
                cancel_reason=state.cancel_reason,
                detail=state.cancel_reason,
            )
            return state.record

    async def clear_for_test(self) -> None:
        with self._lock:
            self._states.clear()

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))


def _effective_budget(*, task: TaskEnvelope, now_ms: int) -> TaskBudget:
    if task.deadline_at_ms is None:
        return task.budget
    remaining_ms = max(1, task.deadline_at_ms - now_ms)
    return task.budget.model_copy(
        update={"max_elapsed_ms": min(task.budget.max_elapsed_ms, remaining_ms)}
    )


def _task_fingerprint(task: TaskEnvelope) -> str:
    payload = task.model_dump(mode="json")
    payload["allowed_data_sources"] = sorted(task.allowed_data_sources)
    return canonical_fingerprint(payload)
