from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from simorgh_core.agents.budget import BudgetSnapshot
from simorgh_core.agents.context_compiler import ContextCompilerService
from simorgh_core.agents.context_contracts import (
    ContextCompilationRequest,
    ContextCompilerLimits,
    ContextCompilerPolicy,
    ContextMaterial,
    ContextOmissionReason,
    ContextSectionDisposition,
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
    FreshnessClass,
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
        input_text="ریپازیتوری را بررسی کن و برنامه توسعه بده",
        requested_outcome="یک برنامه تایپ‌شده و قابل راستی‌آزمایی",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        freshness=FreshnessClass.CURRENT,
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
        decision_id=uuid5(NAMESPACE_URL, f"simorgh-test-route:{task.request_id}"),
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="development.planner",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        candidate_agent_ids=("development.planner",),
        reason="explicit development task kind",
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
            committed=UsageVector(model_calls=1, tool_calls=1, input_tokens=200),
            reserved=UsageVector(),
            elapsed_ms=2_000,
            cancelled=False,
        ),
        detail="routed fixture",
    )


def _capabilities() -> SpecialistCapabilitySet:
    return SpecialistCapabilitySet(
        tool_ids=frozenset({"github.search"}),
        connector_ids=frozenset({"github"}),
        proposal_allowed=True,
    )


def _material(*, request_id: UUID, source_id: str, content: str) -> ContextMaterial:
    source_sha256 = canonical_fingerprint(
        {"source_kind": ContextSourceKind.EVIDENCE.value, "source_id": source_id}
    )
    return ContextMaterial(
        material_id=context_material_id_for(
            request_id=request_id,
            source_kind=ContextSourceKind.EVIDENCE,
            source_id=source_id,
            source_sha256=source_sha256,
        ),
        request_id=request_id,
        source_kind=ContextSourceKind.EVIDENCE,
        trust=ContextTrustClass.UNTRUSTED_EXTERNAL_EVIDENCE,
        source_id=source_id,
        source_sha256=source_sha256,
        content_sha256=context_text_sha256(content),
        content=content,
        priority=100,
        observed_at_ms=1_500,
        fresh_until_ms=20_000,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        content_addressed=False,
        tainted=True,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.SESSION,
        citation_reference=f"fixture:{source_id}",
    )


def _request(
    *,
    task: TaskEnvelope,
    invocation_id: UUID,
    material: ContextMaterial,
) -> ContextCompilationRequest:
    tool_schemas = build_github_context_tool_schemas(
        manifest=default_github_read_manifest(),
        tool_ids=("github.search",),
    )
    return ContextCompilationRequest(
        request_id=task.request_id,
        specialist_invocation_id=invocation_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        capabilities=_capabilities(),
        materials=(material,),
        tool_schemas=tool_schemas,
        output_schema=build_specialist_plan_context_output_schema(
            registry=default_result_schema_registry(),
            output_contract="simorgh.typed-plan.v1",
        ),
    )


def _service(
    *,
    task: TaskEnvelope,
    material: ContextMaterial,
    policy: ContextCompilerPolicy,
) -> ContextCompilerService:
    task_store = InMemoryAgentTaskStore()
    task_store.upsert(new_task_store_entry(_record(task)))
    tool_schemas = build_github_context_tool_schemas(
        manifest=default_github_read_manifest(),
        tool_ids=("github.search",),
    )
    return ContextCompilerService(
        task_store=task_store,
        invocation_store=InMemoryInvocationStore(
            wall_clock_millis=lambda: _NOW_MS
        ),
        specialist_registry=default_specialist_registry(),
        result_schema_registry=default_result_schema_registry(),
        context_store=InMemoryContextStore(),
        material_registry=ContextMaterialRegistry((material,)),
        reviewed_tool_schemas={item.tool_id: item for item in tool_schemas},
        policy=policy,
        wall_clock_millis=lambda: _NOW_MS,
    )


def test_text_limit_truncation_records_source_and_reason() -> None:
    task = _task()
    material = _material(
        request_id=task.request_id,
        source_id="github.text-limit",
        content="x" * 500,
    )
    service = _service(
        task=task,
        material=material,
        policy=ContextCompilerPolicy(
            limits=ContextCompilerLimits(max_text_characters=160)
        ),
    )

    result = service.compile(
        _request(task=task, invocation_id=uuid4(), material=material)
    )
    section = next(
        item for item in result.bundle.sections if item.material_id == material.material_id
    )
    reports = [
        item
        for item in result.bundle.omissions
        if item.material_id == material.material_id
    ]

    assert section.disposition == ContextSectionDisposition.TRUNCATED
    assert section.included_characters == 160
    assert [(item.source_id, item.reason) for item in reports] == [
        (material.source_id, ContextOmissionReason.TEXT_LIMIT)
    ]


def test_total_byte_compaction_records_reason_without_duplicate_reports() -> None:
    task = _task()
    material = _material(
        request_id=task.request_id,
        source_id="github.byte-limit",
        content="y" * 100_000,
    )
    service = _service(
        task=task,
        material=material,
        policy=ContextCompilerPolicy(
            limits=ContextCompilerLimits(
                max_total_bytes=40_000,
                max_estimated_tokens=1_000_000,
                max_text_characters=120_000,
            )
        ),
    )

    result = service.compile(
        _request(task=task, invocation_id=uuid4(), material=material)
    )
    reports = [
        item
        for item in result.bundle.omissions
        if item.material_id == material.material_id
        and item.reason == ContextOmissionReason.BYTE_LIMIT
    ]

    assert len(reports) == 1
    section = next(
        item for item in result.bundle.sections if item.material_id == material.material_id
    )
    assert section.disposition == ContextSectionDisposition.TRUNCATED
    assert section.included_characters < len(material.content)
