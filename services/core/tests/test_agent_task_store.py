from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.budget import BudgetSnapshot
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RiskClass,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.control_plane import AgentTaskControlPlane
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import (
    AgentTaskStoreConflictError,
    AgentTaskStoreCorruptionError,
    AgentTaskStoreSchemaError,
    SQLiteAgentTaskStore,
    new_task_store_entry,
)


def _task(
    *,
    request_id: UUID | None = None,
    text: str = "ریپازیتوری GitHub پروژه را بررسی کن",
) -> TaskEnvelope:
    return TaskEnvelope(
        request_id=request_id or uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=61_000,
        locale="fa-IR",
        input_text=text,
        requested_outcome="گزارش ساختاریافته وضعیت ریپازیتوری",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=0,
            max_tool_calls=4,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def _budget(
    task: TaskEnvelope,
    *,
    elapsed_ms: int = 0,
    cancelled: bool = False,
    committed: UsageVector | None = None,
    reserved: UsageVector | None = None,
) -> BudgetSnapshot:
    return BudgetSnapshot(
        request_id=task.request_id,
        limits=task.budget,
        committed=committed or UsageVector(),
        reserved=reserved or UsageVector(),
        elapsed_ms=elapsed_ms,
        cancelled=cancelled,
    )


def _decision(task: TaskEnvelope) -> RoutingDecision:
    return RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="github.read",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        candidate_agent_ids=("github.read",),
        reason="explicit repository task selected github.read",
    )


def _record(
    task: TaskEnvelope,
    *,
    phase: AgentTaskPhase,
    created_at_ms: int = 2_000,
    updated_at_ms: int = 2_000,
    budget: BudgetSnapshot | None = None,
    decision: RoutingDecision | None = None,
    cancel_reason: str | None = None,
    detail: str = "fixture",
) -> AgentTaskRecord:
    return AgentTaskRecord(
        request_id=task.request_id,
        phase=phase,
        created_at_ms=created_at_ms,
        updated_at_ms=updated_at_ms,
        task=task,
        routing_decision=decision,
        budget=budget or _budget(task),
        cancel_reason=cancel_reason,
        detail=detail,
    )


def _routing(task: TaskEnvelope) -> AgentTaskRecord:
    return _record(task, phase=AgentTaskPhase.ROUTING)


def _routed(task: TaskEnvelope, *, updated_at_ms: int = 2_100) -> AgentTaskRecord:
    return _record(
        task,
        phase=AgentTaskPhase.ROUTED,
        updated_at_ms=updated_at_ms,
        budget=_budget(task, elapsed_ms=100),
        decision=_decision(task),
    )


def test_sqlite_round_trip_and_reopen_preserve_exact_task_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    task = _task()
    store = SQLiteAgentTaskStore(path)
    store.upsert(new_task_store_entry(_routing(task)))
    routed = _routed(task)
    store.upsert(new_task_store_entry(routed))
    store.close()

    reopened = SQLiteAgentTaskStore(path)
    loaded = reopened.get(task.request_id)

    assert loaded is not None
    assert loaded.record == routed
    assert loaded.task_fingerprint == new_task_store_entry(routed).task_fingerprint
    assert reopened.load() == [loaded]
    reopened.close()


def test_same_request_id_with_changed_task_content_conflicts(tmp_path: Path) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    request_id = uuid4()
    store = SQLiteAgentTaskStore(path)
    store.upsert(new_task_store_entry(_routing(_task(request_id=request_id))))

    changed = _routing(
        _task(
            request_id=request_id,
            text="این محتوای متفاوت نباید همان هویت را تصاحب کند",
        )
    )
    with pytest.raises(
        AgentTaskStoreConflictError,
        match="fingerprint is immutable",
    ):
        store.upsert(new_task_store_entry(changed))
    store.close()


def test_cancellation_survives_store_restart(tmp_path: Path) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    task = _task()
    store = SQLiteAgentTaskStore(path)
    store.upsert(new_task_store_entry(_routing(task)))
    routed = _routed(task)
    store.upsert(new_task_store_entry(routed))
    cancelled = _record(
        task,
        phase=AgentTaskPhase.CANCELLED,
        updated_at_ms=2_200,
        budget=_budget(task, elapsed_ms=200, cancelled=True),
        decision=routed.routing_decision,
        cancel_reason="کاربر گفت لغو",
        detail="کاربر گفت لغو",
    )
    store.upsert(new_task_store_entry(cancelled))
    store.close()

    reopened = SQLiteAgentTaskStore(path)
    loaded = reopened.get(task.request_id)

    assert loaded is not None
    assert loaded.record.phase == AgentTaskPhase.CANCELLED
    assert loaded.record.cancel_reason == "کاربر گفت لغو"
    assert loaded.record.budget.cancelled
    reopened.close()


