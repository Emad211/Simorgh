from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    TaskEnvelope,
    TaskKind,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import InvocationEffect
from simorgh_core.agents.specialist_execution import (
    DuplicateSpecialistExecutorError,
    SpecialistCancellation,
    SpecialistCapabilitySet,
    SpecialistExecutionCancelledError,
    SpecialistExecutionOutcome,
    SpecialistExecutionPolicyError,
    SpecialistExecutionResult,
    SpecialistExecutorRegistry,
    StaticProposalSpecialistExecutor,
    UnknownSpecialistExecutorError,
    build_specialist_execution_request,
)

_CONTEXT_FINGERPRINT = "c" * 64


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="برای توسعه نسخه بعدی سیمرغ برنامه اجرایی بساز",
        requested_outcome="برنامه ساختاریافته توسعه",
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
        reason="explicit development task fixture",
    )


def _capabilities() -> SpecialistCapabilitySet:
    return SpecialistCapabilitySet(
        proposal_allowed=True,
        tool_ids=frozenset({"github.search"}),
        connector_ids=frozenset({"github"}),
    )


def _request() -> tuple[TaskEnvelope, object]:
    task = _task()
    definition = default_specialist_registry().get("development.planner")
    request = build_specialist_execution_request(
        task=task,
        decision=_decision(task),
        definition=definition,
        invocation_id=uuid4(),
        context_fingerprint=_CONTEXT_FINGERPRINT,
        requested_capabilities=_capabilities(),
        created_at_ms=2_000,
    )
    return task, request


def _executor() -> StaticProposalSpecialistExecutor:
    return StaticProposalSpecialistExecutor(
        agent_id="development.planner",
        agent_version="1.0.0",
        output_contract="simorgh.typed-plan.v1",
        payload={
            "summary": "برنامه محلی و بدون فراخوانی خارجی",
            "steps": ["تعریف قرارداد", "اجرای تست"],
        },
        wall_clock_millis=lambda: 3_000,
    )


def test_request_is_derived_from_routed_task_and_policy_intersection() -> None:
    task, request = _request()

    assert request.request_id == task.request_id
    assert request.agent_id == "development.planner"
    assert request.agent_version == "1.0.0"
    assert request.effect == InvocationEffect.PROPOSAL
    assert request.capabilities == _capabilities()
    assert request.effective_budget.max_model_calls == min(
        task.budget.max_model_calls,
        default_specialist_registry().get("development.planner").budget_ceiling.max_model_calls,
    )
    assert request.parent_invocation_id is None
    assert request.attempt == 1


def test_request_task_fingerprint_is_stable_for_data_source_order() -> None:
    first = _task()
    second = first.model_copy(
        update={"allowed_data_sources": frozenset({"github", "docs"})}
    )
    third = first.model_copy(
        update={"allowed_data_sources": frozenset({"docs", "github"})}
    )
    definition = default_specialist_registry().get("development.planner")

    second_request = build_specialist_execution_request(
        task=second,
        decision=_decision(second),
        definition=definition,
        invocation_id=uuid4(),
        context_fingerprint=_CONTEXT_FINGERPRINT,
        requested_capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        created_at_ms=2_000,
    )
    third_request = build_specialist_execution_request(
        task=third,
        decision=_decision(third),
        definition=definition,
        invocation_id=uuid4(),
        context_fingerprint=_CONTEXT_FINGERPRINT,
        requested_capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        created_at_ms=2_000,
    )

    assert second_request.task_fingerprint == third_request.task_fingerprint


@pytest.mark.parametrize(
    "capabilities, message",
    [
        (
            SpecialistCapabilitySet(
                proposal_allowed=True,
                tool_ids=frozenset({"gmail.send"}),
            ),
            "tools exceed",
        ),
        (
            SpecialistCapabilitySet(
                proposal_allowed=True,
                connector_ids=frozenset({"gmail"}),
            ),
            "connectors exceed",
        ),
        (
            SpecialistCapabilitySet(
                proposal_allowed=True,
                typed_mutation_allowed=True,
            ),
            "mutation authority exceeds",
        ),
    ],
)
def test_capability_widening_is_rejected(
    capabilities: SpecialistCapabilitySet,
    message: str,
) -> None:
    task = _task()
    definition = default_specialist_registry().get("development.planner")

    with pytest.raises(SpecialistExecutionPolicyError, match=message):
        build_specialist_execution_request(
            task=task,
            decision=_decision(task),
            definition=definition,
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
            requested_capabilities=capabilities,
            created_at_ms=2_000,
        )


