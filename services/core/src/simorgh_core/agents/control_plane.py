from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.budget import BudgetAccount, BudgetSnapshot
from simorgh_core.agents.contracts import RoutingDecision, RoutingState, TaskEnvelope
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


class AgentTaskRecord(BaseModel):
    """Public, content-aware task status without private trace payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    phase: AgentTaskPhase
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    task: TaskEnvelope
    routing_decision: RoutingDecision | None = None
    budget: BudgetSnapshot
    cancel_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_phase_shape(self) -> Self:
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms cannot precede created_at_ms")
        if self.phase == AgentTaskPhase.ROUTING and self.routing_decision is not None:
            raise ValueError("routing phase cannot already contain a decision")
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
    completed: asyncio.Future[None]
    cancelled: bool = False
    cancel_reason: str | None = None


class AgentTaskControlPlane:
    """Idempotent route/status/cancel foundation for one primary specialist per task."""

    def __init__(
        self,
        *,
        router: SpecialistRouter,
        wall_clock_millis: callable[[], int] | None = None,
    ) -> None:
        self._router = router
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )
        self._lock = asyncio.Lock()
        self._states: dict[UUID, _MutableTaskState] = {}

    async def submit(self, task: TaskEnvelope) -> AgentTaskRecord:
        fingerprint = _task_fingerprint(task)
        creator = False
        state: _MutableTaskState
        async with self._lock:
            existing = self._states.get(task.request_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise AgentTaskConflictError(
                        f"request_id {task.request_id} was reused with different task content"
                    )
                state = existing
            else:
                creator = True
                account = BudgetAccount(
                    request_id=task.request_id,
                    limits=task.budget,
                )
                now = self._now_ms()
                completed: asyncio.Future[None] = (
                    asyncio.get_running_loop().create_future()
                )
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
                    completed=completed,
                )
                self._states[task.request_id] = state

        if creator:
            await self._route_creator(state)
        else:
            await asyncio.shield(state.completed)
        return await self.get(task.request_id)

    async def get(self, request_id: UUID) -> AgentTaskRecord:
        async with self._lock:
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
        async with self._lock:
            state = self._states.get(request_id)
            if state is None:
                raise AgentTaskNotFoundError(f"agent task {request_id} was not found")
            if state.record.phase == AgentTaskPhase.CANCELLED:
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
            )
            return state.record

    async def clear_for_test(self) -> None:
        async with self._lock:
            for state in self._states.values():
                if not state.completed.done():
                    state.completed.cancel()
            self._states.clear()

    async def _route_creator(self, state: _MutableTaskState) -> None:
        try:
            decision = await self._router.route(
                task=state.task,
                budget=state.account,
            )
            async with self._lock:
                if state.cancelled:
                    if not state.completed.done():
                        state.completed.set_result(None)
                    return
                state.record = AgentTaskRecord(
                    request_id=state.task.request_id,
                    phase=_phase_from_decision(decision),
                    created_at_ms=state.record.created_at_ms,
                    updated_at_ms=self._now_ms(),
                    task=state.task,
                    routing_decision=decision,
                    budget=state.account.snapshot(),
                )
                if not state.completed.done():
                    state.completed.set_result(None)
        except BaseException as exc:
            async with self._lock:
                if not state.completed.done():
                    state.completed.set_exception(exc)
            raise

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))


def _phase_from_decision(decision: RoutingDecision) -> AgentTaskPhase:
    return {
        RoutingState.ROUTED: AgentTaskPhase.ROUTED,
        RoutingState.NEEDS_CLARIFICATION: AgentTaskPhase.NEEDS_CLARIFICATION,
        RoutingState.NEEDS_ESCALATION: AgentTaskPhase.NEEDS_ESCALATION,
        RoutingState.BUDGET_EXHAUSTED: AgentTaskPhase.BUDGET_EXHAUSTED,
        RoutingState.POLICY_BLOCKED: AgentTaskPhase.POLICY_BLOCKED,
        RoutingState.CONTRACT_INVALID: AgentTaskPhase.CONTRACT_INVALID,
    }[decision.state]


def _task_fingerprint(task: TaskEnvelope) -> str:
    canonical = task.model_dump_json().encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
