from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.invocations import InMemoryInvocationStore
from simorgh_core.agents.live_provider_staging import (
    LiveProviderPreflightError,
    LiveProviderPreflightErrorCode,
    LiveProviderStagingService,
)
from simorgh_core.agents.live_provider_staging_contracts import (
    LIVE_PROVIDER_CANARY_INPUT,
    LIVE_PROVIDER_CANARY_INSTRUCTIONS,
    LIVE_PROVIDER_CANARY_OUTPUT,
    LiveProviderModelPricing,
    LiveProviderReconciliationCode,
    LiveProviderReconciliationDisposition,
    LiveProviderStagingDisposition,
    LiveProviderStagingPolicy,
    LiveProviderStagingRequest,
)
from simorgh_core.agents.live_provider_staging_store import (
    InMemoryLiveProviderStagingResultStore,
)
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
_PRIVATE_OUTPUT = "private-model-output-marker"


class RecordingProvider:
    def __init__(
        self,
        *,
        text: str = LIVE_PROVIDER_CANARY_OUTPUT,
        request_id: str | None = str(_TRANSACTION_ID),
        models: list[str] | None = None,
        error: Exception | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self.text = text
        self.request_id = request_id
        self.models = models or ["gpt-5.4-mini"]
        self.error = error
        self.list_error = list_error
        self.generate_calls = 0
        self.list_calls = 0
        self.inputs: list[str] = []
        self.instructions: list[str | None] = []
        self.output_limits: list[int | None] = []

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        self.generate_calls += 1
        self.inputs.append(input_text)
        self.instructions.append(instructions)
        self.output_limits.append(max_output_tokens)
        if self.error is not None:
            raise self.error
        return ModelOutput(
            text=self.text,
            model=model or "",
            provider="avalai",
            request_id=self.request_id,
            usage={"input_tokens": 8, "output_tokens": 2},
        )

    async def list_models(self) -> list[str]:
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return list(self.models)


class PendingUserAPI:
    def __init__(
        self,
        *,
        credit: AvalAICreditSummary,
        pending_attempts: int,
        transaction: AvalAITransactionSummary,
        error_on_lookup: bool = False,
    ) -> None:
        self.credit = credit
        self.pending_attempts = pending_attempts
        self.transaction = transaction
        self.error_on_lookup = error_on_lookup
        self.credit_calls = 0
        self.lookup_calls = 0

    async def get_credit(self) -> AvalAICreditSummary:
        self.credit_calls += 1
        return self.credit

    async def lookup_transaction(
        self,
        transaction_id: UUID,
    ) -> AvalAITransactionLookupResult:
        self.lookup_calls += 1
        if self.error_on_lookup:
            raise AvalAIUserAPIError(AvalAIUserAPIErrorCode.RATE_LIMITED)
        found = self.lookup_calls > self.pending_attempts
        return AvalAITransactionLookupResult(
            requested_transaction_id=transaction_id,
            found=found,
            transaction=self.transaction if found else None,
        )


def _credit(*, remaining_unit: str = "1.00") -> AvalAICreditSummary:
    return AvalAICreditSummary(
        limit_irt=Decimal("0"),
        remaining_irt=Decimal("100000"),
        remaining_unit=Decimal(remaining_unit),
        total_unit=Decimal(remaining_unit),
        exchange_rate_irt_per_unit=100000,
        account_tier=1,
    )


def _transaction(
    *,
    model: str = "gpt-5.4-mini",
    provider: str = "openai",
    prompt_tokens: int = 8,
    completion_tokens: int = 2,
    exact_unit: str = "0.001",
    transaction_id: UUID = _TRANSACTION_ID,
) -> AvalAITransactionSummary:
    return AvalAITransactionSummary(
        transaction_id=transaction_id,
        created_at="2026-08-01T02:00:20Z",
        requested_at="2026-08-01T02:00:10Z",
        model=model,
        provider=provider,
        status_code=200,
        stream=False,
        tokens=AvalAITokenUsage(
            total=prompt_tokens + completion_tokens,
            prompt=prompt_tokens,
            completion=completion_tokens,
            reasoning=0,
            cached=0,
        ),
        cost=AvalAIExactCost(
            unit=Decimal(exact_unit),
            paid_unit=Decimal(exact_unit),
            paid_irt=Decimal("0"),
            paid_grant_irt=Decimal("0"),
            source=AvalAICostSource.CREDIT,
            currency="UNIT",
        ),
    )


def _policy(**updates: object) -> LiveProviderStagingPolicy:
    return LiveProviderStagingPolicy(
        enabled=True,
        minimum_credit_floor_unit=Decimal("0.10"),
        max_exact_cost_unit=Decimal("0.01"),
        **updates,
    )


def _pricing(**updates: object) -> LiveProviderModelPricing:
    payload: dict[str, object] = {
        "model_id": "gpt-5.4-mini",
        "transaction_provider_id": "openai",
        "input_price_microusd_per_million_tokens": 1_000_000,
        "output_price_microusd_per_million_tokens": 1_000_000,
        "maximum_output_tokens": 16,
    }
    payload.update(updates)
    return LiveProviderModelPricing.model_validate(payload)


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
    provider: RecordingProvider,
    user_api: object,
    policy: LiveProviderStagingPolicy | None = None,
    pricing: LiveProviderModelPricing | None = None,
    invocation_store: InMemoryInvocationStore | None = None,
    result_store: InMemoryLiveProviderStagingResultStore | None = None,
    sleep: Callable[[float], object] | None = None,
) -> tuple[
    LiveProviderStagingService,
    InMemoryInvocationStore,
    InMemoryLiveProviderStagingResultStore,
]:
    invocations = invocation_store or InMemoryInvocationStore(
        wall_clock_millis=_clock(10_000)
    )
    results = result_store or InMemoryLiveProviderStagingResultStore()

    async def no_sleep(_: float) -> None:
        return None

    selected_sleep = sleep if sleep is not None else no_sleep
    return (
        LiveProviderStagingService(
            policy=policy or _policy(),
            pricing=pricing or _pricing(),
            provider=provider,
            user_api=user_api,  # type: ignore[arg-type]
            invocation_store=invocations,
            result_store=results,
            wall_clock_millis=_clock(),
            monotonic_millis=lambda: 100,
            sleep=selected_sleep,  # type: ignore[arg-type]
        ),
        invocations,
        results,
    )