def test_proposal_execution_requires_explicit_proposal_capability() -> None:
    task = _task()
    definition = default_specialist_registry().get("development.planner")

    with pytest.raises(SpecialistExecutionPolicyError, match="proposal capability"):
        build_specialist_execution_request(
            task=task,
            decision=_decision(task),
            definition=definition,
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
            requested_capabilities=SpecialistCapabilitySet(),
            created_at_ms=2_000,
        )


def test_wrong_routing_version_is_rejected() -> None:
    task = _task()
    definition = default_specialist_registry().get("development.planner")
    decision = _decision(task).model_copy(
        update={"selected_agent_version": "2.0.0"}
    )

    with pytest.raises(SpecialistExecutionPolicyError, match="identity does not match"):
        build_specialist_execution_request(
            task=task,
            decision=decision,
            definition=definition,
            invocation_id=uuid4(),
            context_fingerprint=_CONTEXT_FINGERPRINT,
            requested_capabilities=_capabilities(),
            created_at_ms=2_000,
        )


def test_executor_registry_is_exact_versioned_and_rejects_duplicates() -> None:
    executor = _executor()
    registry = SpecialistExecutorRegistry((executor,))

    assert registry.get(
        agent_id="development.planner",
        agent_version="1.0.0",
    ) is executor
    with pytest.raises(UnknownSpecialistExecutorError, match="not registered"):
        registry.get(
            agent_id="development.planner",
            agent_version="2.0.0",
        )
    with pytest.raises(DuplicateSpecialistExecutorError, match="more than once"):
        SpecialistExecutorRegistry((executor, executor))


@pytest.mark.asyncio
async def test_static_proposal_executor_returns_typed_zero_usage_result() -> None:
    task, request = _request()
    budget = BudgetAccount(
        request_id=task.request_id,
        limits=request.effective_budget,
        monotonic_millis=lambda: 100,
    )

    result = await _executor().execute(
        request=request,
        cancellation=SpecialistCancellation(),
        budget=budget,
    )

    assert result.outcome == SpecialistExecutionOutcome.COMPLETED
    assert result.payload is not None
    assert result.payload["steps"] == ["تعریف قرارداد", "اجرای تست"]
    assert result.committed_usage.model_calls == 0
    assert result.committed_usage.tool_calls == 0
    assert budget.snapshot().committed.model_calls == 0
    assert budget.snapshot().committed.tool_calls == 0


@pytest.mark.asyncio
async def test_static_executor_honours_cancellation_before_entry() -> None:
    task, request = _request()
    cancellation = SpecialistCancellation()
    cancellation.cancel("لغو از سمت کاربر")
    budget = BudgetAccount(
        request_id=task.request_id,
        limits=request.effective_budget,
        monotonic_millis=lambda: 100,
    )

    with pytest.raises(SpecialistExecutionCancelledError, match="لغو از سمت کاربر"):
        await _executor().execute(
            request=request,
            cancellation=cancellation,
            budget=budget,
        )


def test_completed_result_rejects_non_json_payload_without_echoing_value() -> None:
    task, request = _request()
    private_marker = "PRIVATE_SPECIALIST_VALUE_5fd8"

    with pytest.raises(ValidationError) as raised:
        SpecialistExecutionResult(
            request_id=task.request_id,
            invocation_id=request.invocation_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            effect=request.effect,
            outcome=SpecialistExecutionOutcome.COMPLETED,
            output_contract=request.output_contract,
            payload={"private": object(), "marker": private_marker},
            started_at_ms=2_000,
            completed_at_ms=3_000,
        )

    assert private_marker not in str(raised.value)
