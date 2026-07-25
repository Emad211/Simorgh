from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.budget import (
    BudgetAccount,
    BudgetCancelledError,
    BudgetElapsedError,
    BudgetExceededError,
    ReservationKind,
)
from simorgh_core.agents.contracts import TaskBudget, UsageVector


def test_usage_is_reserved_before_call_and_reconciled_afterwards() -> None:
    now = [1_000]
    account = BudgetAccount(
        request_id=uuid4(),
        limits=TaskBudget(
            max_model_calls=1,
            max_tool_calls=0,
            max_input_tokens=1_000,
            max_output_tokens=500,
            max_estimated_cost_microusd=10_000,
            max_elapsed_ms=5_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
        monotonic_millis=lambda: now[0],
    )

    reservation = account.reserve(
        kind=ReservationKind.MODEL,
        usage=UsageVector(
            model_calls=1,
            input_tokens=700,
            output_tokens=300,
            estimated_cost_microusd=8_000,
        ),
    )
    reserved = account.snapshot()
    assert reserved.committed == UsageVector()
    assert reserved.reserved.model_calls == 1
    assert reserved.reserved.input_tokens == 700

    now[0] = 1_250
    reconciled = account.reconcile(
        reservation_id=reservation.reservation_id,
        actual_usage=UsageVector(
            model_calls=1,
            input_tokens=420,
            output_tokens=110,
            estimated_cost_microusd=3_500,
        ),
    )
    assert reconciled.reserved == UsageVector()
    assert reconciled.committed.model_calls == 1
    assert reconciled.committed.input_tokens == 420
    assert reconciled.committed.output_tokens == 110
    assert reconciled.committed.estimated_cost_microusd == 3_500
    assert reconciled.elapsed_ms == 250


def test_competing_reservations_cannot_overcommit_the_same_budget() -> None:
    account = BudgetAccount(
        request_id=uuid4(),
        limits=TaskBudget(
            max_model_calls=1,
            max_tool_calls=0,
            max_input_tokens=1_000,
            max_output_tokens=500,
            max_estimated_cost_microusd=10_000,
            max_elapsed_ms=5_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
        monotonic_millis=lambda: 100,
    )
    account.reserve(
        kind=ReservationKind.MODEL,
        usage=UsageVector(
            model_calls=1,
            input_tokens=500,
            output_tokens=100,
        ),
    )

    with pytest.raises(BudgetExceededError) as raised:
        account.reserve(
            kind=ReservationKind.MODEL,
            usage=UsageVector(
                model_calls=1,
                input_tokens=1,
                output_tokens=1,
            ),
        )
    assert raised.value.dimension == "model_calls"


def test_actual_provider_overage_is_recorded_and_exhausts_future_calls() -> None:
    account = BudgetAccount(
        request_id=uuid4(),
        limits=TaskBudget(
            max_model_calls=1,
            max_tool_calls=0,
            max_input_tokens=100,
            max_output_tokens=100,
            max_estimated_cost_microusd=1_000,
            max_elapsed_ms=5_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
        monotonic_millis=lambda: 100,
    )
    reservation = account.reserve(
        kind=ReservationKind.MODEL,
        usage=UsageVector(
            model_calls=1,
            input_tokens=80,
            output_tokens=50,
            estimated_cost_microusd=800,
        ),
    )

    with pytest.raises(BudgetExceededError) as raised:
        account.reconcile(
            reservation_id=reservation.reservation_id,
            actual_usage=UsageVector(
                model_calls=1,
                input_tokens=120,
                output_tokens=50,
                estimated_cost_microusd=900,
            ),
        )
    assert raised.value.dimension == "input_tokens"
    snapshot = account.snapshot()
    assert snapshot.committed.input_tokens == 120
    assert snapshot.exhausted_dimension == "input_tokens"

    with pytest.raises(BudgetExceededError):
        account.reserve(
            kind=ReservationKind.MODEL,
            usage=UsageVector(model_calls=1),
        )


def test_cancelled_or_elapsed_budget_stops_future_invocations() -> None:
    now = [1_000]
    account = BudgetAccount(
        request_id=uuid4(),
        limits=TaskBudget(max_elapsed_ms=100),
        monotonic_millis=lambda: now[0],
    )
    now[0] = 1_101
    with pytest.raises(BudgetElapsedError):
        account.reserve(
            kind=ReservationKind.TOOL,
            usage=UsageVector(tool_calls=1),
        )

    second = BudgetAccount(
        request_id=uuid4(),
        limits=TaskBudget(),
        monotonic_millis=lambda: 100,
    )
    second.cancel()
    with pytest.raises(BudgetCancelledError):
        second.reserve(
            kind=ReservationKind.TOOL,
            usage=UsageVector(tool_calls=1),
        )


def test_reservation_kind_must_match_accounted_call() -> None:
    account = BudgetAccount(
        request_id=uuid4(),
        limits=TaskBudget(),
        monotonic_millis=lambda: 100,
    )
    with pytest.raises(ValueError, match="exactly one model call"):
        account.reserve(
            kind=ReservationKind.MODEL,
            usage=UsageVector(model_calls=0),
        )
