from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

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
    GitHubReadAdapter,
    default_github_read_manifest,
    github_fixture_key,
)
from simorgh_core.agents.github_read_contracts import (
    GITHUB_FETCH_FILE_TOOL_ID,
    GITHUB_FETCH_ISSUE_TOOL_ID,
    GITHUB_FETCH_PR_TOOL_ID,
    GITHUB_SEARCH_TOOL_ID,
    GitHubCachePolicy,
    GitHubCheckState,
    GitHubFileArguments,
    GitHubFileProjection,
    GitHubIssueArguments,
    GitHubIssueProjection,
    GitHubIssueState,
    GitHubObjectKind,
    GitHubPullRequestArguments,
    GitHubPullRequestProjection,
    GitHubPullRequestState,
    GitHubReadProjectionEnvelope,
    GitHubSearchArguments,
    GitHubSearchItem,
    GitHubSearchProjection,
    GitHubTextDisposition,
    GitHubVisibility,
)
from simorgh_core.agents.github_read_service import (
    GitHubReadPolicyError,
    GitHubReadRequestCompiler,
    GitHubReadToolInvoker,
    GovernedGitHubReadService,
    github_projection_to_evidence,
)
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationPhase,
    canonical_fingerprint,
    canonical_size_bytes,
)
from simorgh_core.agents.registry import SpecialistRegistry
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistExecutionCancelledError,
)
from simorgh_core.agents.tool_gateway import (
    BudgetedToolGateway,
    ToolGatewayError,
)
from simorgh_core.agents.tracing import InMemoryTraceSink


def _task(
    *,
    freshness: FreshnessClass = FreshnessClass.CURRENT,
    sources: frozenset[str] = frozenset({"github", "drive"}),
) -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="ریپازیتوری سیمرغ را بررسی کن",
        requested_outcome="پروژکشن تایپ‌شده GitHub",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        freshness=freshness,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=sources,
        budget=TaskBudget(
            max_model_calls=0,
            max_tool_calls=2,
            max_input_tokens=0,
            max_output_tokens=0,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def _routing(task: TaskEnvelope) -> RoutingDecision:
    return RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="github.read",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="explicit repository research",
    )


def _compiler(*, registry: SpecialistRegistry | None = None):
    return GitHubReadRequestCompiler(
        registry=registry or default_specialist_registry(),
        manifest=default_github_read_manifest(),
        wall_clock_millis=lambda: 2_000,
    )


def _envelope(
    *,
    tool_id: str,
    projection,
    privacy: PrivacyClassification = PrivacyClassification.PUBLIC,
    cache: EvidenceCacheDisposition = EvidenceCacheDisposition.LIVE,
    fresh_until_ms: int | None = 12_000,
) -> GitHubReadProjectionEnvelope:
    return GitHubReadProjectionEnvelope(
        tool_id=tool_id,
        projection=projection,
        projection_sha256=canonical_fingerprint(projection),
        response_bytes=canonical_size_bytes(projection),
        observed_at_ms=2_000,
        fresh_until_ms=fresh_until_ms,
        cache_disposition=cache,
        citation_reference=f"github:evidence:{tool_id}",
        privacy=privacy,
    )


def _runtime(
    *,
    adapter: GitHubReadAdapter,
    store,
    registry: SpecialistRegistry | None = None,
    trace_sink: InMemoryTraceSink | None = None,
) -> GovernedGitHubReadService:
    active_registry = registry or default_specialist_registry()
    manifest = default_github_read_manifest()
    gateway = BudgetedToolGateway(
        registry=active_registry,
        invoker=GitHubReadToolInvoker(manifest=manifest, adapter=adapter),
        invocation_store=store,
        trace_sink=trace_sink,
    )
    return GovernedGitHubReadService(
        registry=active_registry,
        gateway=gateway,
        manifest=manifest,
        wall_clock_millis=lambda: 2_500,
    )


def _budget(task: TaskEnvelope, *, registry: SpecialistRegistry | None = None):
    active = registry or default_specialist_registry()
    return BudgetAccount(
        request_id=task.request_id,
        limits=active.effective_budget(
            agent_id="github.read",
            request_budget=task.budget,
        ),
        monotonic_millis=lambda: 0,
    )


