from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

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
    InvocationEffect,
    InvocationKind,
    canonical_fingerprint,
    canonical_size_bytes,
)
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
    ResultSchemaRegistry,
    RetentionDisposition,
    SpecialistPlanResultSchema,
    build_authoritative_plan_result,
)
from simorgh_core.agents.result_store import InMemoryResultStore
from simorgh_core.agents.specialist_execution import (
    SpecialistCapabilitySet,
    SpecialistExecutionOutcome,
    SpecialistExecutionResult,
)
from simorgh_core.agents.specialist_results import (
    REPOSITORY_REPORT_OUTPUT_CONTRACT,
)
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import InMemoryAgentTaskStore, new_task_store_entry
from simorgh_core.agents.trace_authority import (
    TraceEventCandidate,
    TracePhase,
    TraceSafeMetadata,
)
from simorgh_core.agents.trace_service import (
    NativeTraceCorrelationValidator,
    TraceCorrelationError,
)
from simorgh_core.agents.tracing import TraceEventKind

_NOW_MS = 2_500


def _budget() -> TaskBudget:
    return TaskBudget(
        max_model_calls=1,
        max_tool_calls=2,
        max_input_tokens=12_000,
        max_output_tokens=4_000,
        max_estimated_cost_microusd=40_000,
        max_elapsed_ms=30_000,
        max_retries=0,
        max_parallel_branches=1,
    )


def _task(*, kind: TaskKind, agent_id: str) -> TaskEnvelope:
    allowed_sources = frozenset({"github"}) if agent_id == "github.read" else frozenset()
    return TaskEnvelope(
        received_at_ms=1_000,
        deadline_at_ms=50_000,
        locale="fa-IR",
        input_text="درخواست تست کنترل‌شده",
        requested_outcome="خروجی تایپ‌شده",
        explicit_task_kind=kind,
        risk_class=(
            RiskClass.READ_ONLY if kind == TaskKind.REPOSITORY_RESEARCH else RiskClass.PLANNING
        ),
        freshness=FreshnessClass.CURRENT,
        execution_mode=(
            ExecutionMode.READ_ONLY
            if kind == TaskKind.REPOSITORY_RESEARCH
            else ExecutionMode.PLAN
        ),
        allowed_data_sources=allowed_sources,
        budget=_budget(),
    )


def _decision(task: TaskEnvelope, *, agent_id: str) -> RoutingDecision:
    return RoutingDecision(
        decision_id=uuid5(
            NAMESPACE_URL,
            f"trace-authority-route:{task.request_id}:{agent_id}",
        ),
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id=agent_id,
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        candidate_agent_ids=(agent_id,),
        reason="explicit test route",
    )


def _task_store(task: TaskEnvelope, *, agent_id: str) -> InMemoryAgentTaskStore:
    store = InMemoryAgentTaskStore()
    store.upsert(
        new_task_store_entry(
            AgentTaskRecord(
                request_id=task.request_id,
                phase=AgentTaskPhase.ROUTED,
                created_at_ms=task.received_at_ms,
                updated_at_ms=1_500,
                task=task,
                routing_decision=_decision(task, agent_id=agent_id),
                budget=BudgetSnapshot(
                    request_id=task.request_id,
                    limits=task.budget,
                    committed=UsageVector(),
                    reserved=UsageVector(),
                    elapsed_ms=500,
                    cancelled=False,
                ),
                detail="routed test authority",
            )
        )
    )
    return store


def _github_evidence(task: TaskEnvelope):
    text = "# Simorgh\nGoverned agent runtime.\n"
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


def _compiled_context_authorities():
    task = _task(
        kind=TaskKind.REPOSITORY_RESEARCH,
        agent_id="github.read",
    )
    task_store = _task_store(task, agent_id="github.read")
    invocation_store = InMemoryInvocationStore(
        wall_clock_millis=lambda: _NOW_MS
    )
    context_store = InMemoryContextStore()
    result_store = InMemoryResultStore()
    evidence = _github_evidence(task)
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
    bundle = service.compile(request).bundle
    validator = NativeTraceCorrelationValidator(
        task_store=task_store,
        invocation_store=invocation_store,
        context_store=context_store,
        result_store=result_store,
    )
    return task, invocation_id, bundle, validator


