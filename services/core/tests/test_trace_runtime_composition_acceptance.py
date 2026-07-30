from __future__ import annotations

import json
from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
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
    ModelTier,
    RiskClass,
    RoutingMethod,
    RoutingState,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.github_read_adapter import (
    FakeGitHubReadAdapter,
    default_github_read_manifest,
    github_fixture_key,
)
from simorgh_core.agents.github_read_contracts import (
    GITHUB_FETCH_FILE_TOOL_ID,
    GitHubFileArguments,
    GitHubFileProjection,
    GitHubObjectKind,
    GitHubReadProjectionEnvelope,
    GitHubTextDisposition,
    GitHubVisibility,
)
from simorgh_core.agents.github_read_service import (
    GitHubReadRequestCompiler,
    GitHubReadToolInvoker,
    GovernedGitHubReadService,
)
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
    canonical_fingerprint,
    canonical_size_bytes,
)
from simorgh_core.agents.model_gateway import (
    BudgetedAgentClassifier,
    BudgetedModelGateway,
    ModelCatalog,
    ModelSpec,
)
from simorgh_core.agents.registry import SpecialistRegistry
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
)
from simorgh_core.agents.result_store import InMemoryResultStore
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.specialist_execution import SpecialistCapabilitySet
from simorgh_core.agents.specialist_results import REPOSITORY_REPORT_OUTPUT_CONTRACT
from simorgh_core.agents.sqlite_trace_store import SQLiteTraceStore
from simorgh_core.agents.task_store import InMemoryAgentTaskStore
from simorgh_core.agents.tool_gateway import BudgetedToolGateway
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceDisposition,
    TraceStage,
)
from simorgh_core.agents.trace_projecting_authority_stores import (
    TraceProjectingContextStore,
)
from simorgh_core.agents.trace_projecting_control_plane import (
    TraceProjectingAgentTaskControlPlane,
)
from simorgh_core.agents.trace_projecting_invocation_store import (
    TraceProjectingInvocationStore,
)
from simorgh_core.agents.trace_projection import (
    StoreBackedRequestTraceProjector,
    request_trace_projector_registry,
)
from simorgh_core.agents.trace_reconciliation import (
    reconcile_retained_trace_authority,
)
from simorgh_core.providers.base import ModelOutput


class _Clock:
    def __init__(self, start: int = 2_000) -> None:
        self._value = start

    def __call__(self) -> int:
        current = self._value
        self._value += 1
        return current


class _ClassifierProvider:
    def __init__(self, *, private_marker: str) -> None:
        self.calls = 0
        self._private_marker = private_marker

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        del input_text, instructions, max_output_tokens
        self.calls += 1
        return ModelOutput(
            text=json.dumps(
                {
                    "selected_agent_id": "github.read",
                    "confidence_bps": 9_500,
                    "reason": self._private_marker,
                },
                sort_keys=True,
            ),
            model=model or "classifier-fast",
            provider="fake",
            request_id="classifier-request-1",
            usage={"input_tokens": 64, "output_tokens": 18},
        )

    async def list_models(self) -> list[str]:
        return ["classifier-fast"]


@pytest.fixture(autouse=True)
def _reset_projector_registry() -> None:
    request_trace_projector_registry.reset_to_null()
    yield
    request_trace_projector_registry.reset_to_null()


def _registry() -> SpecialistRegistry:
    default = default_specialist_registry()
    github = default.get("github.read").model_copy(
        update={"routing_rules": (), "routing_priority": 10}
    )
    alternative = github.model_copy(
        update={
            "agent_id": "github.alternative",
            "display_name": "Alternative GitHub Research Agent",
            "routing_rules": (),
            "routing_priority": 10,
        }
    )
    return SpecialistRegistry((github, alternative))


def _task(*, private_marker: str) -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=100_000,
        locale="fa-IR",
        input_text=f"ریپازیتوری را بررسی کن {private_marker}",
        requested_outcome="گزارش ساختاریافته GitHub",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        freshness=FreshnessClass.CURRENT,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=1,
            max_tool_calls=2,
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            max_estimated_cost_microusd=1_000_000,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def _model_catalog() -> ModelCatalog:
    return ModelCatalog(
        (
            ModelSpec(
                provider_id="fake",
                model_id="classifier-fast",
                tier=ModelTier.FAST,
                input_price_microusd_per_million_tokens=0,
                output_price_microusd_per_million_tokens=0,
                maximum_output_tokens=256,
            ),
        )
    )


def _tool_budget(task: TaskEnvelope, registry: SpecialistRegistry) -> BudgetAccount:
    return BudgetAccount(
        request_id=task.request_id,
        limits=registry.effective_budget(
            agent_id="github.read",
            request_budget=task.budget,
        ),
        monotonic_millis=lambda: 0,
    )