@pytest.mark.asyncio
async def test_successful_canary_uses_one_budgeted_call_and_sanitized_result() -> None:
    request = _request()
    provider = RecordingProvider()
    user_api = FakeAvalAIUserAPI(
        credit=_credit(),
        transactions={_TRANSACTION_ID: _transaction()},
    )
    service, invocations, _ = _service(provider=provider, user_api=user_api)

    result = await service.run(request)

    assert result.disposition == LiveProviderStagingDisposition.COMPLETED
    assert result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.EXACT
    )
    assert result.reconciliation_codes == ()
    assert result.provider_request_id == _TRANSACTION_ID
    assert result.transaction is not None
    assert result.committed_usage.model_calls == 1
    assert provider.generate_calls == 1
    assert provider.list_calls == 1
    assert user_api.credit_calls == 1
    assert user_api.lookup_calls == 1
    assert provider.inputs == [LIVE_PROVIDER_CANARY_INPUT]
    assert provider.instructions == [LIVE_PROVIDER_CANARY_INSTRUCTIONS]
    assert provider.output_limits == [16]
    assert invocations.get(request.invocation_id).committed_usage == result.committed_usage
    serialized = str(result.model_dump(mode="json"))
    assert LIVE_PROVIDER_CANARY_OUTPUT not in serialized
    assert _PRIVATE_OUTPUT not in serialized


