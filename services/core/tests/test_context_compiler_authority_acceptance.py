from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from simorgh_core.agents.budget import BudgetSnapshot
from simorgh_core.agents.context_compiler import (
    ContextCompilerLimitError,
    ContextCompilerService,
)
from simorgh_core.agents.context_contracts import (
    ContextCompilationRequest,
    ContextCompilerLimits,
    ContextCompilerPolicy,
    ContextMaterial,
    ContextOmissionReason,
    ContextSourceKind,
    ContextTrustClass,
    context_material_id_for,
    context_text_sha256,
)
from simorgh_core.agents.context_projections import (
    build_github_context_tool_schemas,
    build_specialist_plan_context_output_schema,
)
from simorgh_core.agents.context_sources import ContextMaterialRegistry
from simorgh_core.agents.context_store import InMemoryContextStore
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.github_read_adapter import default_github_read_manifest
from simorgh_core.agents.invocations import InMemoryInvocationStore, canonical_fingerprint
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
    RetentionDisposition,
    default_result_schema_registry,
)
from simorgh_core.agents.specialist_execution import SpecialistCapabilitySet
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import InMemoryAgentTaskStore, new_task_store_entry

_NOW_MS = 2_500


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        received_at_ms=1_000,
        deadline_at_ms=50_000,
        locale="fa-IR",
        input_text="ریپازیتوری را بررسی کن",
        requested_outcome="برنامه تایپ‌شده",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=1,
            max_tool_calls=3,
            max_input_tokens=20_000,
            max_output_tokens=4_000,
            max_estimated_cost_microusd=50_000,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def _decision(task: TaskEnvelope) -> RoutingDecision:
    return RoutingDecision(
        decision_id=uuid5(NAMESPACE_URL, f"phase17-acceptance:{task.request_id}"),
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="development.planner",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        candidate_agent_ids=("development.planner",),
        reason="explicit development task",
    )


def _record(task: TaskEnvelope) -> AgentTaskRecord:
    return AgentTaskRecord(
        request_id=task.request_id,
        phase=AgentTaskPhase.ROUTED,
        created_at_ms=task.received_at_ms,
        updated_at_ms=1_200,
        task=task,
        routing_decision=_decision(task),
        budget=BudgetSnapshot(
            request_id=task.request_id,
            limits=task.budget,
            committed=UsageVector(),
            reserved=UsageVector(),
            elapsed_ms=1_000,
            cancelled=False,
        ),
        detail="phase 1.7 authority acceptance fixture",
    )


def _material(
    *,
    task: TaskEnvelope,
    kind: ContextSourceKind,
    source_id: str,
    priority: int,
    required: bool = False,
) -> ContextMaterial:
    source_sha = canonical_fingerprint({"kind": kind.value, "source_id": source_id})
    content = f"bounded {source_id}"
    return ContextMaterial(
        material_id=context_material_id_for(
            request_id=task.request_id,
            source_kind=kind,
            source_id=source_id,
            source_sha256=source_sha,
        ),
        request_id=task.request_id,
        source_kind=kind,
        trust=ContextTrustClass.TRUSTED_PROJECT_FACT,
        source_id=source_id,
        source_sha256=source_sha,
        content_sha256=context_text_sha256(content),
        content=content,
        required=required,
        priority=priority,
        observed_at_ms=1_500,
        fresh_until_ms=None,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        content_addressed=True,
        tainted=False,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.SESSION,
        citation_reference=f"fixture:{source_id}",
    )


def _service(
    *,
    task: TaskEnvelope,
    materials: tuple[ContextMaterial, ...],
    tool_ids: tuple[str, ...],
    policy: ContextCompilerPolicy | None = None,
) -> tuple[ContextCompilerService, tuple]:
    task_store = InMemoryAgentTaskStore()
    task_store.upsert(new_task_store_entry(_record(task)))
    tool_schemas = build_github_context_tool_schemas(
        manifest=default_github_read_manifest(),
        tool_ids=tool_ids,
    )
    service = ContextCompilerService(
        task_store=task_store,
        invocation_store=InMemoryInvocationStore(wall_clock_millis=lambda: _NOW_MS),
        specialist_registry=default_specialist_registry(),
        result_schema_registry=default_result_schema_registry(),
        context_store=InMemoryContextStore(),
        material_registry=ContextMaterialRegistry(materials),
        reviewed_tool_schemas={item.tool_id: item for item in tool_schemas},
        policy=policy,
        wall_clock_millis=lambda: _NOW_MS,
    )
    return service, tool_schemas


