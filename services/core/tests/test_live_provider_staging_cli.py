from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID

import pytest

import simorgh_core.app as app_module
from simorgh_core.agents.live_provider_staging_artifact import (
    LiveProviderExternalCallCounts,
    LiveProviderStagingArtifactDisposition,
    LiveProviderStagingArtifactFailureCode,
)
from simorgh_core.agents.live_provider_staging_cli import (
    execute_manual_live_provider_staging,
    reviewed_live_provider_staging_policy,
    reviewed_live_provider_staging_pricing,
)
from simorgh_core.agents.live_provider_staging_contracts import (
    LIVE_PROVIDER_CANARY_OUTPUT,
    LiveProviderReconciliationDisposition,
)
from simorgh_core.config import Settings
from simorgh_core.providers.avalai_user_api import (
    AvalAICostSource,
    AvalAICreditSummary,
    AvalAIExactCost,
    AvalAITokenUsage,
    AvalAITransactionLookupResult,
    AvalAITransactionSummary,
    AvalAIUserAPIError,
    AvalAIUserAPIErrorCode,
    FakeAvalAIUserAPI,
)
from simorgh_core.providers.base import ModelOutput

_TRANSACTION_ID = UUID("019ac4a0-a8f4-7041-845f-3ea8f15dcf1a")
_IDS = (
    UUID("11111111-1111-4111-8111-111111111111"),
    UUID("22222222-2222-4222-8222-222222222222"),
    UUID("33333333-3333-4333-8333-333333333333"),
)
_SOURCE_COMMIT = "a" * 40


class FakeRecordingProvider:
    def __init__(self) -> None:
        self.generate_calls = 0
        self.list_calls = 0

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        del input_text, instructions, max_output_tokens
        self.generate_calls += 1
        return ModelOutput(
            text=LIVE_PROVIDER_CANARY_OUTPUT,
            model=model or "gpt-5.4-mini",
            provider="avalai",
            request_id=str(_TRANSACTION_ID),
            usage={"input_tokens": 8, "output_tokens": 2},
        )

    async def list_models(self) -> list[str]:
        self.list_calls += 1
        return ["gpt-5.4-mini"]


class LookupUnavailableUserAPI:
    def __init__(self, credit: AvalAICreditSummary) -> None:
        self.credit = credit
        self.credit_calls = 0
        self.lookup_calls = 0

    async def get_credit(self) -> AvalAICreditSummary:
        self.credit_calls += 1
        return self.credit

    async def lookup_transaction(
        self,
        transaction_id: UUID,
    ) -> AvalAITransactionLookupResult:
        del transaction_id
        self.lookup_calls += 1
        raise AvalAIUserAPIError(AvalAIUserAPIErrorCode.RATE_LIMITED)


def _settings() -> Settings:
    return Settings(
        simorgh_env="test",
        simorgh_action_journal_path=":memory:",
        simorgh_agent_task_store_path=":memory:",
        simorgh_invocation_store_path=":memory:",
        simorgh_result_store_path=":memory:",
        simorgh_context_store_path=":memory:",
        simorgh_trace_store_path=":memory:",
        simorgh_live_provider_staging_result_store_path=":memory:",
    )


def _credit() -> AvalAICreditSummary:
    return AvalAICreditSummary(
        limit_irt=Decimal("0"),
        remaining_irt=Decimal("100000"),
        remaining_unit=Decimal("1"),
        total_unit=Decimal("1"),
        exchange_rate_irt_per_unit=100000,
        account_tier=1,
    )


def _transaction() -> AvalAITransactionSummary:
    return AvalAITransactionSummary(
        transaction_id=_TRANSACTION_ID,
        created_at="2026-08-03T00:00:20Z",
        requested_at="2026-08-03T00:00:10Z",
        model="gpt-5.4-mini",
        provider="openai",
        status_code=200,
        stream=False,
        tokens=AvalAITokenUsage(
            total=10,
            prompt=8,
            completion=2,
            reasoning=0,
            cached=0,
        ),
        cost=AvalAIExactCost(
            unit=Decimal("0.001"),
            paid_unit=Decimal("0.001"),
            paid_irt=Decimal("0"),
            paid_grant_irt=Decimal("0"),
            source=AvalAICostSource.CREDIT,
            currency="UNIT",
        ),
    )


def _id_factory() -> Iterator[UUID]:
    yield from _IDS


async def _no_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_manual_composition_uses_native_authorities_and_proves_zero_call_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    provider = FakeRecordingProvider()
    user_api = FakeAvalAIUserAPI(
        credit=_credit(),
        transactions={_TRANSACTION_ID: _transaction()},
    )
    ids = _id_factory()

    artifact = await execute_manual_live_provider_staging(
        policy=reviewed_live_provider_staging_policy("gpt-5.4-mini"),
        pricing=reviewed_live_provider_staging_pricing("gpt-5.4-mini"),
        provider=provider,
        user_api=user_api,
        source_commit_sha=_SOURCE_COMMIT,
        workflow_run_id=123,
        workflow_run_attempt=1,
        wall_clock_millis=iter(range(1_000, 2_000)).__next__,
        monotonic_millis=lambda: 100,
        sleep=_no_sleep,
        id_factory=ids.__next__,
    )

    evidence = artifact.model_dump(mode="json")
    assert artifact.disposition == LiveProviderStagingArtifactDisposition.PASSED, evidence
    assert artifact.failure_code == LiveProviderStagingArtifactFailureCode.NONE
    assert artifact.result is not None
    assert artifact.result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.EXACT
    )
    assert artifact.trace_evidence is not None
    assert artifact.replay_observed is True
    assert artifact.replay_delta_calls == LiveProviderExternalCallCounts()
    assert artifact.usage_before_replay == artifact.usage_after_replay
    assert artifact.first_run_calls == LiveProviderExternalCallCounts(
        model_catalog_calls=1,
        model_generate_calls=1,
        credit_calls=1,
        transaction_lookup_calls=1,
    )
    assert provider.generate_calls == 1
    assert provider.list_calls == 1
    assert user_api.credit_calls == 1
    assert user_api.lookup_calls == 1
    serialized = str(evidence)
    assert LIVE_PROVIDER_CANARY_OUTPUT not in serialized


@pytest.mark.asyncio
async def test_manual_composition_emits_failed_artifact_without_model_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    provider = FakeRecordingProvider()
    user_api = LookupUnavailableUserAPI(_credit())
    ids = _id_factory()

    artifact = await execute_manual_live_provider_staging(
        policy=reviewed_live_provider_staging_policy("gpt-5.4-mini"),
        pricing=reviewed_live_provider_staging_pricing("gpt-5.4-mini"),
        provider=provider,
        user_api=user_api,
        source_commit_sha=_SOURCE_COMMIT,
        workflow_run_id=124,
        workflow_run_attempt=1,
        wall_clock_millis=iter(range(2_000, 3_000)).__next__,
        monotonic_millis=lambda: 100,
        sleep=_no_sleep,
        id_factory=ids.__next__,
    )

    evidence = artifact.model_dump(mode="json")
    assert artifact.disposition == LiveProviderStagingArtifactDisposition.FAILED
    assert artifact.failure_code == (
        LiveProviderStagingArtifactFailureCode.RESULT_INCOMPLETE
    ), evidence
    assert artifact.result is not None
    assert artifact.result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.UNAVAILABLE
    )
    assert artifact.replay_delta_calls == LiveProviderExternalCallCounts()
    assert provider.generate_calls == 1
    assert provider.list_calls == 1
    assert user_api.credit_calls == 1
    assert user_api.lookup_calls == 1