@pytest.mark.asyncio
async def test_exact_staging_replay_performs_zero_provider_and_user_api_calls() -> None:
    request = _request()
    provider = RecordingProvider()
    user_api = FakeAvalAIUserAPI(
        credit=_credit(),
        transactions={_TRANSACTION_ID: _transaction()},
    )
    service, invocations, results = _service(provider=provider, user_api=user_api)
    first = await service.run(request)

    second_service, _, _ = _service(
        provider=provider,
        user_api=user_api,
        invocation_store=invocations,
        result_store=results,
    )
    replay = await second_service.run(request)

    assert replay.replayed is True
    assert replay.staging_result_id == first.staging_result_id
    assert replay.canonical_sha256 == first.canonical_sha256
    assert provider.generate_calls == 1
    assert provider.list_calls == 1
    assert user_api.credit_calls == 1
    assert user_api.lookup_calls == 1


@pytest.mark.asyncio
async def test_disabled_policy_and_insufficient_credit_block_before_model_entry() -> None:
    request = _request()
    provider = RecordingProvider()
    user_api = FakeAvalAIUserAPI(credit=_credit(remaining_unit="0.01"))
    disabled, invocations, _ = _service(
        provider=provider,
        user_api=user_api,
        policy=LiveProviderStagingPolicy(),
    )

    with pytest.raises(LiveProviderPreflightError) as disabled_error:
        await disabled.run(request)
    assert disabled_error.value.code == LiveProviderPreflightErrorCode.POLICY_DISABLED
    assert provider.list_calls == 0
    assert provider.generate_calls == 0
    assert user_api.credit_calls == 0
    assert invocations.load() == []

    enabled, invocations, _ = _service(provider=provider, user_api=user_api)
    with pytest.raises(LiveProviderPreflightError) as credit_error:
        await enabled.run(request)
    assert credit_error.value.code == LiveProviderPreflightErrorCode.INSUFFICIENT_CREDIT
    assert provider.list_calls == 0
    assert provider.generate_calls == 0
    assert user_api.credit_calls == 1
    assert invocations.load() == []


@pytest.mark.asyncio
async def test_unavailable_model_and_pricing_mismatch_block_before_model_entry() -> None:
    request = _request()
    provider = RecordingProvider(models=["another-model"])
    user_api = FakeAvalAIUserAPI(credit=_credit())
    service, invocations, _ = _service(provider=provider, user_api=user_api)

    with pytest.raises(LiveProviderPreflightError) as unavailable:
        await service.run(request)
    assert unavailable.value.code == LiveProviderPreflightErrorCode.MODEL_UNAVAILABLE
    assert provider.generate_calls == 0
    assert invocations.load() == []

    mismatched, invocations, _ = _service(
        provider=RecordingProvider(),
        user_api=FakeAvalAIUserAPI(credit=_credit()),
        pricing=_pricing(model_id="different-model"),
    )
    with pytest.raises(LiveProviderPreflightError) as mismatch:
        await mismatched.run(request)
    assert mismatch.value.code == LiveProviderPreflightErrorCode.PRICING_MISMATCH
    assert invocations.load() == []


@pytest.mark.asyncio
async def test_pending_transaction_polls_without_second_model_call() -> None:
    request = _request()
    provider = RecordingProvider()
    user_api = PendingUserAPI(
        credit=_credit(),
        pending_attempts=2,
        transaction=_transaction(),
    )
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    service, _, _ = _service(
        provider=provider,
        user_api=user_api,
        sleep=record_sleep,
    )
    result = await service.run(request)

    assert result.disposition == LiveProviderStagingDisposition.COMPLETED
    assert provider.generate_calls == 1
    assert user_api.lookup_calls == 3
    assert sleeps == [5.0, 5.0]


