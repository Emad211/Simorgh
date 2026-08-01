from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum
from uuid import UUID

from simorgh_core.agents.budget import BudgetAccount, BudgetError
from simorgh_core.agents.contracts import InvocationState, ModelTier, TaskBudget
from simorgh_core.agents.invocations import (
    InvocationNotFoundError,
    InvocationRecord,
    InvocationStore,
    InvocationStoreError,
)
from simorgh_core.agents.live_provider_staging_contracts import (
    AVALAI_PROVIDER_ID,
    LIVE_PROVIDER_CANARY_INPUT,
    LIVE_PROVIDER_CANARY_INSTRUCTIONS,
    LIVE_PROVIDER_CANARY_OUTPUT,
    LiveProviderModelPricing,
    LiveProviderPreflight,
    LiveProviderReconciliationCode,
    LiveProviderStagingDisposition,
    LiveProviderStagingPolicy,
    LiveProviderStagingRequest,
    LiveProviderStagingResult,
    live_provider_staging_result_id_for,
    live_provider_staging_result_sha256,
)
from simorgh_core.agents.live_provider_staging_store import (
    LiveProviderStagingClaimKind,
    LiveProviderStagingResultStore,
    LiveProviderStagingStoreNotFoundError,
)
from simorgh_core.agents.model_gateway import (
    BudgetedModelGateway,
    BudgetedModelRequest,
    BudgetedModelResult,
    ModelCatalog,
    ModelGatewayError,
    ModelSpec,
    conservative_token_upper_bound,
    estimate_cost_microusd,
)
from simorgh_core.providers.avalai_user_api import (
    AvalAITransactionLookupResult,
    AvalAITransactionSummary,
    AvalAIUserAPI,
    AvalAIUserAPIError,
)
from simorgh_core.providers.base import ModelProvider


class LiveProviderPreflightErrorCode(StrEnum):
    POLICY_DISABLED = "policy_disabled"
    PRICING_MISMATCH = "pricing_mismatch"
    COST_CEILING_EXCEEDED = "cost_ceiling_exceeded"
    CREDIT_UNAVAILABLE = "credit_unavailable"
    INSUFFICIENT_CREDIT = "insufficient_credit"
    MODEL_CATALOG_UNAVAILABLE = "model_catalog_unavailable"
    MODEL_CATALOG_INVALID = "model_catalog_invalid"
    MODEL_UNAVAILABLE = "model_unavailable"


class LiveProviderPreflightError(RuntimeError):
    """Sanitized pre-call failure that proves no canary request was issued."""

    def __init__(self, code: LiveProviderPreflightErrorCode) -> None:
        super().__init__(f"live-provider staging preflight failed: {code.value}")
        self.code = code


class LiveProviderStagingExecutionError(RuntimeError):
    """Sanitized failure when staging evidence cannot be durably represented."""