def _request(
    *,
    task: TaskEnvelope,
    invocation_id: UUID,
    materials: tuple[ContextMaterial, ...],
    tool_schemas: tuple,
) -> ContextCompilationRequest:
    return ContextCompilationRequest(
        request_id=task.request_id,
        specialist_invocation_id=invocation_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        capabilities=SpecialistCapabilitySet(
            tool_ids=frozenset(item.tool_id for item in tool_schemas),
            connector_ids=frozenset({"github"}),
            proposal_allowed=True,
        ),
        materials=materials,
        tool_schemas=tool_schemas,
        output_schema=build_specialist_plan_context_output_schema(
            registry=default_result_schema_registry(),
            output_contract="simorgh.typed-plan.v1",
        ),
    )


def test_project_and_decision_limits_select_highest_priority_and_report_omissions() -> None:
    task = _task()
    project_high = _material(
        task=task,
        kind=ContextSourceKind.PROJECT_GOAL,
        source_id="project.high",
        priority=900,
    )
    project_low = _material(
        task=task,
        kind=ContextSourceKind.PROJECT_GOAL,
        source_id="project.low",
        priority=100,
    )
    decision_high = _material(
        task=task,
        kind=ContextSourceKind.DECISION,
        source_id="decision.high",
        priority=800,
    )
    decision_low = _material(
        task=task,
        kind=ContextSourceKind.DECISION,
        source_id="decision.low",
        priority=50,
    )
    materials = (project_high, project_low, decision_high, decision_low)
    service, tool_schemas = _service(
        task=task,
        materials=materials,
        tool_ids=("github.search",),
        policy=ContextCompilerPolicy(
            limits=ContextCompilerLimits(max_project_items=1, max_decision_items=1)
        ),
    )

    result = service.compile(
        _request(
            task=task,
            invocation_id=uuid4(),
            materials=tuple(reversed(materials)),
            tool_schemas=tool_schemas,
        )
    )

    admitted = {item.source_id for item in result.bundle.sections}
    assert {"project.high", "decision.high"}.issubset(admitted)
    assert "project.low" not in admitted
    assert "decision.low" not in admitted
    omitted = {item.source_id: item.reason for item in result.bundle.omissions}
    assert omitted["project.low"] == ContextOmissionReason.PROJECT_LIMIT
    assert omitted["decision.low"] == ContextOmissionReason.DECISION_LIMIT


def test_required_project_limit_overflow_fails_closed() -> None:
    task = _task()
    first = _material(
        task=task,
        kind=ContextSourceKind.PROJECT_GOAL,
        source_id="project.first-required",
        priority=900,
        required=True,
    )
    second = _material(
        task=task,
        kind=ContextSourceKind.PROJECT_GOAL,
        source_id="project.second-required",
        priority=800,
        required=True,
    )
    service, tool_schemas = _service(
        task=task,
        materials=(first, second),
        tool_ids=("github.search",),
        policy=ContextCompilerPolicy(
            limits=ContextCompilerLimits(max_project_items=1)
        ),
    )

    with pytest.raises(ContextCompilerLimitError, match="required project"):
        service.compile(
            _request(
                task=task,
                invocation_id=uuid4(),
                materials=(second, first),
                tool_schemas=tool_schemas,
            )
        )


def test_tool_schema_permutation_preserves_complete_bundle_identity() -> None:
    task = _task()
    invocation_id = uuid4()
    tool_ids = ("github.search", "github.fetch-file")
    first_service, canonical_schemas = _service(
        task=task,
        materials=(),
        tool_ids=tool_ids,
    )
    second_service, _ = _service(
        task=task,
        materials=(),
        tool_ids=tool_ids,
    )

    first = first_service.compile(
        _request(
            task=task,
            invocation_id=invocation_id,
            materials=(),
            tool_schemas=canonical_schemas,
        )
    )
    second = second_service.compile(
        _request(
            task=task,
            invocation_id=invocation_id,
            materials=(),
            tool_schemas=tuple(reversed(canonical_schemas)),
        )
    )

    assert first.bundle.tool_schemas == second.bundle.tool_schemas
    assert first.bundle.canonical_sha256 == second.bundle.canonical_sha256
    assert first.bundle.context_bundle_id == second.bundle.context_bundle_id
