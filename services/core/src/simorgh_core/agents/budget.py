from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.contracts import TaskBudget, UsageVector

_USAGE_DIMENSIONS = (
    "model_calls",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "estimated_cost_microusd",
    "retries",
    "parallel_branches",
)


class ReservationKind(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    RETRY = "retry"
    BRANCH = "branch"


class BudgetError(RuntimeError):
    """Base class for deterministic request-budget failures."""


class BudgetCancelledError(BudgetError):
    pass


class BudgetElapsedError(BudgetError):
    pass


class BudgetReservationNotFoundError(BudgetError):
    pass


class BudgetExceededError(BudgetError):
    def __init__(self, *, dimension: str, requested: int, limit: int) -> None:
        self.dimension = dimension
        self.requested = requested
        self.limit = limit
        super().__init__(
            f"budget dimension {dimension} would reach {requested}, above limit {limit}"
        )


class BudgetReservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reservation_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    kind: ReservationKind
    usage: UsageVector
    reserved_at_elapsed_ms: int = Field(ge=0)


class BudgetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    limits: TaskBudget
    committed: UsageVector
    reserved: UsageVector
    elapsed_ms: int = Field(ge=0)
    cancelled: bool
    exhausted_dimension: str | None = None


class BudgetAccount:
    """Thread-safe reserve-before-call and reconcile-after-call accounting."""

    def __init__(
        self,
        *,
        request_id: UUID,
        limits: TaskBudget,
        monotonic_millis: Callable[[], int] | None = None,
        initial_snapshot: BudgetSnapshot | None = None,
    ) -> None:
        self._request_id = request_id
        self._limits = limits
        self._monotonic_millis = monotonic_millis or (
            lambda: int(time.monotonic() * 1_000)
        )
        self._lock = RLock()
        self._started_at_ms = self._now_ms()
        self._elapsed_offset_ms = 0
        self._reservations: dict[UUID, BudgetReservation] = {}

        if initial_snapshot is None:
            self._committed = UsageVector()
            self._cancelled = False
            self._exhausted_dimension: str | None = None
        else:
            if initial_snapshot.request_id != request_id:
                raise ValueError("initial budget snapshot request_id does not match account")
            if initial_snapshot.limits != limits:
                raise ValueError("initial budget snapshot limits do not match account")
            # Reservation identities are process-local. After restart, an unresolved reservation
            # may already have reached an external provider/tool, so restore it conservatively as
            # committed usage and never recreate the reservation for automatic replay.
            self._committed = initial_snapshot.committed.plus(
                initial_snapshot.reserved
            )
            self._cancelled = initial_snapshot.cancelled
            self._exhausted_dimension = initial_snapshot.exhausted_dimension
            self._elapsed_offset_ms = initial_snapshot.elapsed_ms
            try:
                self._ensure_within_limits_locked(self._committed)
            except BudgetExceededError as exc:
                self._exhausted_dimension = exc.dimension

    @classmethod
    def restore(
        cls,
        snapshot: BudgetSnapshot,
        *,
        monotonic_millis: Callable[[], int] | None = None,
    ) -> BudgetAccount:
        return cls(
            request_id=snapshot.request_id,
            limits=snapshot.limits,
            monotonic_millis=monotonic_millis,
            initial_snapshot=snapshot,
        )

    @property
    def request_id(self) -> UUID:
        return self._request_id

    @property
    def limits(self) -> TaskBudget:
        return self._limits

    def reserve(
        self,
        *,
        kind: ReservationKind,
        usage: UsageVector,
    ) -> BudgetReservation:
        with self._lock:
            self._require_available_locked()
            self._validate_kind_usage(kind=kind, usage=usage)
            candidate = self._committed.plus(self._reserved_usage_locked()).plus(usage)
            self._ensure_within_limits_locked(candidate)
            reservation = BudgetReservation(
                request_id=self._request_id,
                kind=kind,
                usage=usage,
                reserved_at_elapsed_ms=self._elapsed_ms_locked(),
            )
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    def reconcile(
        self,
        *,
        reservation_id: UUID,
        actual_usage: UsageVector,
    ) -> BudgetSnapshot:
        with self._lock:
            self._require_not_cancelled_locked()
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                raise BudgetReservationNotFoundError(
                    f"budget reservation {reservation_id} does not exist"
                )
            self._validate_kind_usage(kind=reservation.kind, usage=actual_usage)
            self._reservations.pop(reservation_id)
            candidate = self._committed.plus(actual_usage)
            try:
                self._ensure_within_limits_locked(candidate)
            except BudgetExceededError as exc:
                # The external call may already have occurred. Record truthful actual usage,
                # mark the account exhausted, and prevent every later invocation.
                self._committed = candidate
                self._exhausted_dimension = exc.dimension
                raise
            self._committed = candidate
            return self._snapshot_locked()

    def commit_reserved(self, reservation_id: UUID) -> BudgetSnapshot:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                raise BudgetReservationNotFoundError(
                    f"budget reservation {reservation_id} does not exist"
                )
            usage = reservation.usage
        return self.reconcile(
            reservation_id=reservation_id,
            actual_usage=usage,
        )

    def release(self, reservation_id: UUID) -> BudgetSnapshot:
        with self._lock:
            if self._reservations.pop(reservation_id, None) is None:
                raise BudgetReservationNotFoundError(
                    f"budget reservation {reservation_id} does not exist"
                )
            return self._snapshot_locked()

    def cancel(self) -> BudgetSnapshot:
        with self._lock:
            self._cancelled = True
            self._reservations.clear()
            return self._snapshot_locked()

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            request_id=self._request_id,
            limits=self._limits,
            committed=self._committed,
            reserved=self._reserved_usage_locked(),
            elapsed_ms=self._elapsed_ms_locked(),
            cancelled=self._cancelled,
            exhausted_dimension=self._exhausted_dimension,
        )

    def _reserved_usage_locked(self) -> UsageVector:
        total = UsageVector()
        for reservation in self._reservations.values():
            total = total.plus(reservation.usage)
        return total

    def _require_available_locked(self) -> None:
        self._require_not_cancelled_locked()
        if self._exhausted_dimension is not None:
            raise BudgetExceededError(
                dimension=self._exhausted_dimension,
                requested=self._committed_value(self._exhausted_dimension),
                limit=self._limits.limit_for(self._exhausted_dimension),
            )
        elapsed = self._elapsed_ms_locked()
        if elapsed > self._limits.max_elapsed_ms:
            raise BudgetElapsedError(
                f"request elapsed time {elapsed}ms exceeds {self._limits.max_elapsed_ms}ms"
            )

    def _require_not_cancelled_locked(self) -> None:
        if self._cancelled:
            raise BudgetCancelledError("request budget was cancelled")

    def _ensure_within_limits_locked(self, usage: UsageVector) -> None:
        for dimension in _USAGE_DIMENSIONS:
            requested = self._usage_value(usage, dimension)
            limit = self._limits.limit_for(dimension)
            if requested > limit:
                raise BudgetExceededError(
                    dimension=dimension,
                    requested=requested,
                    limit=limit,
                )

    @staticmethod
    def _validate_kind_usage(*, kind: ReservationKind, usage: UsageVector) -> None:
        if kind == ReservationKind.MODEL and usage.model_calls != 1:
            raise ValueError("model reservation must account for exactly one model call")
        if kind == ReservationKind.TOOL and usage.tool_calls != 1:
            raise ValueError("tool reservation must account for exactly one tool call")
        if kind == ReservationKind.RETRY and usage.retries != 1:
            raise ValueError("retry reservation must account for exactly one retry")
        if kind == ReservationKind.BRANCH and usage.parallel_branches != 1:
            raise ValueError("branch reservation must account for exactly one parallel branch")

    @staticmethod
    def _usage_value(usage: UsageVector, dimension: str) -> int:
        value = getattr(usage, dimension)
        if not isinstance(value, int):
            raise TypeError(f"usage dimension {dimension} is not an integer")
        return value

    def _committed_value(self, dimension: str) -> int:
        return self._usage_value(self._committed, dimension)

    def _elapsed_ms_locked(self) -> int:
        elapsed_this_process = max(0, self._now_ms() - self._started_at_ms)
        return self._elapsed_offset_ms + elapsed_this_process

    def _now_ms(self) -> int:
        return max(0, int(self._monotonic_millis()))
