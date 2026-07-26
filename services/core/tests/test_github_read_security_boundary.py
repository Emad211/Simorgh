from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
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
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.github_read_adapter import (
    FakeGitHubReadAdapter,
    default_github_read_manifest,
    github_fixture_key,
)
from simorgh_core.agents.github_read_contracts import (
    GitHubFileArguments,
    GitHubFileProjection,
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
    InvocationPhase,
    canonical_fingerprint,
    canonical_json,
    canonical_size_bytes,
)
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
)
from simorgh_core.agents.tool_gateway import BudgetedToolGateway, ToolGatewayError
from simorgh_core.agents.tracing import InMemoryTraceSink


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="ریپازیتوری را بررسی کن",
        requested_outcome="پروژکشن تایپ‌شده",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        freshness=FreshnessClass.CACHED_OK,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=0,
            max_tool_calls=1,
            max_input_tokens=0,
            max_output_tokens=0,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def _request(task: TaskEnvelope):
    routing = RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="github.read",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="explicit repository research",
    )
    return GitHubReadRequestCompiler(
        registry=default_specialist_registry(),
        manifest=default_github_read_manifest(),
        wall_clock_millis=lambda: 2_000,
    ).compile(
        task=task,
        routing=routing,
        arguments=GitHubFileArguments(
            repository="Emad211/Simorgh",
            ref="main",
            path="README.md",
        ),
        invocation_id=uuid4(),
        cancellation_owner_id=uuid4(),
    )


def _budget(task: TaskEnvelope) -> BudgetAccount:
    registry = default_specialist_registry()
    return BudgetAccount(
        request_id=task.request_id,
        limits=registry.effective_budget(
            agent_id="github.read",
            request_budget=task.budget,
        ),
        monotonic_millis=lambda: 0,
    )


def _service(*, adapter, store, traces) -> GovernedGitHubReadService:
    registry = default_specialist_registry()
    manifest = default_github_read_manifest()
    gateway = BudgetedToolGateway(
        registry=registry,
        invoker=GitHubReadToolInvoker(manifest=manifest, adapter=adapter),
        invocation_store=store,
        trace_sink=traces,
    )
    return GovernedGitHubReadService(
        registry=registry,
        gateway=gateway,
        manifest=manifest,
        wall_clock_millis=lambda: 2_500,
    )


def _envelope(*, projection, privacy: PrivacyClassification):
    return GitHubReadProjectionEnvelope(
        tool_id="github.fetch-file",
        projection=projection,
        projection_sha256=canonical_fingerprint(projection),
        response_bytes=canonical_size_bytes(projection),
        observed_at_ms=2_000,
        fresh_until_ms=12_000,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        citation_reference="github:evidence:security-boundary",
        privacy=privacy,
    )


@pytest.mark.asyncio
async def test_non_public_visibility_cannot_be_laundered_as_public() -> None:
    marker = "PRIVATE_VISIBILITY_MARKER_91df"
    task = _task()
    request = _request(task)
    text = marker + "\n"
    projection = GitHubFileProjection(
        repository="Emad211/Simorgh",
        visibility=GitHubVisibility.PRIVATE,
        ref="main",
        path="README.md",
        blob_sha="a" * 40,
        byte_count=len(text.encode("utf-8")),
        text=text,
        text_disposition=GitHubTextDisposition.COMPLETE,
    )
    adapter = FakeGitHubReadAdapter(
        fixtures={
            github_fixture_key(request): _envelope(
                projection=projection,
                privacy=PrivacyClassification.PUBLIC,
            )
        }
    )
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 3_000)
    traces = InMemoryTraceSink()
    budget = _budget(task)

    with pytest.raises(ToolGatewayError, match="rejected"):
        await _service(adapter=adapter, store=store, traces=traces).execute(
            task=task,
            request=request,
            budget=budget,
        )

    record = store.get(request.invocation_id)
    persisted = canonical_json(record.model_dump(mode="json"))
    traced = canonical_json(
        {"events": [event.model_dump(mode="json") for event in traces.for_request(task.request_id)]}
    )
    assert record.state == InvocationPhase.FAILED
    assert record.committed_usage.tool_calls == 1
    assert marker not in persisted
    assert marker not in traced


class _ValueErrorAdapter:
    connector_id = "github"
    connector_version = "1.0.0"

    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.calls = 0

    async def invoke(self, request):
        self.calls += 1
        raise ValueError(self.marker)


@pytest.mark.asyncio
async def test_unexpected_adapter_value_error_remains_unknown_and_sanitized() -> None:
    marker = "ADAPTER_SECRET_MARKER_42aa"
    task = _task()
    request = _request(task)
    adapter = _ValueErrorAdapter(marker)
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 3_000)
    traces = InMemoryTraceSink()
    budget = _budget(task)

    with pytest.raises(ToolGatewayError, match="invocation failed"):
        await _service(adapter=adapter, store=store, traces=traces).execute(
            task=task,
            request=request,
            budget=budget,
        )

    record = store.get(request.invocation_id)
    persisted = canonical_json(record.model_dump(mode="json"))
    traced = canonical_json(
        {"events": [event.model_dump(mode="json") for event in traces.for_request(task.request_id)]}
    )
    assert adapter.calls == 1
    assert record.state == InvocationPhase.UNKNOWN
    assert record.failure_detail == "ValueError"
    assert marker not in persisted
    assert marker not in traced
