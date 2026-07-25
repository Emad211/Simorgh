from __future__ import annotations

from uuid import uuid4

from simorgh_core.agents.budget import BudgetAccount, BudgetSnapshot
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RiskClass,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
    canonical_fingerprint,
)
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import (
    InMemoryAgentTaskStore,
    new_task_store_entry,
)
from simorgh_core.agents.usage_recovery import (
    reconcile_task_store_invocation_usage,
)


def _task(*, budget: TaskBudget | None = None) -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text="وضعیت پروژه را بررسی کن",
        requested_outcome="گزارش پایدار",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=budget
        or TaskBudget(
            max_model_calls=2,
            max_tool_calls=4,
            max_input_tokens=10_000,
            max_output_tokens=2_000,
            max_estimated_cost_microusd=100_000,
            max_elapsed_ms=30_000,
            max_retries=1,
            max_parallel_branches=1,
        ),
    )


def _task_record(
    task: TaskEnvelope,
    *,
    committed: UsageVector | None = None,
    cancelled: bool = False,
) -> AgentTaskRecord:
    snapshot = BudgetSnapshot(
        request_id=task.request_id,
        limits=task.budget,
        committed=committed or UsageVector(),
        reserved=UsageVector(),
        elapsed_ms=100,
        cancelled=cancelled,
    )
    return AgentTaskRecord(
        request_id=task.request_id,
        phase=(AgentTaskPhase.CANCELLED if cancelled else AgentTaskPhase.UNKNOWN),
        created_at_ms=2_000,
        updated_at_ms=2_000,
        task=task,
        budget=snapshot,
        cancel_reason="لغو پایدار" if cancelled else None,
        detail="fixture",
    )


def _unknown_model_invocation(
    task: TaskEnvelope,
    *,
    usage: UsageVector,
):
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    invocation_id = uuid4()
    store.begin(
        invocation_id=invocation_id,
        request_id=task.request_id,
        agent_id="system.specialist-router",
        agent_version="1.0.0",
        operation="classify-primary-specialist",
        input_fingerprint=canonical_fingerprint({"task": str(task.request_id)}),
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="fake",
        model_id="cheap-fast",
    )
    store.reserve(invocation_id=invocation_id, usage=usage)
    return store.mark_unknown(
        invocation_id=invocation_id,
        failure_code="process_interrupted",
        failure_detail="fixture uncertainty",
    )


def test_recovery_raises_task_usage_to_durable_invocation_truth_once() -> None:
    task = _task()
    task_store = InMemoryAgentTaskStore()
    task_store.upsert(new_task_store_entry(_task_record(task)))
    usage = UsageVector(
        model_calls=1,
        input_tokens=500,
        output_tokens=200,
        estimated_cost_microusd=3_000,
    )
    invocation = _unknown_model_invocation(task, usage=usage)

    first = reconcile_task_store_invocation_usage(
        task_store=task_store,
        invocation_records=[invocation],
        wall_clock_millis=lambda: 3_000,
        monotonic_millis=lambda: 500,
    )
    second = reconcile_task_store_invocation_usage(
        task_store=task_store,
        invocation_records=[invocation],
        wall_clock_millis=lambda: 4_000,
        monotonic_millis=lambda: 600,
    )

    recovered = task_store.get(task.request_id)
    assert recovered is not None
    assert first == 1
    assert second == 0
    assert recovered.record.phase == AgentTaskPhase.UNKNOWN
    assert recovered.record.budget.committed == usage
    assert recovered.record.budget.reserved == UsageVector()


def test_recovery_uses_aggregate_invocation_usage_without_double_counting() -> None:
    task = _task()
    task_store = InMemoryAgentTaskStore()
    already_accounted = UsageVector(
        model_calls=1,
        input_tokens=100,
        output_tokens=20,
        estimated_cost_microusd=1_000,
    )
    task_store.upsert(
        new_task_store_entry(
            _task_record(task, committed=already_accounted)
        )
    )
    first_usage = already_accounted
    second_usage = UsageVector(
        model_calls=1,
        input_tokens=300,
        output_tokens=40,
        estimated_cost_microusd=2_000,
    )
    invocations = [
        _unknown_model_invocation(task, usage=first_usage),
        _unknown_model_invocation(task, usage=second_usage),
    ]

    updated = reconcile_task_store_invocation_usage(
        task_store=task_store,
        invocation_records=invocations,
        wall_clock_millis=lambda: 3_000,
        monotonic_millis=lambda: 500,
    )

    recovered = task_store.get(task.request_id)
    assert recovered is not None
    assert updated == 1
    assert recovered.record.budget.committed == first_usage.plus(second_usage)


def test_recovery_preserves_cancellation_and_marks_overage_exhausted() -> None:
    task = _task(
        budget=TaskBudget(
            max_model_calls=0,
            max_tool_calls=0,
            max_input_tokens=0,
            max_output_tokens=0,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        )
    )
    task_store = InMemoryAgentTaskStore()
    task_store.upsert(
        new_task_store_entry(_task_record(task, cancelled=True))
    )
    usage = UsageVector(model_calls=1, input_tokens=10)
    invocation = _unknown_model_invocation(task, usage=usage)

    updated = reconcile_task_store_invocation_usage(
        task_store=task_store,
        invocation_records=[invocation],
        wall_clock_millis=lambda: 3_000,
        monotonic_millis=lambda: 500,
    )

    recovered = task_store.get(task.request_id)
    assert recovered is not None
    assert updated == 1
    assert recovered.record.phase == AgentTaskPhase.CANCELLED
    assert recovered.record.cancel_reason == "لغو پایدار"
    assert recovered.record.budget.cancelled
    assert recovered.record.budget.committed == usage
    assert recovered.record.budget.exhausted_dimension == "model_calls"


def test_recovery_ignores_invocations_without_retained_parent_task() -> None:
    task = _task()
    task_store = InMemoryAgentTaskStore()
    invocation = _unknown_model_invocation(
        task,
        usage=UsageVector(model_calls=1),
    )

    updated = reconcile_task_store_invocation_usage(
        task_store=task_store,
        invocation_records=[invocation],
    )

    assert updated == 0
    assert task_store.load() == []
