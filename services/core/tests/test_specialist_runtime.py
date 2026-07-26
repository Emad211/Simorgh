from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
    InvocationPhase,
    InvocationRecord,
    InvocationStart,
    InvocationStoreCorruptionError,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistCapabilitySet,
    SpecialistExecutionCancelledError,
    SpecialistExecutionOutcome,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    SpecialistExecutorRegistry,
    SpecialistReplayDisposition,
    SpecialistResultContractError,
    UnknownSpecialistExecutorError,
    build_specialist_execution_request,
)
from simorgh_core.agents.specialist_runtime import (
    SpecialistExecutionExpiredError,
    SpecialistExecutionRuntime,
    SpecialistExecutionStoreError,
    SpecialistRuntimeError,
    specialist_execution_fingerprint,
)

_CONTEXT_FINGERPRINT = "d" * 64


def _task(*, deadline_at_ms: int = 60_000) -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=deadline_at_ms,
        locale="fa-IR",
        input_text="برای توسعه سیمرغ یک برنامه مرحله‌ای بساز",
        requested_outcome="برنامه توسعه ساختاریافته",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
        allowed_data_sources=frozenset({"github"}),
    )


def _decision(task: TaskEnvelope) -> RoutingDecision:
    return RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="development.planner",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="explicit development fixture",
    )


def _capabilities() -> SpecialistCapabilitySet:
    return SpecialistCapabilitySet(proposal_allowed=True)


def _budget(task: TaskEnvelope) -> BudgetAccount:
    definition = default_specialist_registry().get("development.planner")
    request = build_specialist_execution_request(
        task=task,
        decision=_decision(task),
        definition=definition,
        invocation_id=uuid4(),
        context_fingerprint=_CONTEXT_FINGERPRINT,
        requested_capabilities=_capabilities(),
        created_at_ms=task.received_at_ms,
    )
    return BudgetAccount(
        request_id=task.request_id,
        limits=request.effective_budget,
        monotonic_millis=lambda: 100,
    )


class CountingProposalExecutor:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        wrong_identity: bool = False,
        committed_usage: UsageVector | None = None,
    ) -> None:
        self.calls = 0
        self.error = error
        self.wrong_identity = wrong_identity
        self.committed_usage = committed_usage or UsageVector()

    @property
    def agent_id(self) -> str:
        return "development.planner"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    @property
    def output_contract(self) -> str:
        return "simorgh.typed-plan.v1"

    async def execute(
        self,
        *,
        request: SpecialistExecutionRequest,
        cancellation: SpecialistCancellation,
        budget: BudgetAccount,
    ) -> SpecialistExecutionResult:
        del budget
        cancellation.raise_if_cancelled()
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SpecialistExecutionResult(
            request_id=request.request_id,
            invocation_id=request.invocation_id,
            agent_id=("seo.planner" if self.wrong_identity else request.agent_id),
            agent_version=request.agent_version,
            effect=InvocationEffect.PROPOSAL,
            outcome=SpecialistExecutionOutcome.COMPLETED,
            output_contract=request.output_contract,
            payload={"summary": "پاسخ پایدار", "steps": ["قرارداد", "تست"]},
            committed_usage=self.committed_usage,
            started_at_ms=2_000,
            completed_at_ms=3_000,
        )


class BeginFailingInvocationStore(InMemoryInvocationStore):
    def begin(
        self,
        *,
        invocation_id: UUID,
        request_id: UUID,
        agent_id: str,
        agent_version: str,
        operation: str,
        input_fingerprint: str,
        kind: InvocationKind = InvocationKind.SPECIALIST,
        effect: InvocationEffect = InvocationEffect.READ_ONLY,
        provider_id: str | None = None,
        model_id: str | None = None,
        tool_id: str | None = None,
        connector_id: str | None = None,
        parent_invocation_id: UUID | None = None,
        attempt: int = 1,
    ) -> InvocationStart:
        del (
            invocation_id,
            request_id,
            agent_id,
            agent_version,
            operation,
            input_fingerprint,
            kind,
            effect,
            provider_id,
            model_id,
            tool_id,
            connector_id,
            parent_invocation_id,
            attempt,
        )
        raise InvocationStoreCorruptionError("simulated begin failure")


def _runtime(
    *,
    executor: CountingProposalExecutor,
    store: InMemoryInvocationStore | SQLiteInvocationStore,
    now_ms: int = 2_000,
) -> SpecialistExecutionRuntime:
    return SpecialistExecutionRuntime(
        executor_registry=SpecialistExecutorRegistry((executor,)),
        invocation_store=store,
        wall_clock_millis=lambda: now_ms,
    )