class LiveProviderStagingService:
    """One fixed, budgeted canary with exact durable replay and reconciliation."""

    def __init__(
        self,
        *,
        policy: LiveProviderStagingPolicy,
        pricing: LiveProviderModelPricing,
        provider: ModelProvider,
        user_api: AvalAIUserAPI,
        invocation_store: InvocationStore,
        result_store: LiveProviderStagingResultStore,
        wall_clock_millis: Callable[[], int],
        monotonic_millis: Callable[[], int],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._policy = policy
        self._pricing = pricing
        self._provider = provider
        self._user_api = user_api
        self._invocations = invocation_store
        self._results = result_store
        self._wall_clock_millis = wall_clock_millis
        self._monotonic_millis = monotonic_millis
        self._sleep = sleep
        self._gateway = BudgetedModelGateway(
            provider=provider,
            provider_id=AVALAI_PROVIDER_ID,
            catalog=ModelCatalog((self._model_spec(),)),
            invocation_store=invocation_store,
        )

    async def run(
        self,
        request: LiveProviderStagingRequest,
    ) -> LiveProviderStagingResult:
        existing = self._load_existing_result(request)
        if existing is not None:
            return existing.model_copy(update={"replayed": True})

        started_at_ms = self._now_ms()
        preflight = await self._preflight()
        budget = BudgetAccount(
            request_id=request.request_id,
            limits=TaskBudget(
                max_model_calls=1,
                max_tool_calls=0,
                max_input_tokens=self._policy.max_input_tokens,
                max_output_tokens=self._policy.max_output_tokens,
                max_estimated_cost_microusd=(
                    self._policy.max_estimated_cost_microusd
                ),
                max_elapsed_ms=self._policy.max_elapsed_ms,
                max_retries=0,
                max_parallel_branches=1,
            ),
            monotonic_millis=self._monotonic_millis,
        )
        gateway_result: BudgetedModelResult | None = None
        gateway_failed = False
        try:
            gateway_result = await self._gateway.generate(
                request=BudgetedModelRequest(
                    invocation_id=request.invocation_id,
                    request_id=request.request_id,
                    agent_id=request.agent_id,
                    agent_version=request.agent_version,
                    operation=request.operation,
                    input_text=LIVE_PROVIDER_CANARY_INPUT,
                    instructions=LIVE_PROVIDER_CANARY_INSTRUCTIONS,
                    allowed_tiers=(ModelTier.FAST,),
                    minimum_tier=ModelTier.FAST,
                    maximum_output_tokens=self._policy.max_output_tokens,
                    policy_hash=self._policy.canonical_sha256,
                ),
                budget=budget,
            )
        except asyncio.CancelledError:
            raise
        except (BudgetError, ModelGatewayError):
            gateway_failed = True

        invocation = self._require_invocation(request.invocation_id)
        codes: set[LiveProviderReconciliationCode] = set()
        provider_request_id: UUID | None = None
        output_sha256: str | None = None
        output_characters: int | None = None
        transaction: AvalAITransactionSummary | None = None

        if gateway_failed:
            if invocation.state in {
                InvocationState.UNKNOWN,
                InvocationState.UNKNOWN_SIDE_EFFECT,
            }:
                codes.add(
                    LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN
                )
            else:
                codes.add(
                    LiveProviderReconciliationCode.PROVIDER_INVOCATION_FAILED
                )
        elif gateway_result is not None:
            output_sha256 = hashlib.sha256(
                gateway_result.text.encode("utf-8")
            ).hexdigest()
            output_characters = len(gateway_result.text)
            if gateway_result.text != LIVE_PROVIDER_CANARY_OUTPUT:
                codes.add(LiveProviderReconciliationCode.OUTPUT_CONTRACT_INVALID)
            provider_request_id = _provider_request_uuid(
                gateway_result.provider_request_id,
                codes=codes,
            )
            if provider_request_id is not None:
                transaction = await self._lookup_transaction(
                    provider_request_id,
                    codes=codes,
                )
                if transaction is not None:
                    _reconcile_transaction(
                        transaction=transaction,
                        gateway_result=gateway_result,
                        pricing=self._pricing,
                        policy=self._policy,
                        codes=codes,
                    )

        completed_at_ms = self._now_ms()
        disposition = (
            LiveProviderStagingDisposition.COMPLETED
            if not codes
            and invocation.state == InvocationState.COMPLETED
            and gateway_result is not None
            and provider_request_id is not None
            and transaction is not None
            else LiveProviderStagingDisposition.INCOMPLETE
        )
        record = _new_result(
            request=request,
            policy=self._policy,
            pricing=self._pricing,
            preflight=preflight,
            invocation=invocation,
            disposition=disposition,
            provider_request_id=provider_request_id,
            output_sha256=output_sha256,
            output_characters=output_characters,
            transaction=transaction,
            codes=tuple(sorted(codes, key=lambda item: item.value)),
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
        )
        claim = self._results.claim(record)
        return claim.record.model_copy(
            update={
                "replayed": claim.kind == LiveProviderStagingClaimKind.REPLAY,
            }
        )

    def _load_existing_result(
        self,
        request: LiveProviderStagingRequest,
    ) -> LiveProviderStagingResult | None:
        try:
            existing = self._results.get(request.staging_run_id)
        except LiveProviderStagingStoreNotFoundError:
            return None
        if (
            existing.request_id != request.request_id
            or existing.invocation_id != request.invocation_id
        ):
            raise LiveProviderStagingExecutionError(
                "staging run identity conflicts with durable result"
            )
        return existing

    async def _preflight(self) -> LiveProviderPreflight:
        if not self._policy.enabled:
            raise LiveProviderPreflightError(
                LiveProviderPreflightErrorCode.POLICY_DISABLED
            )
        self._require_pricing_identity()
        estimated_input_tokens = conservative_token_upper_bound(
            LIVE_PROVIDER_CANARY_INPUT,
            LIVE_PROVIDER_CANARY_INSTRUCTIONS,
        )
        spec = self._model_spec()
        worst_case_cost = estimate_cost_microusd(
            input_tokens=estimated_input_tokens,
            output_tokens=self._policy.max_output_tokens,
            spec=spec,
        )
        if worst_case_cost > self._policy.max_estimated_cost_microusd:
            raise LiveProviderPreflightError(
                LiveProviderPreflightErrorCode.COST_CEILING_EXCEEDED
            )
        try:
            credit = await self._user_api.get_credit()
        except AvalAIUserAPIError:
            raise LiveProviderPreflightError(
                LiveProviderPreflightErrorCode.CREDIT_UNAVAILABLE
            ) from None
        required_credit = (
            self._policy.minimum_credit_floor_unit
            + self._policy.max_exact_cost_unit
        )
        if credit.remaining_unit < required_credit:
            raise LiveProviderPreflightError(
                LiveProviderPreflightErrorCode.INSUFFICIENT_CREDIT
            )
        try:
            models = await self._provider.list_models()
        except Exception:
            raise LiveProviderPreflightError(
                LiveProviderPreflightErrorCode.MODEL_CATALOG_UNAVAILABLE
            ) from None
        _require_model_catalog(models)
        if self._policy.selected_model_id not in models:
            raise LiveProviderPreflightError(
                LiveProviderPreflightErrorCode.MODEL_UNAVAILABLE
            )
        return LiveProviderPreflight(
            model_id=self._policy.selected_model_id,
            transaction_provider_id=self._pricing.transaction_provider_id,
            policy_sha256=self._policy.canonical_sha256,
            pricing_sha256=self._pricing.canonical_sha256,
            estimated_input_tokens=estimated_input_tokens,
            maximum_output_tokens=self._policy.max_output_tokens,
            worst_case_estimated_cost_microusd=worst_case_cost,
            required_credit_unit=required_credit,
            credit_before=credit,
            checked_at_ms=self._now_ms(),
        )

    def _require_pricing_identity(self) -> None:
        if (
            self._pricing.provider_id != self._policy.provider_id
            or self._pricing.model_id != self._policy.selected_model_id
            or self._pricing.maximum_output_tokens < self._policy.max_output_tokens
        ):
            raise LiveProviderPreflightError(
                LiveProviderPreflightErrorCode.PRICING_MISMATCH
            )

    def _model_spec(self) -> ModelSpec:
        return ModelSpec(
            provider_id=self._pricing.provider_id,
            model_id=self._pricing.model_id,
            tier=ModelTier.FAST,
            input_price_microusd_per_million_tokens=(
                self._pricing.input_price_microusd_per_million_tokens
            ),
            output_price_microusd_per_million_tokens=(
                self._pricing.output_price_microusd_per_million_tokens
            ),
            maximum_output_tokens=self._pricing.maximum_output_tokens,
        )

    async def _lookup_transaction(
        self,
        provider_request_id: UUID,
        *,
        codes: set[LiveProviderReconciliationCode],
    ) -> AvalAITransactionSummary | None:
        for attempt in range(self._policy.transaction_poll_attempts):
            try:
                lookup = await self._user_api.lookup_transaction(
                    provider_request_id
                )
            except AvalAIUserAPIError:
                codes.add(
                    LiveProviderReconciliationCode.TRANSACTION_LOOKUP_UNAVAILABLE
                )
                return None
            if lookup.transaction is not None:
                return lookup.transaction
            if attempt + 1 == self._policy.transaction_poll_attempts:
                break
            if _rate_limit_wait_exceeds_policy(lookup, self._policy):
                codes.add(
                    LiveProviderReconciliationCode.TRANSACTION_LOOKUP_UNAVAILABLE
                )
                return None
            await self._sleep(self._policy.transaction_poll_interval_ms / 1_000)
        codes.add(LiveProviderReconciliationCode.TRANSACTION_PENDING)
        return None

    def _require_invocation(self, invocation_id: UUID) -> InvocationRecord:
        try:
            return self._invocations.get(invocation_id)
        except (InvocationNotFoundError, InvocationStoreError):
            raise LiveProviderStagingExecutionError(
                "staging invocation authority is unavailable"
            ) from None

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))


