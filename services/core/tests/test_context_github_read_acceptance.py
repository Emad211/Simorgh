from __future__ import annotations

from uuid import NAMESPACE_URL, uuid4, uuid5

from simorgh_core.agents.budget import BudgetSnapshot
from simorgh_core.agents.context_compiler import ContextCompilerService
from simorgh_core.agents.context_contracts import ContextCompilationRequest
from simorgh_core.agents.context_projections import (
    build_context_output_schema,
    build_github_context_tool_schemas,
)
from simorgh_core.agents.context_result_schemas import (
    default_context_result_schema_registry,
)
from simorgh_core.agents.context_sources import (
    ContextMaterialRegistry,
    context_material_from_github_projection,
)
from simorgh_core.agents.context_store import InMemoryContextStore
from simorgh_core.agents.contracts import (
    ExecutionMode,
    FreshnessClass,
    RiskClass,
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
from simorgh_core.agents.github_read_contracts import (
    GITHUB_FETCH_FILE_TOOL_ID,
    GitHubFileProjection,
    GitHubObjectKind,
    GitHubReadProjectionEnvelope,
    GitHubTextDisposition,
    GitHubVisibility,
)
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    canonical_fingerprint,
    canonical_size_bytes,
)
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistCapabilitySet,
    build_specialist_execution_request,
)
from simorgh_core.agents.specialist_results import REPOSITORY_REPORT_OUTPUT_CONTRACT
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import InMemoryAgentTaskStore, new_task_store_entry

_NOW_MS = 2_500


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        received_at_ms=1_000,
        deadline_at_ms=50_000,
        locale="fa-IR",
        input_text="فایل README ریپازیتوری سیمرغ را بررسی کن",
        requested_outcome="گزارش ساختاریافته و مستند ریپازیتوری",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        freshness=FreshnessClass.CURRENT,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=1,
            max_tool_calls=2,
            max_input_tokens=12_000,
            max_output_tokens=4_000,
            max_estimated_cost_microusd=40_000,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def _decision(task: TaskEnvelope) -> RoutingDecision:
    return RoutingDecision(
        decision_id=uuid5(NAMESPACE_URL, f"context-github-route:{task.request_id}"),
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="github.read",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        candidate_agent_ids=("github.read",),
        reason="explicit repository research task",
    )


def _record(task: TaskEnvelope) -> AgentTaskRecord:
    return AgentTaskRecord(
        request_id=task.request_id,
        phase=AgentTaskPhase.ROUTED,
        created_at_ms=task.received_at_ms,
        updated_at_ms=1_500,
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
        detail="routed github.read acceptance fixture",
    )


def _evidence(task: TaskEnvelope):
    text = "# Simorgh\nA Persian-first governed agent runtime.\n"
    projection = GitHubFileProjection(
        repository="Emad211/Simorgh",
        visibility=GitHubVisibility.PUBLIC,
        ref="main",
        resolved_ref_sha="a" * 40,
        path="README.md",
        object_kind=GitHubObjectKind.REGULAR,
        blob_sha="b" * 40,
        byte_count=len(text.encode("utf-8")),
        text=text,
        text_disposition=GitHubTextDisposition.COMPLETE,
    )
    envelope = GitHubReadProjectionEnvelope(
        tool_id=GITHUB_FETCH_FILE_TOOL_ID,
        projection=projection,
        projection_sha256=canonical_fingerprint(projection),
        response_bytes=canonical_size_bytes(projection),
        observed_at_ms=2_000,
        fresh_until_ms=20_000,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        citation_reference="github:Emad211/Simorgh@main:README.md",
        privacy=PrivacyClassification.PUBLIC,
    )
    return context_material_from_github_projection(
        request_id=task.request_id,
        envelope=envelope,
        required=True,
        priority=900,
    )


def test_routed_github_read_compiles_typed_evidence_and_replays_zero_cost() -> None:
    task = _task()
    task_store = InMemoryAgentTaskStore()
    expected_record = _record(task)
    task_store.upsert(new_task_store_entry(expected_record))
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: _NOW_MS)
    context_store = InMemoryContextStore()
    evidence = _evidence(task)
    capabilities = SpecialistCapabilitySet(
        tool_ids=frozenset({GITHUB_FETCH_FILE_TOOL_ID}),
        connector_ids=frozenset({"github"}),
    )
    tool_schemas = build_github_context_tool_schemas(
        manifest=default_github_read_manifest(),
        tool_ids=(GITHUB_FETCH_FILE_TOOL_ID,),
    )
    result_registry = default_context_result_schema_registry()
    output_schema = build_context_output_schema(
        registry=result_registry,
        output_contract=REPOSITORY_REPORT_OUTPUT_CONTRACT,
    )
    invocation_id = uuid4()
    request = ContextCompilationRequest(
        request_id=task.request_id,
        specialist_invocation_id=invocation_id,
        agent_id="github.read",
        agent_version="1.0.0",
        capabilities=capabilities,
        materials=(evidence,),
        tool_schemas=tool_schemas,
        output_schema=output_schema,
    )
    service = ContextCompilerService(
        task_store=task_store,
        invocation_store=invocation_store,
        specialist_registry=default_specialist_registry(),
        result_schema_registry=result_registry,
        context_store=context_store,
        material_registry=ContextMaterialRegistry((evidence,)),
        reviewed_tool_schemas={item.tool_id: item for item in tool_schemas},
        wall_clock_millis=lambda: _NOW_MS,
    )

    first = service.compile(request)
    replay = service.compile(request)

    assert not first.replayed
    assert replay.replayed
    assert first.bundle.context_bundle_id == replay.bundle.context_bundle_id
    assert first.bundle.canonical_sha256 == replay.bundle.canonical_sha256
    assert first.bundle.output_schema.output_contract == REPOSITORY_REPORT_OUTPUT_CONTRACT
    assert first.bundle.output_schema.family == "repository_report"
    assert first.bundle.evidence_count == 1
    assert first.bundle.tainted
    evidence_section = next(
        section for section in first.bundle.sections if section.source_id.startswith("github.")
    )
    assert evidence_section.tainted
    assert evidence_section.source_sha256 == evidence.source_sha256
    assert tuple(item.tool_id for item in first.bundle.tool_schemas) == (
        GITHUB_FETCH_FILE_TOOL_ID,
    )
    assert invocation_store.load() == []
    assert task_store.get(task.request_id).record.budget == expected_record.budget

    definition = default_specialist_registry().get("github.read")
    execution_request = build_specialist_execution_request(
        task=task,
        decision=_decision(task),
        definition=definition,
        invocation_id=invocation_id,
        context_fingerprint=first.bundle.canonical_sha256,
        requested_capabilities=capabilities,
        created_at_ms=_NOW_MS,
    )
    assert execution_request.context_bundle_id == first.bundle.context_bundle_id
    assert execution_request.context_fingerprint == first.bundle.canonical_sha256
    assert execution_request.output_contract == REPOSITORY_REPORT_OUTPUT_CONTRACT
