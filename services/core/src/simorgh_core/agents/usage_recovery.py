from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from uuid import UUID

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import InvocationRecord
from simorgh_core.agents.task_state import AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStore, new_task_store_entry

_USAGE_DIMENSIONS = (
    "model_calls",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "estimated_cost_microusd",
    "retries",
    "parallel_branches",
)


def reconcile_task_store_invocation_usage(
    *,
    task_store: AgentTaskStore,
    invocation_records: Iterable[InvocationRecord],
    wall_clock_millis: Callable[[], int] | None = None,
    monotonic_millis: Callable[[], int] | None = None,
) -> int:
    """Raise parent task accounting to at least durable invocation truth.

    Invocation usage is summed by request identity. Existing task usage is then merged
    component-wise with that aggregate, so a task already accounting for the same calls is not
    charged twice while a crash-recovered invocation can never remain invisible at task level.
    """

    usage_by_request = _usage_by_request(invocation_records)
    if not usage_by_request:
        return 0

    now = wall_clock_millis or (lambda: int(time.time() * 1_000))
    updated = 0
    for entry in task_store.load():
        durable_usage = usage_by_request.get(entry.request_id)
        if durable_usage is None:
            continue
        record = entry.record
        merged_usage = _componentwise_max(
            record.budget.committed,
            durable_usage,
        )
        if merged_usage == record.budget.committed:
            continue

        restored_budget = BudgetAccount.restore(
            record.budget.model_copy(
                update={
                    "committed": merged_usage,
                    "reserved": UsageVector(),
                }
            ),
            monotonic_millis=monotonic_millis,
        ).snapshot()
        candidate = AgentTaskRecord(
            request_id=record.request_id,
            phase=record.phase,
            created_at_ms=record.created_at_ms,
            updated_at_ms=max(record.updated_at_ms, max(0, int(now()))),
            task=record.task,
            routing_decision=record.routing_decision,
            budget=restored_budget,
            cancel_reason=record.cancel_reason,
            detail=record.detail,
        )
        task_store.upsert(new_task_store_entry(candidate))
        updated += 1
    return updated


def _usage_by_request(
    records: Iterable[InvocationRecord],
) -> dict[UUID, UsageVector]:
    grouped: dict[UUID, UsageVector] = {}
    for record in records:
        grouped[record.request_id] = grouped.get(
            record.request_id,
            UsageVector(),
        ).plus(record.committed_usage)
    return grouped


def _componentwise_max(left: UsageVector, right: UsageVector) -> UsageVector:
    return UsageVector(
        **{
            dimension: max(
                getattr(left, dimension),
                getattr(right, dimension),
            )
            for dimension in _USAGE_DIMENSIONS
        }
    )