def _require_model_catalog(models: Sequence[str]) -> None:
    if len(models) > 256 or len(set(models)) != len(models):
        raise LiveProviderPreflightError(
            LiveProviderPreflightErrorCode.MODEL_CATALOG_INVALID
        )
    if any(not model_id or len(model_id) > 128 for model_id in models):
        raise LiveProviderPreflightError(
            LiveProviderPreflightErrorCode.MODEL_CATALOG_INVALID
        )


def _provider_request_uuid(
    value: str | None,
    *,
    codes: set[LiveProviderReconciliationCode],
) -> UUID | None:
    if value is None:
        codes.add(LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_MISSING)
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        codes.add(LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_INVALID)
        return None
    if parsed.version != 7:
        codes.add(LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_INVALID)
        return None
    return parsed


def _reconcile_transaction(
    *,
    transaction: AvalAITransactionSummary,
    gateway_result: BudgetedModelResult,
    pricing: LiveProviderModelPricing,
    policy: LiveProviderStagingPolicy,
    codes: set[LiveProviderReconciliationCode],
) -> None:
    if transaction.model != pricing.model_id:
        codes.add(LiveProviderReconciliationCode.TRANSACTION_MODEL_MISMATCH)
    if transaction.provider != pricing.transaction_provider_id:
        codes.add(LiveProviderReconciliationCode.TRANSACTION_PROVIDER_MISMATCH)
    if transaction.status_code < 200 or transaction.status_code >= 300:
        codes.add(LiveProviderReconciliationCode.TRANSACTION_STATUS_INVALID)
    if transaction.stream:
        codes.add(LiveProviderReconciliationCode.TRANSACTION_STREAM_INVALID)
    if (
        transaction.tokens.prompt != gateway_result.input_tokens
        or transaction.tokens.completion != gateway_result.output_tokens
        or transaction.tokens.total
        != gateway_result.input_tokens + gateway_result.output_tokens
        or transaction.tokens.reasoning != 0
        or transaction.tokens.cached != 0
    ):
        codes.add(LiveProviderReconciliationCode.TRANSACTION_USAGE_MISMATCH)
    if transaction.cost.unit > policy.max_exact_cost_unit:
        codes.add(LiveProviderReconciliationCode.TRANSACTION_COST_EXCEEDED)