def test_interrupted_routing_recovers_unknown_without_router_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    task = _task()
    store = SQLiteAgentTaskStore(path)
    store.upsert(new_task_store_entry(_routing(task)))
    store.close()

    router = CountingRouter()
    reopened = SQLiteAgentTaskStore(path)
    control_plane = AgentTaskControlPlane(
        router=router,  # type: ignore[arg-type]
        store=reopened,
        wall_clock_millis=lambda: 3_000,
        monotonic_millis=lambda: 500,
    )

    recovered = asyncio.run(control_plane.get(task.request_id))
    replay = asyncio.run(control_plane.submit(task))

    assert recovered.phase == AgentTaskPhase.UNKNOWN
    assert "automatic replay is blocked" in recovered.detail
    assert replay == recovered
    assert router.calls == 0
    persisted = reopened.get(task.request_id)
    assert persisted is not None
    assert persisted.record == recovered
    reopened.close()


def test_invalid_terminal_transition_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    task = _task()
    store = SQLiteAgentTaskStore(path)
    store.upsert(new_task_store_entry(_routing(task)))
    store.upsert(new_task_store_entry(_routed(task)))

    expired = _record(
        task,
        phase=AgentTaskPhase.EXPIRED,
        updated_at_ms=2_200,
        budget=_budget(task, elapsed_ms=200),
        detail="invalid late expiry",
    )
    with pytest.raises(
        AgentTaskStoreConflictError,
        match="invalid durable agent-task phase transition",
    ):
        store.upsert(new_task_store_entry(expired))
    store.close()


def test_payload_hash_corruption_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    task = _task()
    store = SQLiteAgentTaskStore(path)
    store.upsert(new_task_store_entry(_routing(task)))
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE agent_task_records SET payload_json = payload_json || ' '",
    )
    connection.commit()
    connection.close()

    reopened = SQLiteAgentTaskStore(path)
    with pytest.raises(AgentTaskStoreCorruptionError, match="hash mismatch"):
        reopened.load()
    reopened.close()


def test_indexed_column_tampering_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    task = _task()
    store = SQLiteAgentTaskStore(path)
    store.upsert(new_task_store_entry(_routing(task)))
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE agent_task_records SET phase = 'unknown' WHERE request_id = ?",
        (str(task.request_id),),
    )
    connection.commit()
    connection.close()

    reopened = SQLiteAgentTaskStore(path)
    with pytest.raises(
        AgentTaskStoreCorruptionError,
        match="indexed columns do not match payload",
    ):
        reopened.load()
    reopened.close()


def test_unsupported_store_schema_fails_at_open(tmp_path: Path) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    store = SQLiteAgentTaskStore(path)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        """
        UPDATE agent_task_store_metadata
        SET value = '999'
        WHERE key = 'schema_version'
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(AgentTaskStoreSchemaError, match="unsupported"):
        SQLiteAgentTaskStore(path)


def test_terminal_pruning_never_removes_nonterminal_routing_task(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agent-tasks.sqlite3"
    store = SQLiteAgentTaskStore(path, max_terminal_records=1)
    routing_task = _task()
    first_terminal = _task()
    latest_terminal = _task()

    store.upsert(new_task_store_entry(_routing(routing_task)))
    store.upsert(
        new_task_store_entry(
            _record(
                first_terminal,
                phase=AgentTaskPhase.EXPIRED,
                created_at_ms=2_100,
                updated_at_ms=2_100,
                detail="first terminal",
            )
        )
    )
    store.upsert(
        new_task_store_entry(
            _record(
                latest_terminal,
                phase=AgentTaskPhase.EXPIRED,
                created_at_ms=2_200,
                updated_at_ms=2_200,
                detail="latest terminal",
            )
        )
    )

    loaded_ids = {entry.request_id for entry in store.load()}
    assert routing_task.request_id in loaded_ids
    assert latest_terminal.request_id in loaded_ids
    assert first_terminal.request_id not in loaded_ids
    store.close()


class CountingRouter:
    def __init__(self) -> None:
        self.calls = 0

    async def route(self, **_kwargs: object) -> RoutingDecision:
        self.calls += 1
        raise AssertionError("recovered task must not be routed automatically")