@pytest.mark.asyncio
async def test_specialist_executes_once_and_replays_without_new_usage() -> None:
    task = _task()
    invocation_id = uuid4()
    executor = CountingProposalExecutor()
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    runtime = _runtime(executor=executor, store=store)
    first_budget = _budget(task)

    first = await runtime.execute(
        task=task,
        decision=_decision(task),
        definition=default_specialist_registry().get("development.planner"),
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
        capabilities=_capabilities(),
        budget=first_budget,
    )
    replay_budget = _budget(task)
    replay = await runtime.execute(
        task=task,
        decision=_decision(task),
        definition=default_specialist_registry().get("development.planner"),
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
        capabilities=_capabilities(),
        budget=replay_budget,
    )

    assert executor.calls == 1
    assert first.replay == SpecialistReplayDisposition.FRESH
    assert replay.replay == SpecialistReplayDisposition.REPLAYED
    assert replay.payload == first.payload
    assert replay_budget.snapshot().committed == UsageVector()
    assert replay_budget.snapshot().reserved == UsageVector()


@pytest.mark.asyncio
async def test_sqlite_replay_survives_restart_deadline_and_missing_executor(
    tmp_path: Path,
) -> None:
    path = tmp_path / "specialist-invocations.sqlite3"
    task = _task(deadline_at_ms=5_000)
    invocation_id = uuid4()
    executor = CountingProposalExecutor()
    first_store = SQLiteInvocationStore(path, wall_clock_millis=lambda: 2_000)
    first_runtime = _runtime(executor=executor, store=first_store, now_ms=2_000)

    first = await first_runtime.execute(
        task=task,
        decision=_decision(task),
        definition=default_specialist_registry().get("development.planner"),
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
        capabilities=_capabilities(),
        budget=_budget(task),
    )
    first_store.close()

    replay_store = SQLiteInvocationStore(path, wall_clock_millis=lambda: 90_000)
    replay_runtime = SpecialistExecutionRuntime(
        executor_registry=SpecialistExecutorRegistry(),
        invocation_store=replay_store,
        wall_clock_millis=lambda: 90_000,
    )
    replay = await replay_runtime.execute(
        task=task,
        decision=_decision(task),
        definition=default_specialist_registry().get("development.planner"),
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
        capabilities=_capabilities(),
        budget=_budget(task),
    )

    assert executor.calls == 1
    assert replay.replay == SpecialistReplayDisposition.REPLAYED
    assert replay.payload == first.payload
    replay_store.close()


@pytest.mark.asyncio
async def test_changed_context_under_same_invocation_fails_before_executor() -> None:
    task = _task()
    invocation_id = uuid4()
    executor = CountingProposalExecutor()
    store = InMemoryInvocationStore()
    runtime = _runtime(executor=executor, store=store)

    await runtime.execute(
        task=task,
        decision=_decision(task),
        definition=default_specialist_registry().get("development.planner"),
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
        capabilities=_capabilities(),
        budget=_budget(task),
    )

    with pytest.raises(SpecialistExecutionStoreError, match="durably claimed"):
        await runtime.execute(
            task=task,
            decision=_decision(task),
            definition=default_specialist_registry().get("development.planner"),
            invocation_id=invocation_id,
            context_fingerprint="e" * 64,
            capabilities=_capabilities(),
            budget=_budget(task),
        )
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_cancellation_before_executor_is_durably_terminal() -> None:
    task = _task()
    invocation_id = uuid4()
    executor = CountingProposalExecutor()
    store = InMemoryInvocationStore()
    runtime = _runtime(executor=executor, store=store)
    cancellation = SpecialistCancellation()
    cancellation.cancel("لغو کاربر")

    with pytest.raises(SpecialistExecutionCancelledError, match="لغو کاربر"):
        await runtime.execute(
            task=task,
            decision=_decision(task),
            definition=default_specialist_registry().get("development.planner"),
            invocation_id=invocation_id,
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=_capabilities(),
            budget=_budget(task),
            cancellation=cancellation,
        )

    assert executor.calls == 0
    assert store.get(invocation_id).state == InvocationPhase.CANCELLED


