from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from uuid import UUID

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import TaskBudget, TaskEnvelope, UsageVector
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.task_state import (
    DECISION_PHASES,
    AgentTaskPhase,
    AgentTaskRecord,
)
from simorgh_core.agents.task_store import (
    AgentTaskStore,
    AgentTaskStoreConflictError,
    AgentTaskStoreError,
    InMemoryAgentTaskStore,
    new_task_store_entry,
)


class AgentTaskControlPlaneError(RuntimeError):
    """Base class for typed specialist task control-plane failures."""


class AgentTaskConflictError(AgentTaskControlPlaneError):
    pass


class AgentTaskNotFoundError(AgentTaskControlPlaneError):
    pass


class AgentTaskStoreUnavailableError(AgentTaskControlPlaneError):
    pass


class AgentTaskRoutingUnknownError(AgentTaskControlPlaneError):
    pass


@dataclass(slots=True)
class _MutableTaskState:
    task: TaskEnvelope
    fingerprint: str
    account: BudgetAccount
    record: AgentTaskRecord
    cancelled: bool = False
    cancel_reason: str | None = None


class AgentTaskControlPlane:
    """Durable route/status/cancel control plane for one primary specialist."""

    def __init__(
        self,
        *,
        router: SpecialistRouter,
        store: AgentTaskStore | None = None,
        wall_clock_millis: Callable[[], int] | None = None,
        monotonic_millis: Callable[[], int] | None = None,
    ) -> None:
        self._router = router
        self._store = store or InMemoryAgentTaskStore()
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )
        self._monotonic_millis = monotonic_millis
        self._lock = RLock()
        self._states: dict[UUID, _MutableTaskState] = {}
        self._store_failure: AgentTaskStoreError | None = None
        self._load_store_locked(recover_interrupted=True)

    async def configure_store(self, store: AgentTaskStore) -> None:
        """Replace the task store during Core startup and recover durable records."""

        with self._lock:
            if any(
                state.record.phase == AgentTaskPhase.ROUTING
                for state in self._states.values()
            ):
                raise AgentTaskStoreUnavailableError(
                    "cannot replace agent task store while routing is active"
                )
            previous_store = self._store
            previous_states = self._states
            previous_failure = self._store_failure
            self._store = store
            self._states = {}
            self._store_failure = None
            try:
                self._load_store_locked(recover_interrupted=True)
            except BaseException:
                self._store = previous_store
                self._states = previous_states
                self._store_failure = previous_failure
                raise
            if previous_store is not store:
                previous_store.close()

    async def reset_to_memory_store(self) -> None:
        """Detach runtime durability without modifying prior on-disk contents."""

        with self._lock:
            if any(
                state.record.phase == AgentTaskPhase.ROUTING
                for state in self._states.values()
            ):
                raise AgentTaskStoreUnavailableError(
                    "cannot reset agent task store while routing is active"
                )
            previous_store = self._store
            self._store = InMemoryAgentTaskStore()
            self._states = {}
            self._store_failure = None
            previous_store.close()

    async def submit(self, task: TaskEnvelope) -> AgentTaskRecord:
        fingerprint = _task_fingerprint(task)
        with self._lock:
            self._require_store_healthy_locked()
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
                self._persist_new_state_locked(
                    task=task,
                    fingerprint=fingerprint,
                    account=account,
                    record=record,
                )
                return record

            routing_record = AgentTaskRecord(
                request_id=task.request_id,
                phase=AgentTaskPhase.ROUTING,
                created_at_ms=now,
                updated_at_ms=now,
                task=task,
                budget=account.snapshot(),
                detail="task identity persisted before specialist routing",
            )
            self._persist_new_state_locked(
                task=task,
                fingerprint=fingerprint,
                account=account,
                record=routing_record,
            )

        try:
            decision = await self._router.route(task=task, budget=account)
        except asyncio.CancelledError:
            with self._lock:
                self._require_store_healthy_locked()
                current = self._states[task.request_id]
                if not current.cancelled:
                    self._mark_routing_unknown_locked(
                        task=task,
                        account=account,
                        detail=(
                            "specialist routing coroutine was cancelled after durable "
                            "claim; automatic replay is blocked"
                        ),
                    )
            raise
        except Exception as exc:
            with self._lock:
                self._require_store_healthy_locked()
                current = self._states[task.request_id]
                if current.cancelled:
                    return current.record
                self._mark_routing_unknown_locked(
                    task=task,
                    account=account,
                    detail=(
                        "specialist routing failed after durable claim; automatic replay "
                        f"is blocked ({exc.__class__.__name__})"
                    ),
                )
            raise AgentTaskRoutingUnknownError(
                "agent task routing failed closed and is recorded as unknown"
            ) from exc

        with self._lock:
            self._require_store_healthy_locked()
            current = self._states[task.request_id]
            if current.cancelled:
                return current.record
            stabilized_account = _restore_stable_account(
                account,
                monotonic_millis=self._monotonic_millis,
            )
            completed_record = AgentTaskRecord(
                request_id=task.request_id,
                phase=DECISION_PHASES[decision.state],
                created_at_ms=current.record.created_at_ms,
                updated_at_ms=self._next_record_time(
                    current.record.updated_at_ms
                ),
                task=task,
                routing_decision=decision,
                budget=stabilized_account.snapshot(),
                detail=decision.reason,
            )
            self._persist_transition_locked(
                state=current,
                account=stabilized_account,
                record=completed_record,
            )
            return completed_record

    async def get(self, request_id: UUID) -> AgentTaskRecord:
        with self._lock:
            self._require_store_healthy_locked()
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
            self._require_store_healthy_locked()
            state = self._states.get(request_id)
            if state is None:
                raise AgentTaskNotFoundError(f"agent task {request_id} was not found")
            if state.record.phase in {
                AgentTaskPhase.CANCELLED,
                AgentTaskPhase.EXPIRED,
            }:
                return state.record

            state.cancelled = True
            state.cancel_reason = normalized_reason[:1_000]
            state.account.cancel()
            cancelled_record = AgentTaskRecord(
                request_id=request_id,
                phase=AgentTaskPhase.CANCELLED,
                created_at_ms=state.record.created_at_ms,
                updated_at_ms=self._next_record_time(state.record.updated_at_ms),
                task=state.task,
                routing_decision=state.record.routing_decision,
                budget=state.account.snapshot(),
                cancel_reason=state.cancel_reason,
                detail=state.cancel_reason,
            )
            self._persist_transition_locked(
                state=state,
                account=state.account,
                record=cancelled_record,
            )
            return cancelled_record

    async def clear_for_test(self) -> None:
        with self._lock:
            self._require_store_healthy_locked()
            try:
                self._store.clear()
            except AgentTaskStoreError as exc:
                self._record_store_failure_locked(exc)
                raise AgentTaskStoreUnavailableError(str(exc)) from exc
            self._states.clear()

    def _load_store_locked(self, *, recover_interrupted: bool) -> None:
        try:
            entries = self._store.load()
        except AgentTaskStoreError as exc:
            self._record_store_failure_locked(exc)
            raise AgentTaskStoreUnavailableError(str(exc)) from exc

        now = self._now_ms()
        recovered: dict[UUID, _MutableTaskState] = {}
        for entry in entries:
            record = entry.record
            account = BudgetAccount.restore(
                record.budget,
                monotonic_millis=self._monotonic_millis,
            )
            if recover_interrupted and record.phase == AgentTaskPhase.ROUTING:
                record = AgentTaskRecord(
                    request_id=record.request_id,
                    phase=AgentTaskPhase.UNKNOWN,
                    created_at_ms=record.created_at_ms,
                    updated_at_ms=max(now, record.updated_at_ms),
                    task=record.task,
                    budget=account.snapshot(),
                    detail=(
                        "Core restarted while specialist routing was in progress; "
                        "automatic replay is blocked"
                    ),
                )
                try:
                    self._store.upsert(new_task_store_entry(record))
                except AgentTaskStoreError as exc:
                    self._record_store_failure_locked(exc)
                    raise AgentTaskStoreUnavailableError(str(exc)) from exc

            recovered[record.request_id] = _MutableTaskState(
                task=record.task,
                fingerprint=entry.task_fingerprint,
                account=account,
                record=record,
                cancelled=record.phase == AgentTaskPhase.CANCELLED,
                cancel_reason=record.cancel_reason,
            )
        self._states = recovered

    def _mark_routing_unknown_locked(
        self,
        *,
        task: TaskEnvelope,
        account: BudgetAccount,
        detail: str,
    ) -> AgentTaskRecord:
        current = self._states[task.request_id]
        stabilized_account = _restore_stable_account(
            account,
            monotonic_millis=self._monotonic_millis,
        )
        unknown_record = AgentTaskRecord(
            request_id=task.request_id,
            phase=AgentTaskPhase.UNKNOWN,
            created_at_ms=current.record.created_at_ms,
            updated_at_ms=self._next_record_time(current.record.updated_at_ms),
            task=task,
            budget=stabilized_account.snapshot(),
            detail=detail,
        )
        self._persist_transition_locked(
            state=current,
            account=stabilized_account,
            record=unknown_record,
        )
        return unknown_record

    def _persist_new_state_locked(
        self,
        *,
        task: TaskEnvelope,
        fingerprint: str,
        account: BudgetAccount,
        record: AgentTaskRecord,
    ) -> None:
        try:
            self._store.upsert(new_task_store_entry(record))
        except AgentTaskStoreConflictError as exc:
            raise AgentTaskConflictError(str(exc)) from exc
        except AgentTaskStoreError as exc:
            self._record_store_failure_locked(exc)
            raise AgentTaskStoreUnavailableError(str(exc)) from exc
        self._states[task.request_id] = _MutableTaskState(
            task=task,
            fingerprint=fingerprint,
            account=account,
            record=record,
        )

    def _persist_transition_locked(
        self,
        *,
        state: _MutableTaskState,
        account: BudgetAccount,
        record: AgentTaskRecord,
    ) -> None:
        try:
            self._store.upsert(new_task_store_entry(record))
        except AgentTaskStoreError as exc:
            self._record_store_failure_locked(exc)
            raise AgentTaskStoreUnavailableError(
                f"durable agent-task transition failed: {exc}"
            ) from exc
        state.account = account
        state.record = record

    def _record_store_failure_locked(self, exc: AgentTaskStoreError) -> None:
        if self._store_failure is None:
            self._store_failure = exc

    def _require_store_healthy_locked(self) -> None:
        if self._store_failure is not None:
            raise AgentTaskStoreUnavailableError(
                "agent task store is unhealthy after a durable operation failure: "
                f"{self._store_failure}"
            ) from self._store_failure

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))

    def _next_record_time(self, previous_updated_at_ms: int) -> int:
        return max(previous_updated_at_ms, self._now_ms())


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


def _restore_stable_account(
    account: BudgetAccount,
    *,
    monotonic_millis: Callable[[], int] | None,
) -> BudgetAccount:
    snapshot = account.snapshot()
    if snapshot.reserved == UsageVector():
        return account
    return BudgetAccount.restore(
        snapshot,
        monotonic_millis=monotonic_millis,
    )