def _rate_limit_wait_exceeds_policy(
    lookup: AvalAITransactionLookupResult,
    policy: LiveProviderStagingPolicy,
) -> bool:
    reset_after_ms = lookup.rate_limit.reset_after_ms
    return (
        reset_after_ms is not None
        and reset_after_ms > policy.transaction_poll_interval_ms
    )


def _new_result(
    *,
    request: LiveProviderStagingRequest,
    policy: LiveProviderStagingPolicy,
    pricing: LiveProviderModelPricing,
    preflight: LiveProviderPreflight,
    invocation: InvocationRecord,
    disposition: LiveProviderStagingDisposition,
    provider_request_id: UUID | None,
    output_sha256: str | None,
    output_characters: int | None,
    transaction: AvalAITransactionSummary | None,
    codes: tuple[LiveProviderReconciliationCode, ...],
    started_at_ms: int,
    completed_at_ms: int,
) -> LiveProviderStagingResult:
    provisional = LiveProviderStagingResult.model_construct(
        schema_version="1.0",
        staging_result_id=UUID(int=0),
        canonical_sha256="0" * 64,
        staging_run_id=request.staging_run_id,
        request_id=request.request_id,
        invocation_id=request.invocation_id,
        provider_id=policy.provider_id,
        model_id=policy.selected_model_id,
        transaction_provider_id=pricing.transaction_provider_id,
        invocation_state=invocation.state,
        disposition=disposition,
        replayed=False,
        committed_usage=invocation.committed_usage,
        preflight=preflight,
        provider_request_id=provider_request_id,
        output_sha256=output_sha256,
        output_characters=output_characters,
        transaction=transaction,
        reconciliation_codes=codes,
        started_at_ms=started_at_ms,
        completed_at_ms=completed_at_ms,
    )
    canonical_sha256 = live_provider_staging_result_sha256(provisional)
    return LiveProviderStagingResult.model_validate(
        {
            **provisional.model_dump(mode="json"),
            "staging_result_id": live_provider_staging_result_id_for(
                staging_run_id=request.staging_run_id,
                canonical_sha256=canonical_sha256,
            ),
            "canonical_sha256": canonical_sha256,
        }
    )


__all__ = [
    "LiveProviderPreflightError",
    "LiveProviderPreflightErrorCode",
    "LiveProviderStagingExecutionError",
    "LiveProviderStagingService",
]
