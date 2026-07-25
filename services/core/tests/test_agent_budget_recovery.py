from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.budget import (
    BudgetAccount,
    BudgetCancelledError,
    BudgetExceededError,
    BudgetSnapshot,
    ReservationKind,
)
from simorgh_core.agents.contracts import TaskBudget, UsageVector


def test_restore_commits_unresolved_reservations_and_preserves_elapsed_time() -> None:
    request_id = uuid4()
    now = [5_000]
    snapshot = BudgetSnapshot(
        request_id=request_id,
        limits=TaskBudget(
            max_model_calls=2,
            max_tool_calls=3,
            max_input_tokens=10_000,
            max_output_tokens=2_000,
            max_estimated_cost_microusd=50_000,
            max_elapsed_ms=20_000,
            max_retries=1,
            max_parallel_branches=1,
        ),
        committed=UsageVector(
            model_calls=1,
            input_tokens=400,
            output_tokens=100,
            estimated_cost_microusd=2_000,
        ),
        reserved=UsageVector(
            tool_calls=1,
            input_tokens=50,
            estimated_cost_microusd=500,
        ),
        elapsed_ms=2_500,
        cancelled=False,
    )

    restored = BudgetAccount.restore(
        snapshot,
        monotonic_millis=lambda: now[0],
    )
    initial = restored.snapshot()

    assert initial.reserved == UsageVector()
    assert initial.committed.model_calls == 1
    assert initial.committed.tool_calls == 1
    assert initial.committed.input_tokens == 450
    assert initial.committed.estimated_cost_microusd == 2_500
    assert initial.elapsed_ms == 2_500

    now[0] = 5_125
    assert restored.snapshot().elapsed_ms == 2_625


def test_restored_cancelled_budget_rejects_every_future_reservation() -> None:
    request_id = uuid4()
    limits = TaskBudget()
    restored = BudgetAccount.restore(
        BudgetSnapshot(
            request_id=request_id,
            limits=limits,
            committed=UsageVector(),
            reserved=UsageVector(),
            elapsed_ms=100,
            cancelled=True,
        ),
        monotonic_millis=lambda: 10_000,
    )

    with pytest.raises(BudgetCancelledError):
        restored.reserve(
            kind=ReservationKind.TOOL,
            usage=UsageVector(tool_calls=1),
        )


def test_restored_overage_is_truthfully_retained_and_blocks_future_calls() -> None:
    request_id = uuid4()
    limits = TaskBudget(
        max_model_calls=1,
        max_tool_calls=0,
        max_input_tokens=100,
        max_output_tokens=100,
        max_estimated_cost_microusd=1_000,
        max_elapsed_ms=10_000,
        max_retries=0,
        max_parallel_branches=1,
    )
    restored = BudgetAccount.restore(
        BudgetSnapshot(
            request_id=request_id,
            limits=limits,
            committed=UsageVector(
                model_calls=1,
                input_tokens=80,
                output_tokens=20,
                estimated_cost_microusd=800,
            ),
            reserved=UsageVector(
                input_tokens=40,
                estimated_cost_microusd=300,
            ),
            elapsed_ms=200,
            cancelled=False,
        ),
        monotonic_millis=lambda: 1_000,
    )

    recovered = restored.snapshot()
    assert recovered.committed.input_tokens == 120
    assert recovered.committed.estimated_cost_microusd == 1_100
    assert recovered.exhausted_dimension == "input_tokens"

    with pytest.raises(BudgetExceededError) as raised:
        restored.reserve(
            kind=ReservationKind.MODEL,
            usage=UsageVector(model_calls=1),
        )
    assert raised.value.dimension == "input_tokens"


def test_restore_rejects_snapshot_for_another_request_or_budget() -> None:
    request_id = uuid4()
    snapshot = BudgetSnapshot(
        request_id=request_id,
        limits=TaskBudget(),
        committed=UsageVector(),
        reserved=UsageVector(),
        elapsed_ms=0,
        cancelled=False,
    )

    with pytest.raises(ValueError, match="request_id"):
        BudgetAccount(
            request_id=uuid4(),
            limits=snapshot.limits,
            initial_snapshot=snapshot,
        )

    with pytest.raises(ValueError, match="limits"):
        BudgetAccount(
            request_id=request_id,
            limits=TaskBudget(max_model_calls=2),
            initial_snapshot=snapshot,
        )
