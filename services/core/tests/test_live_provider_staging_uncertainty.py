from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.cancellation_contracts import (
    CancellationRequesterAuthority,
    TaskCancellationRequest,
)
from simorgh_core.agents.contracts import InvocationState, UsageVector
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import InMemoryInvocationStore, InvocationStore
from simorgh_core.agents.live_provider_staging import LiveProviderStagingService
from simorgh_core.agents.live_provider_staging_contracts import (
    LIVE_PROVIDER_CANARY_OUTPUT,
    LiveProviderModelPricing,
    LiveProviderReconciliationCode,
    LiveProviderStagingDisposition,
    LiveProviderStagingPolicy,
    LiveProviderStagingRequest,
)
from simorgh_core.agents.live_provider_staging_sqlite_store import (
    SQLiteLiveProviderStagingResultStore,
)
from simorgh_core.agents.live_provider_staging_store import (
    InMemoryLiveProviderStagingResultStore,
    LiveProviderStagingResultStore,
)
from simorgh_core.providers.avalai_user_api import (
    AvalAICostSource,
    AvalAICreditSummary,
    AvalAIExactCost,
    AvalAITokenUsage,
    AvalAITransactionLookupResult,
    AvalAITransactionSummary,
    FakeAvalAIUserAPI,
)
from simorgh_core.providers.base import ModelOutput, ModelProvider

_TRANSACTION_ID = UUID("019ac4a0-a8f4-7041-845f-3ea8f15dcf1a")
_PRIVATE_MARKER = "PRIVATE_STAGING_UNCERTAINTY_MARKER"


class RecordingProvider:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.error = error
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
        if self.error is not None:
            raise self.error
        return ModelOutput(
            text=LIVE_PROVIDER_CANARY_OUTPUT,
            model=model or "",
            provider="avalai",
            request_id=str(_TRANSACTION_ID),
            usage={"input_tokens": 8, "output_tokens": 2},
        )

    async def list_models(self) -> list[str]:
        self.list_calls += 1
        return ["gpt-5.4-mini"]


class ProvenNonEntryCancellingProvider(RecordingProvider):
    def __init__(
        self,
        *,
        request: LiveProviderStagingRequest,
        invocations: InvocationStore,
    ) -> None:
        super().__init__()
        self._request = request
        self._invocations = invocations
        self.network_calls = 0

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        del input_text, model, instructions, max_output_tokens
        self.generate_calls += 1
        cancellation = TaskCancellationRequest(
            request_id=self._request.request_id,
            cancellation_id=uuid4(),
            requested_at_ms=10_100,
            reason_code="operator_requested",
            operator_reason="cancel before provider network entry",
            requester_authority=CancellationRequesterAuthority.OPERATOR,
            observed_task_phase="routed",
            observed_task_version=1,
        )
        self._invocations.accept_cancellation(cancellation)
        self._invocations.settle_reserved_cancellation(
            self._request.request_id,
            proven_not_entered=frozenset({self._request.invocation_id}),
        )
        raise asyncio.CancelledError


class CancellingLookupUserAPI:
    def __init__(self) -> None:
        self.credit_calls = 0
        self.lookup_calls = 0

    async def get_credit(self) -> AvalAICreditSummary:
        self.credit_calls += 1
        return _credit()

    async def lookup_transaction(
        self,
        transaction_id: UUID,
    ) -> AvalAITransactionLookupResult:
        del transaction_id
        self.lookup_calls += 1
        raise asyncio.CancelledError


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


def _policy() -> LiveProviderStagingPolicy:
    return LiveProviderStagingPolicy(enabled=True)


def _pricing() -> LiveProviderModelPricing:
    return LiveProviderModelPricing(
        model_id="gpt-5.4-mini",
        transaction_provider_id="openai",
        input_price_microusd_per_million_tokens=1_000_000,
        output_price_microusd_per_million_tokens=1_000_000,
        maximum_output_tokens=16,
    )


def _request() -> LiveProviderStagingRequest:
    return LiveProviderStagingRequest(
        staging_run_id=uuid4(),
        request_id=uuid4(),
        invocation_id=uuid4(),
        manual_approval=True,
    )


def _clock(start: int = 1_000) -> Callable[[], int]:
    value = start

    def now() -> int:
        nonlocal value
        value += 1
        return value

    return now


def _service(
    *,
    provider: ModelProvider,
    user_api: object,
    invocation_store: InvocationStore,
    result_store: LiveProviderStagingResultStore,
) -> LiveProviderStagingService:
    return LiveProviderStagingService(
        policy=_policy(),
        pricing=_pricing(),
        provider=provider,
        user_api=user_api,  # type: ignore[arg-type]
        invocation_store=invocation_store,
        result_store=result_store,
        wall_clock_millis=_clock(),
        monotonic_millis=lambda: 100,
    )


@pytest.mark.asyncio
async def test_positive_canary_remains_completed() -> None:
    request = _request()
    provider = RecordingProvider()
    user_api = FakeAvalAIUserAPI(
        credit=_credit(),
        transactions={_TRANSACTION_ID: _transaction()},
    )
    invocations = InMemoryInvocationStore(wall_clock_millis=_clock(10_000))
    results = InMemoryLiveProviderStagingResultStore()

    result = await _service(
        provider=provider,
        user_api=user_api,
        invocation_store=invocations,
        result_store=results,
    ).run(request)

    assert result.disposition == LiveProviderStagingDisposition.COMPLETED
    assert result.invocation_state == InvocationState.COMPLETED
    assert result.reconciliation_codes == ()
    assert provider.generate_calls == 1
    assert user_api.lookup_calls == 1