def test_compiler_binds_exact_policy_budget_freshness_and_deadline() -> None:
    task = _task()
    request = _compiler().compile(
        task=task,
        routing=_routing(task),
        arguments=GitHubFileArguments(
            repository="Emad211/Simorgh",
            ref="main",
            path="README.md",
        ),
        invocation_id=uuid4(),
        cancellation_owner_id=uuid4(),
    )

    assert request.allowed_data_sources == frozenset({"github"})
    assert request.tool_id == GITHUB_FETCH_FILE_TOOL_ID
    assert request.cache_policy == GitHubCachePolicy.LIVE_ONLY
    assert request.minimum_fresh_until_ms == 2_000
    assert request.monotonic_timeout_ms == 30_000
    assert request.deadline_at_ms == 32_000
    assert canonical_size_bytes(request) <= default_github_read_manifest().maximum_request_bytes


def test_compiler_rejects_missing_task_connector_intersection() -> None:
    task = _task(sources=frozenset({"drive"}))
    with pytest.raises(GitHubReadPolicyError, match="no effective GitHub"):
        _compiler().compile(
            task=task,
            routing=_routing(task),
            arguments=GitHubSearchArguments(query="typed results"),
            invocation_id=uuid4(),
            cancellation_owner_id=uuid4(),
        )


def test_compiler_rejects_specialist_tool_widening() -> None:
    default = default_specialist_registry()
    github = default.get("github.read").model_copy(
        update={"tool_allowlist": frozenset({GITHUB_FETCH_FILE_TOOL_ID})}
    )
    registry = SpecialistRegistry((github,))
    task = _task()

    with pytest.raises(GitHubReadPolicyError, match="outside specialist"):
        _compiler(registry=registry).compile(
            task=task,
            routing=_routing(task),
            arguments=GitHubPullRequestArguments(
                repository="Emad211/Simorgh",
                pull_request_number=52,
            ),
            invocation_id=uuid4(),
            cancellation_owner_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("tool_id", "projection"),
    (
        (
            GITHUB_SEARCH_TOOL_ID,
            GitHubSearchProjection(
                query="typed results",
                items=(
                    GitHubSearchItem(
                        repository="Emad211/Simorgh",
                        default_branch="main",
                        visibility=GitHubVisibility.PUBLIC,
                        topics=("agents", "android"),
                        path="docs/TYPED_RESULTS.md",
                        title="Typed results",
                        source_reference="github:search:typed-results",
                    ),
                ),
                total_count_lower_bound=1,
                truncated=False,
            ),
        ),
        (
            GITHUB_FETCH_FILE_TOOL_ID,
            GitHubFileProjection(
                repository="Emad211/Simorgh",
                ref="main",
                resolved_ref_sha="a" * 40,
                path="README.md",
                blob_sha="b" * 40,
                byte_count=10,
                text="# Simorgh\n",
                text_disposition=GitHubTextDisposition.COMPLETE,
            ),
        ),
        (
            GITHUB_FETCH_ISSUE_TOOL_ID,
            GitHubIssueProjection(
                repository="Emad211/Simorgh",
                issue_number=51,
                title="Governed GitHub read tools",
                state=GitHubIssueState.OPEN,
                labels=("phase-1", "security"),
                updated_at_ms=2_000,
                truncated=False,
            ),
        ),
        (
            GITHUB_FETCH_PR_TOOL_ID,
            GitHubPullRequestProjection(
                repository="Emad211/Simorgh",
                pull_request_number=52,
                title="Core: execute governed read-only GitHub tools",
                state=GitHubPullRequestState.OPEN,
                draft=True,
                head_ref="core/governed-github-read-tools",
                base_ref="main",
                check_state=GitHubCheckState.PENDING,
                updated_at_ms=2_000,
                truncated=False,
            ),
        ),
    ),
)
def test_all_four_projection_families_map_to_stable_tainted_evidence(
    tool_id: str,
    projection,
) -> None:
    envelope = _envelope(tool_id=tool_id, projection=projection)
    evidence = github_projection_to_evidence(envelope)
    repeated = github_projection_to_evidence(
        GitHubReadProjectionEnvelope.model_validate(envelope.model_dump(mode="json"))
    )

    assert evidence == repeated
    assert evidence.tool_id == tool_id
    assert evidence.projection_sha256 == envelope.projection_sha256
    assert evidence.untrusted_source and evidence.tainted