@pytest.mark.asyncio
async def test_expired_execution_is_durably_terminal_before_executor() -> None:
    task = _task(deadline_at_ms=1_500)
    invocation_id = uuid4()
    executor = CountingProposalExecutor()
    store = InMemoryInvocationStore()
    runtime = _runtime(executor=executor, store=store, now_ms=2_000)

    with pytest.raises(SpecialistExecutionExpiredError, match="deadline"):
        await runtime.execute(
            task=task,
            decision=_decision(task),
            definition=default_specialist_registry().get("development.planner"),
            invocation_id=invocation_id,
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=_capabilities(),
            budget=_budget(task),
        )

    assert executor.calls == 0
    assert store.get(invocation_id).state == InvocationPhase.EXPIRED


@pytest.mark.asyncio
async def test_store_begin_failure_prevents_executor_entry() -> None:
    task = _task()
    executor = CountingProposalExecutor()
    runtime = SpecialistExecutionRuntime(
        executor_registry=SpecialistExecutorRegistry((executor,)),
        invocation_store=BeginFailingInvocationStore(),
        wall_clock_millis=lambda: 2_000,
    )

    with pytest.raises(SpecialistExecutionStoreError, match="durably claimed"):
        await runtime.execute(
            task=task,
            decision=_decision(task),
            definition=default_specialist_registry().get("development.planner"),
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=_capabilities(),
            budget=_budget(task),
        )

    assert executor.calls == 0


@pytest.mark.asyncio
async def test_wrong_result_identity_becomes_durable_failure() -> None:
    task = _task()
    invocation_id = uuid4()
    executor = CountingProposalExecutor(wrong_identity=True)
    store = InMemoryInvocationStore()
    runtime = _runtime(executor=executor, store=store)

    with pytest.raises(SpecialistResultContractError, match="typed contract"):
        await runtime.execute(
            task=task,
            decision=_decision(task),
            definition=default_specialist_registry().get("development.planner"),
            invocation_id=invocation_id,
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=_capabilities(),
            budget=_budget(task),
        )

    record = store.get(invocation_id)
    assert record.state == InvocationPhase.FAILED
    assert record.failure_code == "specialist_result_contract_invalid"
    assert record.result_payload is None


@pytest.mark.asyncio
async def test_native_executor_cannot_bypass_model_tool_accounting() -> None:
    task = _task()
    invocation_id = uuid4()
    executor = CountingProposalExecutor(
        committed_usage=UsageVector(model_calls=1, input_tokens=10, output_tokens=5)
    )
    store = InMemoryInvocationStore()
    runtime = _runtime(executor=executor, store=store)

    with pytest.raises(SpecialistResultContractError, match="typed contract"):
        await runtime.execute(
            task=task,
            decision=_decision(task),
            definition=default_specialist_registry().get("development.planner"),
            invocation_id=invocation_id,
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=_capabilities(),
            budget=_budget(task),
        )

    assert store.get(invocation_id).state == InvocationPhase.FAILED


@pytest.mark.asyncio
async def test_executor_exception_text_is_not_persisted() -> None:
    task = _task()
    invocation_id = uuid4()
    private_marker = "PRIVATE_SPECIALIST_EXCEPTION_9f02"
    executor = CountingProposalExecutor(
        error=RuntimeError(f"failure near {private_marker}")
    )
    store = InMemoryInvocationStore()
    runtime = _runtime(executor=executor, store=store)

    with pytest.raises(SpecialistRuntimeError, match="implementation failed"):
        await runtime.execute(
            task=task,
            decision=_decision(task),
            definition=default_specialist_registry().get("development.planner"),
            invocation_id=invocation_id,
            context_fingerprint=_CONTEXT_FINGERPRINT,
            capabilities=_capabilities(),
            budget=_budget(task),
        )

    record: InvocationRecord = store.get(invocation_id)
    assert record.failure_detail == "RuntimeError"
    assert private_marker not in record.model_dump_json()


def test_specialist_fingerprint_ignores_creation_time_but_not_context() -> None:
    task = _task()
    definition = default_specialist_registry().get("development.planner")
    invocation_id = uuid4()
    first = build_specialist_execution_request(
        task=task,
        decision=_decision(task),
        definition=definition,
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
        requested_capabilities=_capabilities(),
        created_at_ms=1_000,
    )
    second = first.model_copy(update={"created_at_ms": 2_000})
    changed_context = first.model_copy(update={"context_fingerprint": "e" * 64})

    assert specialist_execution_fingerprint(first) == specialist_execution_fingerprint(second)
    assert specialist_execution_fingerprint(first) != specialist_execution_fingerprint(
        changed_context
    )


def test_missing_executor_is_required_for_new_execution_only() -> None:
    definition = default_specialist_registry().get("development.planner")
    with pytest.raises(UnknownSpecialistExecutorError):
        SpecialistExecutorRegistry().require_definition(definition)