@pytest.mark.asyncio
async def test_cancel_before_provider_entry_persists_zero_usage_and_replays() -> None:
    request = _request()
    invocations = InMemoryInvocationStore(wall_clock_millis=_clock(10_000))
    results = InMemoryLiveProviderStagingResultStore()
    provider = ProvenNonEntryCancellingProvider(
        request=request,
        invocations=invocations,
    )
    user_api = FakeAvalAIUserAPI(credit=_credit())
    service = _service(
        provider=provider,
        user_api=user_api,
        invocation_store=invocations,
        result_store=results,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.run(request)

    persisted = results.get(request.staging_run_id)
    invocation = invocations.get(request.invocation_id)
    assert invocation.state == InvocationState.CANCELLED
    assert persisted.invocation_state == InvocationState.CANCELLED
    assert persisted.reconciliation_codes == (
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED,
    )
    assert persisted.committed_usage == UsageVector()
    assert provider.generate_calls == 1
    assert provider.network_calls == 0
    assert user_api.lookup_calls == 0

    replay = await _service(
        provider=provider,
        user_api=user_api,
        invocation_store=invocations,
        result_store=results,
    ).run(request)

    assert replay.replayed is True
    assert replay.canonical_sha256 == persisted.canonical_sha256
    assert provider.generate_calls == 1
    assert provider.list_calls == 1
    assert user_api.credit_calls == 1
    assert user_api.lookup_calls == 0


@pytest.mark.asyncio
async def test_cancel_after_possible_entry_persists_unknown_before_raise() -> None:
    request = _request()
    provider = RecordingProvider(error=asyncio.CancelledError())
    user_api = FakeAvalAIUserAPI(credit=_credit())
    invocations = InMemoryInvocationStore(wall_clock_millis=_clock(10_000))
    results = InMemoryLiveProviderStagingResultStore()
    service = _service(
        provider=provider,
        user_api=user_api,
        invocation_store=invocations,
        result_store=results,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.run(request)

    persisted = results.get(request.staging_run_id)
    invocation = invocations.get(request.invocation_id)
    assert invocation.state == InvocationState.UNKNOWN
    assert persisted.invocation_state == InvocationState.UNKNOWN
    assert persisted.reconciliation_codes == (
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED,
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN,
    )
    assert persisted.committed_usage == invocation.committed_usage
    assert persisted.committed_usage.model_calls == 1
    assert provider.generate_calls == 1
    assert user_api.lookup_calls == 0
    assert _PRIVATE_MARKER not in persisted.model_dump_json()

    replay = await _service(
        provider=provider,
        user_api=user_api,
        invocation_store=invocations,
        result_store=results,
    ).run(request)
    assert replay.replayed is True
    assert provider.generate_calls == 1
    assert provider.list_calls == 1
    assert user_api.credit_calls == 1
    assert user_api.lookup_calls == 0


@pytest.mark.asyncio
async def test_cancel_during_transaction_lookup_preserves_completed_invocation() -> None:
    request = _request()
    provider = RecordingProvider()
    user_api = CancellingLookupUserAPI()
    invocations = InMemoryInvocationStore(wall_clock_millis=_clock(10_000))
    results = InMemoryLiveProviderStagingResultStore()
    service = _service(
        provider=provider,
        user_api=user_api,
        invocation_store=invocations,
        result_store=results,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.run(request)

    persisted = results.get(request.staging_run_id)
    invocation = invocations.get(request.invocation_id)
    assert invocation.state == InvocationState.COMPLETED
    assert persisted.invocation_state == InvocationState.COMPLETED
    assert persisted.reconciliation_codes == (
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED,
    )
    assert persisted.provider_request_id == _TRANSACTION_ID
    assert persisted.transaction is None
    assert provider.generate_calls == 1
    assert user_api.lookup_calls == 1


@pytest.mark.asyncio
async def test_transport_uncertainty_survives_sqlite_restart_and_zero_call_replay(
    tmp_path: Path,
) -> None:
    request = _request()
    invocation_path = tmp_path / "invocations.sqlite3"
    result_path = tmp_path / "staging-results.sqlite3"
    first_invocations = SQLiteInvocationStore(
        invocation_path,
        wall_clock_millis=_clock(10_000),
    )
    first_results = SQLiteLiveProviderStagingResultStore(result_path)
    first_provider = RecordingProvider(error=TimeoutError(_PRIVATE_MARKER))
    first_user_api = FakeAvalAIUserAPI(credit=_credit())

    first = await _service(
        provider=first_provider,
        user_api=first_user_api,
        invocation_store=first_invocations,
        result_store=first_results,
    ).run(request)
    first_usage = first_invocations.get(request.invocation_id).committed_usage

    assert first.invocation_state == InvocationState.UNKNOWN
    assert first.reconciliation_codes == (
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN,
    )
    assert first_usage.model_calls == 1
    assert _PRIVATE_MARKER not in first.model_dump_json()
    first_results.close()
    first_invocations.close()

    reopened_invocations = SQLiteInvocationStore(
        invocation_path,
        wall_clock_millis=_clock(20_000),
    )
    reopened_results = SQLiteLiveProviderStagingResultStore(result_path)
    replay_provider = RecordingProvider()
    replay_user_api = FakeAvalAIUserAPI(credit=_credit())

    replay = await _service(
        provider=replay_provider,
        user_api=replay_user_api,
        invocation_store=reopened_invocations,
        result_store=reopened_results,
    ).run(request)

    assert replay.replayed is True
    assert replay.canonical_sha256 == first.canonical_sha256
    assert reopened_invocations.get(request.invocation_id).committed_usage == first_usage
    assert replay_provider.generate_calls == 0
    assert replay_provider.list_calls == 0
    assert replay_user_api.credit_calls == 0
    assert replay_user_api.lookup_calls == 0
    reopened_results.close()
    reopened_invocations.close()
