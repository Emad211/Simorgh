from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID, uuid4

from simorgh_core.agents.budget import BudgetAccount, ReservationKind
from simorgh_core.agents.contracts import (
    AgentClassification,
    ExecutionMode,
    ModelPolicy,
    RoutingRule,
    RoutingState,
    SideEffectPolicy,
    SpecialistDefinition,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.registry import SpecialistRegistry
from simorgh_core.agents.router import SpecialistRouter, normalize_routing_text


def _task(
    text: str,
    *,
    explicit_task_kind: TaskKind | None = None,
    execution_mode: ExecutionMode = ExecutionMode.PLAN,
) -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        locale="fa-IR",
        input_text=text,
        requested_outcome="انتخاب عامل تخصصی اصلی",
        explicit_task_kind=explicit_task_kind,
        execution_mode=execution_mode,
        budget=TaskBudget(max_model_calls=1),
    )


def _budget(task: TaskEnvelope) -> BudgetAccount:
    return BudgetAccount(
        request_id=task.request_id,
        limits=task.budget,
        monotonic_millis=lambda: 100,
    )


def test_explicit_task_kind_routes_with_zero_model_calls() -> None:
    task = _task(
        "این ورودی ساختاریافته است",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        execution_mode=ExecutionMode.READ_ONLY,
    )
    classifier = RecordingClassifier(
        AgentClassification(
            selected_agent_id="general.planner",
            confidence_bps=9_000,
            reason="should never be called",
        )
    )
    router = SpecialistRouter(
        registry=default_specialist_registry(),
        classifier=classifier,
    )

    decision = asyncio.run(router.route(task=task, budget=_budget(task)))

    assert decision.state == RoutingState.ROUTED
    assert decision.selected_agent_id == "github.read"
    assert decision.method == "explicit_task_kind"
    assert decision.model_calls == 0
    assert classifier.calls == 0
    assert _budget(task).snapshot().committed.model_calls == 0


def test_persian_and_mixed_english_terms_route_deterministically() -> None:
    router = SpecialistRouter(registry=default_specialist_registry())
    seo_task = _task(
        "برای سئوی سایت، keyword و سرچ کنسول را دقیق تحلیل کن",
        execution_mode=ExecutionMode.PLAN,
    )
    github_task = _task(
        "ریپازیتوری GitHub و pull request های پروژه را بررسی کن",
        execution_mode=ExecutionMode.READ_ONLY,
    )

    seo = asyncio.run(router.route(task=seo_task, budget=_budget(seo_task)))
    github = asyncio.run(router.route(task=github_task, budget=_budget(github_task)))

    assert seo.state == RoutingState.ROUTED
    assert seo.selected_agent_id == "seo.planner"
    assert seo.method == "deterministic_rule"
    assert seo.model_calls == 0
    assert github.selected_agent_id == "github.read"
    assert github.model_calls == 0


def test_arabic_keyboard_variants_normalize_to_persian_routing_text() -> None:
    assert normalize_routing_text("گيت هاب و كدنويسي") == "گیت هاب و کدنویسی"

    task = _task("گيت هاب را براي اين ريپازيتوري بررسي كن")
    decision = asyncio.run(
        SpecialistRouter(registry=default_specialist_registry()).route(
            task=task,
            budget=_budget(task),
        )
    )
    assert decision.selected_agent_id == "github.read"
    assert decision.model_calls == 0


def test_ambiguous_rules_use_at_most_one_classifier_call_and_one_primary_owner() -> None:
    registry = SpecialistRegistry(
        (
            _definition(agent_id="alpha.planner", phrase="پروژه"),
            _definition(agent_id="beta.planner", phrase="پروژه"),
        )
    )
    task = _task("برای این پروژه یک برنامه بساز")
    classifier = RecordingClassifier(
        AgentClassification(
            selected_agent_id="beta.planner",
            confidence_bps=8_500,
            reason="beta owns the requested outcome",
        )
    )

    decision = asyncio.run(
        SpecialistRouter(registry=registry, classifier=classifier).route(
            task=task,
            budget=_budget(task),
        )
    )

    assert decision.state == RoutingState.ROUTED
    assert decision.selected_agent_id == "beta.planner"
    assert decision.method == "model_classifier"
    assert decision.model_calls == 1
    assert classifier.calls == 1
    assert set(decision.candidate_agent_ids) == {"alpha.planner", "beta.planner"}