def test_truncation_and_non_regular_object_contracts_fail_closed() -> None:
    with pytest.raises(ValidationError, match="explicit reason"):
        GitHubSearchProjection(
            query="x",
            items=(),
            total_count_lower_bound=0,
            truncated=True,
        )
    with pytest.raises(ValidationError, match="metadata-only"):
        GitHubFileProjection(
            repository="Emad211/Simorgh",
            ref="main",
            path="linked.txt",
            object_kind=GitHubObjectKind.SYMLINK,
            blob_sha="c" * 40,
            byte_count=4,
            text="oops",
            text_disposition=GitHubTextDisposition.COMPLETE,
        )

    metadata = GitHubFileProjection(
        repository="Emad211/Simorgh",
        ref="main",
        path="linked.txt",
        object_kind=GitHubObjectKind.SYMLINK,
        blob_sha="c" * 40,
        byte_count=4,
        text_disposition=GitHubTextDisposition.METADATA_ONLY,
        truncation_reason="symlink traversal is forbidden",
    )
    assert metadata.text is None


@pytest.mark.asyncio
async def test_private_projection_is_terminal_rejection_without_marker_leak() -> None:
    marker = "PRIVATE_MARKER_f8d9a11b"
    task = _task(freshness=FreshnessClass.CACHED_OK)
    request = (
        _compiler()
        .compile(
            task=task,
            routing=_routing(task),
            arguments=GitHubFileArguments(
                repository="Emad211/Simorgh",
                ref="main",
                path="private.txt",
            ),
            invocation_id=uuid4(),
            cancellation_owner_id=uuid4(),
        )
        .model_copy(update={"privacy_ceiling": PrivacyClassification.PRIVATE})
    )
    text = marker + "\n"
    projection = GitHubFileProjection(
        repository="Emad211/Simorgh",
        visibility=GitHubVisibility.PRIVATE,
        ref="main",
        path="private.txt",
        blob_sha="d" * 40,
        byte_count=len(text.encode("utf-8")),
        text=text,
        text_disposition=GitHubTextDisposition.COMPLETE,
    )
    adapter = FakeGitHubReadAdapter(
        fixtures={
            github_fixture_key(request): _envelope(
                tool_id=request.tool_id,
                projection=projection,
                privacy=PrivacyClassification.PRIVATE,
            )
        }
    )
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 3_000)
    traces = InMemoryTraceSink()

    with pytest.raises(ToolGatewayError, match="rejected"):
        await _runtime(
            adapter=adapter,
            store=store,
            trace_sink=traces,
        ).execute(task=task, request=request, budget=_budget(task))

    record = store.get(request.invocation_id)
    assert adapter.calls == 1
    assert record.state == InvocationPhase.FAILED
    assert record.failure_code == "tool_result_rejected"
    assert record.committed_usage.tool_calls == 1
    serialized = str(record.model_dump(mode="json")) + str(
        [event.model_dump(mode="json") for event in traces.for_request(task.request_id)]
    )
    assert marker not in serialized


@pytest.mark.asyncio
async def test_current_request_rejects_cache_hit_as_deterministic_failure() -> None:
    task = _task()
    request = _compiler().compile(
        task=task,
        routing=_routing(task),
        arguments=GitHubIssueArguments(
            repository="Emad211/Simorgh",
            issue_number=51,
        ),
        invocation_id=uuid4(),
        cancellation_owner_id=uuid4(),
    )
    projection = GitHubIssueProjection(
        repository="Emad211/Simorgh",
        issue_number=51,
        title="Governed read tools",
        state=GitHubIssueState.OPEN,
        updated_at_ms=1_000,
        truncated=False,
    )
    adapter = FakeGitHubReadAdapter(
        fixtures={
            github_fixture_key(request): _envelope(
                tool_id=request.tool_id,
                projection=projection,
                cache=EvidenceCacheDisposition.CACHE_HIT,
                fresh_until_ms=20_000,
            )
        }
    )
    store = InMemoryInvocationStore()

    budget = _budget(task)
    with pytest.raises(ToolGatewayError, match="rejected"):
        await _runtime(adapter=adapter, store=store).execute(
            task=task,
            request=request,
            budget=budget,
        )

    assert store.get(request.invocation_id).state == InvocationPhase.FAILED
    assert budget.snapshot().committed.tool_calls == 1


