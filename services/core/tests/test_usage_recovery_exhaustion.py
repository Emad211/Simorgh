from __future__ import annotations

from uuid import uuid4

from simorgh_core.agents.budget import BudgetSnapshot
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
from simorgh_core.agents.task_store import InMemoryAgentTaskStore, new_task_store_entry
from simorgh_core.agents.usage_recovery import reconcile_task_store_invocation_usage


def test_usage_recovery_preserves_first_durable_exhausted_dimension() -> None:
    task = TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text="fixture",
        requested_outcome="fixture",
        explicit_task_kind=TaskKind.GENERAL_PLANNING,
        risk_class=RiskClass.PLANNING,
        execution_mode=ExecutionMode.PLAN,
        budget=TaskBudget(
            max_model_calls=0,
            max_tool_calls=0,
            max_input_tokens=0,
            max_output_tokens=0,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )
    task_store = InMemoryAgentTaskStore()
    task_store.upsert(
        new_task_store_entry(
            AgentTaskRecord(
                request_id=task.request_id,
                phase=AgentTaskPhase.UNKNOWN,
                created_at_ms=2_000,
                updated_at_ms=2_000,
                task=task,
                budget=BudgetSnapshot(
                    request_id=task.request_id,
                    limits=task.budget,
                    committed=UsageVector(tool_calls=1),
                    reserved=UsageVector(),
                    elapsed_ms=100,
                    cancelled=False,
                    exhausted_dimension="tool_calls",
                ),
                detail="fixture",
            )
        )
    )

    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    invocation_id = uuid4()
    invocation_store.begin(
        invocation_id=invocation_id,
        request_id=task.request_id,
        agent_id="system.router",
        agent_version="1.0.0",
        operation="model-fixture",
        input_fingerprint=canonical_fingerprint({"fixture": True}),
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="fake",
        model_id="cheap-fast",
    )
    invocation_store.reserve(
        invocation_id=invocation_id,
        usage=UsageVector(model_calls=1),
    )
    invocation = invocation_store.mark_unknown(
        invocation_id=invocation_id,
        failure_code="process_interrupted",
        failure_detail="fixture",
    )

    updated = reconcile_task_store_invocation_usage(
        task_store=task_store,
        invocation_records=[invocation],
        wall_clock_millis=lambda: 3_000,
        monotonic_millis=lambda: 500,
    )

    recovered = task_store.get(task.request_id)
    assert recovered is not None
    assert updated == 1
    assert recovered.record.budget.committed == UsageVector(
        model_calls=1,
        tool_calls=1,
    )
    assert recovered.record.budget.exhausted_dimension == "tool_calls"