def test_low_classifier_confidence_requests_clarification_instead_of_fanout() -> None:
    registry = SpecialistRegistry(
        (
            _definition(agent_id="alpha.planner", phrase="پروژه"),
            _definition(agent_id="beta.planner", phrase="پروژه"),
        )
    )
    task = _task("برای این پروژه کمک کن")
    classifier = RecordingClassifier(
        AgentClassification(
            selected_agent_id="alpha.planner",
            confidence_bps=4_000,
            reason="request spans both domains",
        )
    )

    decision = asyncio.run(
        SpecialistRouter(registry=registry, classifier=classifier).route(
            task=task,
            budget=_budget(task),
        )
    )

    assert decision.state == RoutingState.NEEDS_CLARIFICATION
    assert decision.selected_agent_id is None
    assert decision.model_calls == 1
    assert classifier.calls == 1


def test_no_classifier_returns_clarification_without_model_cost() -> None:
    registry = SpecialistRegistry(
        (
            _definition(agent_id="alpha.planner", phrase="پروژه"),
            _definition(agent_id="beta.planner", phrase="پروژه"),
        )
    )
    task = _task("یک پروژه دارم")
    budget = _budget(task)

    decision = asyncio.run(
        SpecialistRouter(registry=registry).route(task=task, budget=budget)
    )

    assert decision.state == RoutingState.NEEDS_CLARIFICATION
    assert decision.model_calls == 0
    assert budget.snapshot().committed.model_calls == 0


def test_execute_mode_cannot_route_to_proposal_only_mobile_agent() -> None:
    task = _task(
        "اپ را روی گوشی باز کن",
        explicit_task_kind=TaskKind.MOBILE_OPERATION_PLANNING,
        execution_mode=ExecutionMode.EXECUTE_TYPED,
    )

    decision = asyncio.run(
        SpecialistRouter(registry=default_specialist_registry()).route(
            task=task,
            budget=_budget(task),
        )
    )

    assert decision.state == RoutingState.POLICY_BLOCKED
    assert decision.selected_agent_id is None
    assert decision.model_calls == 0


def _definition(*, agent_id: str, phrase: str) -> SpecialistDefinition:
    return SpecialistDefinition(
        agent_id=agent_id,
        version="1.0.0",
        display_name=agent_id,
        task_kinds=frozenset({TaskKind.GENERAL_PLANNING}),
        locale_prefixes=frozenset({"fa"}),
        input_contract="simorgh.task.v1",
        output_contract="simorgh.typed-plan.v1",
        model_policy=ModelPolicy(),
        budget_ceiling=TaskBudget(),
        side_effect_policy=SideEffectPolicy.PROPOSE_ONLY,
        routing_rules=(
            RoutingRule(
                rule_id=f"{agent_id}.shared",
                locale_prefixes=frozenset({"fa"}),
                phrases=(phrase,),
                weight=10,
            ),
        ),
        routing_priority=100,
    )


class RecordingClassifier:
    def __init__(self, result: AgentClassification) -> None:
        self.result = result
        self.calls = 0
        self.invocation_ids: list[UUID] = []

    async def classify(
        self,
        *,
        task: TaskEnvelope,
        candidates: Sequence[SpecialistDefinition],
        budget: BudgetAccount,
        invocation_id: UUID,
    ) -> AgentClassification:
        del task, candidates
        self.calls += 1
        self.invocation_ids.append(invocation_id)
        reservation = budget.reserve(
            kind=ReservationKind.MODEL,
            usage=UsageVector(
                model_calls=1,
                input_tokens=100,
                output_tokens=20,
                estimated_cost_microusd=100,
            ),
        )
        budget.reconcile(
            reservation_id=reservation.reservation_id,
            actual_usage=UsageVector(
                model_calls=1,
                input_tokens=80,
                output_tokens=10,
                estimated_cost_microusd=70,
            ),
        )
        return self.result
