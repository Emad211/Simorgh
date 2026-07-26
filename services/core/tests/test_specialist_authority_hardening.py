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
from simorgh_core.agents.invocations import InMemoryInvocationStore
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistCapabilitySet,
    SpecialistExecutionPolicyError,
    SpecialistExecutionResult,
    SpecialistExecutorRegistry,
    StaticProposalSpecialistExecutor,
    build_specialist_execution_request,
)
from simorgh_core.agents.specialist_results import SpecialistPlanPayload
from simorgh_core.agents.specialist_runtime import SpecialistExecutionRuntime
from simorgh_core.agents.tracing import InMemoryTraceSink, TraceEventKind


def _task(*, private_marker: str = "fixture") -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text=f"برای سیمرغ برنامه بساز {private_marker}",
        requested_outcome="برنامه اجرایی",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
        allowed_data_sources=frozenset(),
    )


def _decision(task: TaskEnvelope) -> RoutingDecision:
    definition = default_specialist_registry().get("development.planner")
    return RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id=definition.agent_id,
        selected_agent_version=definition.version,
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="explicit fixture",
    )


def _request(
    task: TaskEnvelope,
    *,
    invocation_id: object,
    context_fingerprint: str,
):
    definition = default_specialist_registry().get("development.planner")
    return build_specialist_execution_request(
        task=task,
        decision=_decision(task),
        definition=definition,
        invocation_id=invocation_id,
        context_fingerprint=context_fingerprint,
        requested_capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        created_at_ms=2_000,
    )


def test_plan_payload_is_concrete_and_rejects_arbitrary_fields() -> None:
    payload = SpecialistPlanPayload(
        summary="برنامه مرحله‌ای",
        steps=("قرارداد", "تست"),
        unresolved_risks=("نبود داده زنده",),
        verification_requirements=("CI سبز",),
    )

    assert payload.kind == "plan"
    assert payload.steps == ("قرارداد", "تست")
    assert payload.unresolved_risks == ("نبود داده زنده",)
    assert payload.verification_requirements == ("CI سبز",)

    with pytest.raises(ValidationError):
        SpecialistPlanPayload.model_validate(
            {
                "summary": "برنامه",
                "steps": [],
                "arbitrary_model_output": "not allowed",
            }
        )


def test_execution_result_coerces_only_the_concrete_plan_contract() -> None:
    task = _task()
    invocation_id = uuid4()
    request = _request(
        task,
        invocation_id=invocation_id,
        context_fingerprint="a" * 64,
    )

    result = SpecialistExecutionResult(
        request_id=task.request_id,
        invocation_id=invocation_id,
        agent_id=request.agent_id,
        agent_version=request.agent_version,
        effect=request.effect,
        outcome="completed",
        output_contract=request.output_contract,
        payload={"summary": "برنامه", "steps": ["تست"]},
        started_at_ms=2_000,
        completed_at_ms=3_000,
    )

    assert isinstance(result.payload, SpecialistPlanPayload)
    assert result.payload.steps == ("تست",)

    with pytest.raises(ValidationError):
        SpecialistExecutionResult(
            request_id=task.request_id,
            invocation_id=invocation_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            effect=request.effect,
            outcome="completed",
            output_contract=request.output_contract,
            payload={"summary": "برنامه", "unexpected": "blocked"},
            started_at_ms=2_000,
            completed_at_ms=3_000,
        )


def test_context_and_cancellation_identities_are_stable_and_scoped() -> None:
    task = _task()
    first_invocation = uuid4()
    second_invocation = uuid4()
    first = _request(
        task,
        invocation_id=first_invocation,
        context_fingerprint="b" * 64,
    )
    same_context = _request(
        task,
        invocation_id=second_invocation,
        context_fingerprint="b" * 64,
    )
    changed_context = _request(
        task,
        invocation_id=uuid4(),
        context_fingerprint="c" * 64,
    )

    assert first.context_bundle_id == same_context.context_bundle_id
    assert first.context_bundle_id != changed_context.context_bundle_id
    assert first.cancellation_owner_id != same_context.cancellation_owner_id
    assert first.monotonic_timeout_ms == first.effective_budget.max_elapsed_ms


def test_cancellation_token_rejects_wrong_owner() -> None:
    first_owner = uuid4()
    token = SpecialistCancellation(owner_id=first_owner)

    token.require_owner(first_owner)
    with pytest.raises(SpecialistExecutionPolicyError, match="owner"):
        token.require_owner(uuid4())


@pytest.mark.asyncio
async def test_runtime_trace_contains_only_bounded_authority_metadata() -> None:
    private_task = "PRIVATE_TASK_63f5"
    private_result = "PRIVATE_RESULT_80b1"
    task = _task(private_marker=private_task)
    definition = default_specialist_registry().get("development.planner")
    executor = StaticProposalSpecialistExecutor(
        agent_id=definition.agent_id,
        agent_version=definition.version,
        output_contract=definition.output_contract,
        payload={
            "summary": private_result,
            "steps": ["قرارداد"],
            "unresolved_risks": ["fixture risk"],
            "verification_requirements": ["fixture verification"],
        },
        wall_clock_millis=lambda: 2_000,
    )
    traces = InMemoryTraceSink()
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    runtime = SpecialistExecutionRuntime(
        executor_registry=SpecialistExecutorRegistry((executor,)),
        invocation_store=store,
        trace_sink=traces,
        wall_clock_millis=lambda: 2_000,
    )
    budget = BudgetAccount(
        request_id=task.request_id,
        limits=definition.budget_ceiling,
        monotonic_millis=lambda: 0,
    )
    invocation_id = uuid4()

    result = await runtime.execute(
        task=task,
        decision=_decision(task),
        definition=definition,
        invocation_id=invocation_id,
        context_fingerprint="d" * 64,
        capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        budget=budget,
    )
    replay = await runtime.execute(
        task=task,
        decision=_decision(task),
        definition=definition,
        invocation_id=invocation_id,
        context_fingerprint="d" * 64,
        capabilities=SpecialistCapabilitySet(proposal_allowed=True),
        budget=BudgetAccount(
            request_id=task.request_id,
            limits=definition.budget_ceiling,
            monotonic_millis=lambda: 0,
        ),
    )

    assert isinstance(result.payload, SpecialistPlanPayload)
    assert replay.replayed
    events = traces.for_request(task.request_id)
    kinds = {event.kind for event in events}
    assert TraceEventKind.SPECIALIST_STARTED in kinds
    assert TraceEventKind.SPECIALIST_COMPLETED in kinds
    assert TraceEventKind.INVOCATION_REPLAYED in kinds
    encoded = "\n".join(event.model_dump_json() for event in events)
    assert private_task not in encoded
    assert private_result not in encoded
    assert "context_bundle_id" in encoded
    assert "output_contract" in encoded