@pytest.mark.asyncio
async def test_transaction_pending_and_lookup_error_are_incomplete_without_retry() -> None:
    request = _request()
    provider = RecordingProvider()
    pending_api = PendingUserAPI(
        credit=_credit(),
        pending_attempts=99,
        transaction=_transaction(),
    )
    pending_service, _, _ = _service(
        provider=provider,
        user_api=pending_api,
        policy=_policy(transaction_poll_attempts=2),
    )
    pending = await pending_service.run(request)

    assert pending.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert pending.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.PENDING
    )
    assert pending.reconciliation_codes == (
        LiveProviderReconciliationCode.TRANSACTION_PENDING,
    )
    assert provider.generate_calls == 1
    assert pending_api.lookup_calls == 2

    lookup_provider = RecordingProvider()
    failing_api = PendingUserAPI(
        credit=_credit(),
        pending_attempts=0,
        transaction=_transaction(),
        error_on_lookup=True,
    )
    failing_service, _, _ = _service(
        provider=lookup_provider,
        user_api=failing_api,
    )
    unavailable = await failing_service.run(_request())
    assert unavailable.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.UNAVAILABLE
    )
    assert unavailable.reconciliation_codes == (
        LiveProviderReconciliationCode.TRANSACTION_LOOKUP_UNAVAILABLE,
    )
    assert lookup_provider.generate_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "expected"),
    (
        (
            RecordingProvider(request_id=None),
            LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_MISSING,
        ),
        (
            RecordingProvider(request_id="not-a-uuid"),
            LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_INVALID,
        ),
        (
            RecordingProvider(request_id=str(uuid4())),
            LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_INVALID,
        ),
        (
            RecordingProvider(text="wrong-output"),
            LiveProviderReconciliationCode.OUTPUT_CONTRACT_INVALID,
        ),
    ),
)
async def test_post_call_contract_failures_are_incomplete_and_never_retry_model(
    provider: RecordingProvider,
    expected: LiveProviderReconciliationCode,
) -> None:
    user_api = FakeAvalAIUserAPI(
        credit=_credit(),
        transactions={_TRANSACTION_ID: _transaction()},
    )
    service, _, _ = _service(provider=provider, user_api=user_api)

    result = await service.run(_request())

    assert result.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert expected in result.reconciliation_codes
    assert provider.generate_calls == 1


@pytest.mark.asyncio
async def test_transaction_identity_usage_and_cost_mismatch_are_typed() -> None:
    request = _request()
    provider = RecordingProvider()
    transaction = _transaction(
        model="other-model",
        provider="other-provider",
        prompt_tokens=9,
        completion_tokens=2,
        exact_unit="0.02",
    )
    user_api = FakeAvalAIUserAPI(
        credit=_credit(),
        transactions={_TRANSACTION_ID: transaction},
    )
    service, _, _ = _service(provider=provider, user_api=user_api)

    result = await service.run(request)

    assert result.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.MISMATCH
    )
    assert result.reconciliation_codes == (
        LiveProviderReconciliationCode.TRANSACTION_COST_EXCEEDED,
        LiveProviderReconciliationCode.TRANSACTION_MODEL_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_PROVIDER_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_USAGE_MISMATCH,
    )
    assert provider.generate_calls == 1


@pytest.mark.asyncio
async def test_provider_transport_uncertainty_is_recorded_without_retry() -> None:
    request = _request()
    provider = RecordingProvider(error=RuntimeError(_PRIVATE_OUTPUT))
    user_api = FakeAvalAIUserAPI(credit=_credit())
    service, invocations, _ = _service(provider=provider, user_api=user_api)

    result = await service.run(request)

    assert result.disposition == LiveProviderStagingDisposition.INCOMPLETE
    assert result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.UNAVAILABLE
    )
    assert result.reconciliation_codes == (
        LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN,
    )
    assert result.invocation_state == invocations.get(request.invocation_id).state
    assert provider.generate_calls == 1
    assert user_api.lookup_calls == 0
    assert _PRIVATE_OUTPUT not in str(result.model_dump(mode="json"))