def test_context_trace_cross_checks_hash_classification_and_taint() -> None:
    task, invocation_id, bundle, validator = _compiled_context_authorities()
    candidate = TraceEventCandidate(
        request_id=task.request_id,
        occurred_at_ms=bundle.compiled_at_ms,
        kind=TraceEventKind.CONTEXT_COMPILED,
        phase=TracePhase.CONTEXT,
        invocation_id=invocation_id,
        context_bundle_id=bundle.context_bundle_id,
        agent_id=bundle.agent_id,
        agent_version=bundle.agent_version,
        outcome="completed",
        privacy=bundle.privacy,
        retention=bundle.retention,
        tainted=bundle.tainted,
        metadata=TraceSafeMetadata(
            context_sha256=bundle.canonical_sha256,
            section_count=len(bundle.sections),
            byte_count=bundle.total_bytes,
            estimated_tokens=bundle.estimated_unit_count,
            omission_count=len(bundle.omissions),
            evidence_count=bundle.evidence_count,
        ),
    )

    validator.validate(candidate)

    with pytest.raises(TraceCorrelationError, match="context hash"):
        validator.validate(
            candidate.model_copy(
                update={
                    "metadata": candidate.metadata.model_copy(
                        update={"context_sha256": "f" * 64}
                    )
                }
            )
        )
    with pytest.raises(TraceCorrelationError, match="classification"):
        validator.validate(
            candidate.model_copy(update={"privacy": PrivacyClassification.RESTRICTED})
        )


def _execution_result(
    *,
    request_id: UUID,
    invocation_id: UUID,
) -> SpecialistExecutionResult:
    return SpecialistExecutionResult(
        request_id=request_id,
        invocation_id=invocation_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        effect=InvocationEffect.PROPOSAL,
        outcome=SpecialistExecutionOutcome.COMPLETED,
        output_contract="simorgh.typed-plan.v1",
        payload={
            "summary": "برنامه کنترل‌شده",
            "steps": ["قرارداد", "تست"],
            "unresolved_risks": [],
            "verification_requirements": [],
        },
        started_at_ms=2_000,
        completed_at_ms=3_000,
    )


def _result_authorities():
    task = _task(
        kind=TaskKind.DEVELOPMENT_PLANNING,
        agent_id="development.planner",
    )
    task_store = _task_store(task, agent_id="development.planner")
    invocation_store = InMemoryInvocationStore(
        wall_clock_millis=lambda: _NOW_MS
    )
    invocation_id = uuid4()
    invocation_store.begin(
        invocation_id=invocation_id,
        request_id=task.request_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="specialist:development.planner",
        input_fingerprint=canonical_fingerprint({"fixture": "trace-result"}),
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.PROPOSAL,
    )
    execution = _execution_result(
        request_id=task.request_id,
        invocation_id=invocation_id,
    )
    invocation_store.complete(
        invocation_id=invocation_id,
        result_payload=execution.model_dump(mode="json"),
        committed_usage=UsageVector(),
    )
    result = build_authoritative_plan_result(
        execution_result=execution,
        registry=ResultSchemaRegistry((SpecialistPlanResultSchema(),)),
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
    )
    result_store = InMemoryResultStore()
    result_store.claim(result)
    validator = NativeTraceCorrelationValidator(
        task_store=task_store,
        invocation_store=invocation_store,
        context_store=InMemoryContextStore(),
        result_store=result_store,
    )
    return task, result, validator


def test_result_trace_cross_checks_invocation_hash_and_classification() -> None:
    task, result, validator = _result_authorities()
    candidate = TraceEventCandidate(
        request_id=task.request_id,
        occurred_at_ms=result.completed_at_ms,
        kind=TraceEventKind.RESULT_COMMITTED,
        phase=TracePhase.RESULT,
        invocation_id=result.invocation_id,
        result_id=result.result_id,
        agent_id=result.producer_agent_id,
        agent_version=result.producer_agent_version,
        outcome="completed",
        privacy=result.privacy,
        retention=result.retention,
        metadata=TraceSafeMetadata(
            schema_id=result.result_schema_id,
            schema_version=result.result_schema_version,
            result_sha256=result.canonical_sha256,
            evidence_count=len(result.evidence),
            artifact_count=len(result.artifacts),
        ),
    )

    validator.validate(candidate)

    with pytest.raises(TraceCorrelationError, match="result hash"):
        validator.validate(
            candidate.model_copy(
                update={
                    "metadata": candidate.metadata.model_copy(
                        update={"result_sha256": "e" * 64}
                    )
                }
            )
        )
    with pytest.raises(TraceCorrelationError, match="result invocation"):
        validator.validate(candidate.model_copy(update={"invocation_id": uuid4()}))