@pytest.mark.asyncio
async def test_classifier_and_governed_github_read_reconstruct_exact_live_trace(
    tmp_path,
) -> None:
    task_marker = "PRIVATE_TASK_MARKER_4217"
    classifier_marker = "PRIVATE_CLASSIFIER_REASON_7731"
    github_marker = "PRIVATE_GITHUB_BODY_9982"
    task = _task(private_marker=task_marker)
    registry = _registry()
    clock = _Clock()

    task_store = InMemoryAgentTaskStore()
    raw_invocations = InMemoryInvocationStore(wall_clock_millis=clock)
    invocation_store = TraceProjectingInvocationStore(raw_invocations)
    raw_contexts = InMemoryContextStore()
    context_store = TraceProjectingContextStore(raw_contexts)
    result_store = InMemoryResultStore()
    trace_path = tmp_path / "traces.sqlite3"
    trace_store = SQLiteTraceStore(trace_path)
    projector = StoreBackedRequestTraceProjector(
        task_store=task_store,
        invocation_store=invocation_store,
        context_store=context_store,
        result_store=result_store,
        trace_store=trace_store,
        wall_clock_millis=clock,
    )
    request_trace_projector_registry.configure(projector)

    provider = _ClassifierProvider(private_marker=classifier_marker)
    model_gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_model_catalog(),
        invocation_store=invocation_store,
    )
    classifier = BudgetedAgentClassifier(
        gateway=model_gateway,
        policy_hash="a" * 64,
        allowed_tiers=(ModelTier.FAST,),
        minimum_tier=ModelTier.FAST,
        maximum_output_tokens=256,
    )
    control_plane = TraceProjectingAgentTaskControlPlane(
        router=SpecialistRouter(registry=registry, classifier=classifier),
        store=task_store,
        invocation_store=invocation_store,
        wall_clock_millis=clock,
        monotonic_millis=lambda: 0,
    )

    routed = await control_plane.submit(task)
    assert routed.routing_decision is not None
    assert routed.routing_decision.state == RoutingState.ROUTED
    assert routed.routing_decision.method == RoutingMethod.MODEL_CLASSIFIER
    assert routed.routing_decision.selected_agent_id == "github.read"
    assert provider.calls == 1

    routed_view = trace_store.view(task.request_id)
    assert [event.event_kind for event in routed_view.events] == [
        DurableTraceEventKind.TASK_CLAIMED,
        DurableTraceEventKind.INVOCATION_STARTED,
        DurableTraceEventKind.INVOCATION_TERMINAL,
        DurableTraceEventKind.ROUTING_DECIDED,
    ]
    assert [event.stage for event in routed_view.events] == [
        TraceStage.TASK,
        TraceStage.MODEL,
        TraceStage.MODEL,
        TraceStage.ROUTING,
    ]

    replayed_route = await control_plane.submit(task)
    assert replayed_route == routed
    assert provider.calls == 1
    assert trace_store.view(task.request_id) == routed_view

    owner_id = uuid4()
    specialist_invocation_id = uuid4()
    tool_invocation_id = uuid4()
    manifest = default_github_read_manifest()
    github_request = GitHubReadRequestCompiler(
        registry=registry,
        manifest=manifest,
        wall_clock_millis=clock,
    ).compile(
        task=task,
        routing=routed.routing_decision,
        arguments=GitHubFileArguments(
            repository="Emad211/Simorgh",
            ref="main",
            path="README.md",
        ),
        invocation_id=tool_invocation_id,
        cancellation_owner_id=owner_id,
    )
    github_text = f"# Simorgh\n{github_marker}\n"
    projection = GitHubFileProjection(
        repository="Emad211/Simorgh",
        visibility=GitHubVisibility.PUBLIC,
        ref="main",
        resolved_ref_sha="b" * 40,
        path="README.md",
        object_kind=GitHubObjectKind.REGULAR,
        blob_sha="c" * 40,
        byte_count=len(github_text.encode("utf-8")),
        text=github_text,
        text_disposition=GitHubTextDisposition.COMPLETE,
    )
    envelope = GitHubReadProjectionEnvelope(
        tool_id=GITHUB_FETCH_FILE_TOOL_ID,
        projection=projection,
        projection_sha256=canonical_fingerprint(projection),
        response_bytes=canonical_size_bytes(projection),
        observed_at_ms=clock(),
        fresh_until_ms=90_000,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        citation_reference="github:Emad211/Simorgh@main:README.md",
        privacy=PrivacyClassification.PUBLIC,
    )
    adapter = FakeGitHubReadAdapter(
        fixtures={github_fixture_key(github_request): envelope}
    )
    github_service = GovernedGitHubReadService(
        registry=registry,
        gateway=BudgetedToolGateway(
            registry=registry,
            invoker=GitHubReadToolInvoker(manifest=manifest, adapter=adapter),
            invocation_store=invocation_store,
        ),
        manifest=manifest,
        wall_clock_millis=clock,
    )
    first_tool_budget = _tool_budget(task, registry)
    github_result = await github_service.execute(
        task=task,
        request=github_request,
        budget=first_tool_budget,
    )
    assert adapter.calls == 1
    assert first_tool_budget.snapshot().committed.tool_calls == 1

    material = context_material_from_github_projection(
        request_id=task.request_id,
        envelope=github_result.projection,
        required=True,
        priority=900,
    )
    capabilities = SpecialistCapabilitySet(
        tool_ids=frozenset({GITHUB_FETCH_FILE_TOOL_ID}),
        connector_ids=frozenset({"github"}),
    )
    tool_schemas = build_github_context_tool_schemas(
        manifest=manifest,
        tool_ids=(GITHUB_FETCH_FILE_TOOL_ID,),
    )
    context_result_registry = default_context_result_schema_registry()
    context_request = ContextCompilationRequest(
        request_id=task.request_id,
        specialist_invocation_id=specialist_invocation_id,
        agent_id="github.read",
        agent_version="1.0.0",
        capabilities=capabilities,
        materials=(material,),
        tool_schemas=tool_schemas,
        output_schema=build_context_output_schema(
            registry=context_result_registry,
            output_contract=REPOSITORY_REPORT_OUTPUT_CONTRACT,
        ),
    )
    compiled = ContextCompilerService(
        task_store=task_store,
        invocation_store=invocation_store,
        specialist_registry=registry,
        result_schema_registry=context_result_registry,
        context_store=context_store,
        material_registry=ContextMaterialRegistry((material,)),
        reviewed_tool_schemas={item.tool_id: item for item in tool_schemas},
        wall_clock_millis=clock,
    ).compile(context_request)

    invocation_store.begin(
        invocation_id=specialist_invocation_id,
        request_id=task.request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="specialist.execute",
        input_fingerprint=canonical_fingerprint(
            {"context_sha256": compiled.bundle.canonical_sha256}
        ),
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.READ_ONLY,
        cancellation_owner_id=owner_id,
    )

    live_view = trace_store.view(task.request_id)
    assert live_view.envelope.disposition == TraceDisposition.IN_PROGRESS
    assert not live_view.envelope.terminal
    assert live_view.envelope.gap_count == 0
    assert [event.event_kind for event in live_view.events] == [
        DurableTraceEventKind.TASK_CLAIMED,
        DurableTraceEventKind.INVOCATION_STARTED,
        DurableTraceEventKind.INVOCATION_TERMINAL,
        DurableTraceEventKind.ROUTING_DECIDED,
        DurableTraceEventKind.CONTEXT_COMPILED,
        DurableTraceEventKind.INVOCATION_STARTED,
        DurableTraceEventKind.INVOCATION_STARTED,
        DurableTraceEventKind.INVOCATION_TERMINAL,
    ]
    assert [event.stage for event in live_view.events] == [
        TraceStage.TASK,
        TraceStage.MODEL,
        TraceStage.MODEL,
        TraceStage.ROUTING,
        TraceStage.CONTEXT,
        TraceStage.SPECIALIST,
        TraceStage.TOOL,
        TraceStage.TOOL,
    ]
    serialized = str(live_view.model_dump(mode="json"))
    assert task_marker not in serialized
    assert classifier_marker not in serialized
    assert github_marker not in serialized

    replay_budget = _tool_budget(task, registry)
    replay = await github_service.execute(
        task=task,
        request=github_request,
        budget=replay_budget,
    )
    assert replay.replayed
    assert adapter.calls == 1
    assert replay_budget.snapshot().committed.tool_calls == 0
    assert trace_store.view(task.request_id) == live_view

    request_trace_projector_registry.reset_to_null()
    trace_store.close()
    reopened = SQLiteTraceStore(trace_path)
    replay_report = reconcile_retained_trace_authority(
        store=reopened,
        task_entries=task_store.load(),
        invocation_records=invocation_store.load(),
        context_bundles=context_store.load(),
        result_records=result_store.load(),
        base_ingested_at_ms=90_000,
    )
    reopened_view = reopened.view(task.request_id)

    assert replay_report.projected_event_count == 0
    assert replay_report.replayed_event_count == len(live_view.events)
    assert reopened_view == live_view
    reopened.close()
    invocation_store.close()
    context_store.close()
    result_store.close()
    task_store.close()