@pytest.mark.asyncio
async def test_owned_cancellation_prevents_invocation_claim_and_adapter_entry() -> None:
    task = _task()
    request = _compiler().compile(
        task=task,
        routing=_routing(task),
        arguments=GitHubSearchArguments(query="phase 1.5"),
        invocation_id=uuid4(),
        cancellation_owner_id=uuid4(),
    )
    adapter = FakeGitHubReadAdapter(fixtures={})
    store = InMemoryInvocationStore()
    cancellation = SpecialistCancellation(owner_id=request.cancellation_owner_id)
    cancellation.cancel("user cancelled")

    with pytest.raises(SpecialistExecutionCancelledError, match="user cancelled"):
        await _runtime(adapter=adapter, store=store).execute(
            task=task,
            request=request,
            budget=_budget(task),
            cancellation=cancellation,
        )

    assert adapter.calls == 0
    assert store.load() == []


@pytest.mark.asyncio
async def test_changed_arguments_under_same_invocation_identity_conflict() -> None:
    task = _task(freshness=FreshnessClass.CACHED_OK)
    request = _compiler().compile(
        task=task,
        routing=_routing(task),
        arguments=GitHubFileArguments(
            repository="Emad211/Simorgh",
            ref="main",
            path="README.md",
        ),
        invocation_id=uuid4(),
        cancellation_owner_id=uuid4(),
    )
    projection = GitHubFileProjection(
        repository="Emad211/Simorgh",
        ref="main",
        path="README.md",
        blob_sha="e" * 40,
        byte_count=10,
        text="# Simorgh\n",
        text_disposition=GitHubTextDisposition.COMPLETE,
    )
    adapter = FakeGitHubReadAdapter(
        fixtures={
            github_fixture_key(request): _envelope(
                tool_id=request.tool_id,
                projection=projection,
            )
        }
    )
    store = InMemoryInvocationStore()
    service = _runtime(adapter=adapter, store=store)
    await service.execute(task=task, request=request, budget=_budget(task))
    changed = request.model_copy(
        update={
            "arguments": GitHubFileArguments(
                repository="Emad211/Simorgh",
                ref="main",
                path="docs/README.md",
            )
        }
    )

    with pytest.raises(ToolGatewayError, match="identity"):
        await service.execute(task=task, request=changed, budget=_budget(task))
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_sqlite_replay_preserves_projection_hash_and_zero_new_usage(
    tmp_path: Path,
) -> None:
    task = _task(freshness=FreshnessClass.CACHED_OK)
    request = _compiler().compile(
        task=task,
        routing=_routing(task),
        arguments=GitHubPullRequestArguments(
            repository="Emad211/Simorgh",
            pull_request_number=52,
        ),
        invocation_id=uuid4(),
        cancellation_owner_id=uuid4(),
    )
    projection = GitHubPullRequestProjection(
        repository="Emad211/Simorgh",
        pull_request_number=52,
        title="Governed reads",
        state=GitHubPullRequestState.OPEN,
        draft=True,
        head_ref="core/governed-github-read-tools",
        base_ref="main",
        check_state=GitHubCheckState.SUCCESS,
        updated_at_ms=3_000,
        truncated=False,
    )
    envelope = _envelope(tool_id=request.tool_id, projection=projection)
    adapter = FakeGitHubReadAdapter(fixtures={github_fixture_key(request): envelope})
    path = tmp_path / "invocations.sqlite3"
    first_store = SQLiteInvocationStore(path)
    first_budget = _budget(task)
    first = await _runtime(adapter=adapter, store=first_store).execute(
        task=task,
        request=request,
        budget=first_budget,
    )
    first_store.close()

    replay_adapter = FakeGitHubReadAdapter(fixtures={})
    reopened = SQLiteInvocationStore(path)
    replay_budget = _budget(task)
    replay = await _runtime(adapter=replay_adapter, store=reopened).execute(
        task=task,
        request=request,
        budget=replay_budget,
    )

    assert first.projection.projection_sha256 == replay.projection.projection_sha256
    assert replay.replayed
    assert adapter.calls == 1
    assert replay_adapter.calls == 0
    assert first_budget.snapshot().committed.tool_calls == 1
    assert replay_budget.snapshot().committed.tool_calls == 0
    reopened.close()
