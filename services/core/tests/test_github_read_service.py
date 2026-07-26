from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import ExecutionMode, TaskBudget, TaskEnvelope, TaskKind
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.github_read_adapter import (
    FakeGitHubReadAdapter,
    GitHubReadAdapter,
    GitHubReadToolInvoker,
    default_github_read_manifest,
    github_fixture_key,
)
from simorgh_core.agents.github_read_contracts import (
    GITHUB_FETCH_FILE_TOOL_ID,
    GitHubFileArguments,
    GitHubFileProjection,
    GitHubReadLimits,
    GitHubReadProjectionEnvelope,
    GitHubTextDisposition,
    GovernedGitHubReadRequest,
)
from simorgh_core.agents.github_read_service import (
    GitHubReadPolicyError,
    GovernedGitHubReadService,
)
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationPhase,
    canonical_fingerprint,
    canonical_size_bytes,
)
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
)
from simorgh_core.agents.tool_gateway import BudgetedToolGateway, ToolGatewayError


def _task(*, allowed: frozenset[str] = frozenset({"github"})) -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="فایل README سیمرغ را بررسی کن",
        requested_outcome="پروژکشن تایپ‌شده فایل",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=allowed,
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


def _request(task: TaskEnvelope) -> GovernedGitHubReadRequest:
    return GovernedGitHubReadRequest(
        request_id=task.request_id,
        invocation_id=uuid4(),
        agent_version="1.0.0",
        arguments=GitHubFileArguments(
            repository="Emad211/Simorgh",
            ref="main",
            path="README.md",
        ),
        limits=GitHubReadLimits(
            max_response_bytes=32_000,
            max_text_characters=8_000,
            max_items=10,
        ),
        privacy_ceiling=PrivacyClassification.INTERNAL,
        deadline_at_ms=task.deadline_at_ms,
        monotonic_timeout_ms=task.budget.max_elapsed_ms,
        cancellation_owner_id=uuid4(),
    )


def _envelope() -> GitHubReadProjectionEnvelope:
    projection = GitHubFileProjection(
        repository="Emad211/Simorgh",
        ref="main",
        path="README.md",
        blob_sha="b" * 40,
        byte_count=10,
        text="# Simorgh\n",
        text_disposition=GitHubTextDisposition.COMPLETE,
    )
    return GitHubReadProjectionEnvelope(
        tool_id=GITHUB_FETCH_FILE_TOOL_ID,
        projection=projection,
        projection_sha256=canonical_fingerprint(projection),
        response_bytes=canonical_size_bytes(projection),
        observed_at_ms=2_000,
        fresh_until_ms=12_000,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        citation_reference="github:Emad211/Simorgh@main:README.md",
        privacy=PrivacyClassification.INTERNAL,
    )


def _service(*, adapter: GitHubReadAdapter, invocation_store) -> GovernedGitHubReadService:
    registry = default_specialist_registry()
    manifest = default_github_read_manifest()
    gateway = BudgetedToolGateway(
        registry=registry,
        invoker=GitHubReadToolInvoker(manifest=manifest, adapter=adapter),
        invocation_store=invocation_store,
    )
    return GovernedGitHubReadService(
        registry=registry,
        gateway=gateway,
        manifest=manifest,
        wall_clock_millis=lambda: 2_500,
    )


@pytest.mark.asyncio
async def test_governed_file_read_executes_once_and_replays_without_charge() -> None:
    task = _task()
    request = _request(task)
    adapter = FakeGitHubReadAdapter(
        fixtures={github_fixture_key(request): _envelope()}
    )
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 3_000)
    service = _service(adapter=adapter, invocation_store=store)
    first_budget = BudgetAccount(
        request_id=task.request_id,
        limits=task.budget,
        monotonic_millis=lambda: 0,
    )

    first = await service.execute(task=task, request=request, budget=first_budget)
    replay_budget = BudgetAccount(
        request_id=task.request_id,
        limits=task.budget,
        monotonic_millis=lambda: 0,
    )
    replay = await service.execute(task=task, request=request, budget=replay_budget)

    assert adapter.calls == 1
    assert not first.replayed
    assert replay.replayed
    assert first.projection == replay.projection
    assert first.evidence == replay.evidence
    assert first_budget.snapshot().committed.tool_calls == 1
    assert replay_budget.snapshot().committed.tool_calls == 0
    assert first.evidence.connector_id == "github"
    assert first.evidence.tool_id == GITHUB_FETCH_FILE_TOOL_ID
    assert first.evidence.untrusted_source and first.evidence.tainted


@pytest.mark.asyncio
async def test_governed_file_read_replays_after_sqlite_reopen(tmp_path: Path) -> None:
    task = _task()
    request = _request(task)
    adapter = FakeGitHubReadAdapter(
        fixtures={github_fixture_key(request): _envelope()}
    )
    path = tmp_path / "invocations.sqlite3"
    first_store = SQLiteInvocationStore(path)
    first_service = _service(adapter=adapter, invocation_store=first_store)

    created = await first_service.execute(
        task=task,
        request=request,
        budget=BudgetAccount(
            request_id=task.request_id,
            limits=task.budget,
            monotonic_millis=lambda: 0,
        ),
    )
    first_store.close()

    replay_adapter = FakeGitHubReadAdapter(fixtures={})
    reopened = SQLiteInvocationStore(path)
    replayed = await _service(
        adapter=replay_adapter,
        invocation_store=reopened,
    ).execute(
        task=task,
        request=request,
        budget=BudgetAccount(
            request_id=task.request_id,
            limits=task.budget,
            monotonic_millis=lambda: 0,
        ),
    )

    assert created.projection == replayed.projection
    assert replayed.replayed
    assert replay_adapter.calls == 0
    reopened.close()


@pytest.mark.asyncio
async def test_task_without_github_is_rejected_before_adapter_call() -> None:
    task = _task(allowed=frozenset())
    request = _request(task)
    adapter = FakeGitHubReadAdapter(
        fixtures={github_fixture_key(request): _envelope()}
    )
    store = InMemoryInvocationStore()

    with pytest.raises(GitHubReadPolicyError, match="does not allow"):
        await _service(adapter=adapter, invocation_store=store).execute(
            task=task,
            request=request,
            budget=BudgetAccount(
                request_id=task.request_id,
                limits=task.budget,
                monotonic_millis=lambda: 0,
            ),
        )

    assert adapter.calls == 0
    assert store.load() == []


class FailingGitHubAdapter:
    connector_id = "github"
    connector_version = "1.0.0"

    def __init__(self) -> None:
        self.calls = 0

    async def invoke(
        self,
        request: GovernedGitHubReadRequest,
    ) -> GitHubReadProjectionEnvelope:
        del request
        self.calls += 1
        raise RuntimeError("SENSITIVE_FIXTURE_91ad")


@pytest.mark.asyncio
async def test_transport_error_becomes_unknown_without_message_leak() -> None:
    task = _task()
    request = _request(task)
    adapter = FailingGitHubAdapter()
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 3_000)
    budget = BudgetAccount(
        request_id=task.request_id,
        limits=task.budget,
        monotonic_millis=lambda: 0,
    )

    with pytest.raises(ToolGatewayError, match="failed"):
        await _service(adapter=adapter, invocation_store=store).execute(
            task=task,
            request=request,
            budget=budget,
        )

    record = store.get(request.invocation_id)
    assert adapter.calls == 1
    assert record.state == InvocationPhase.UNKNOWN
    assert record.failure_code == "tool_transport_uncertain"
    assert "SENSITIVE_FIXTURE_91ad" not in (record.failure_detail or "")
    assert budget.snapshot().committed.tool_calls == 1
