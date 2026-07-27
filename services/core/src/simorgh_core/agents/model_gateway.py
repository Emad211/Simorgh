from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from contextlib import suppress
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from simorgh_core.agents.budget import (
    BudgetAccount,
    BudgetCancelledError,
    BudgetError,
    BudgetReservationNotFoundError,
    ReservationKind,
)
from simorgh_core.agents.contracts import (
    AgentClassification,
    ModelTier,
    SpecialistDefinition,
    TaskEnvelope,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    InvocationNotFoundError,
    InvocationRecord,
    InvocationStartKind,
    InvocationStateError,
    InvocationStore,
    InvocationStoreError,
    canonical_fingerprint,
)
from simorgh_core.agents.tracing import (
    CacheDisposition,
    NullTraceSink,
    TraceEventKind,
    TraceSink,
    trace_event,
)
from simorgh_core.providers.base import ModelOutput, ModelProvider

_MICROUSD_PER_USD = 1_000_000
_PRICE_DENOMINATOR = 1_000_000
_TIER_RANK = {
    ModelTier.FAST: 0,
    ModelTier.GENERAL: 1,
    ModelTier.REASONING: 2,
    ModelTier.DOMAIN: 3,
}


class ModelGatewayError(RuntimeError):
    """Base class for governed model invocation failures."""


class ModelSelectionError(ModelGatewayError):
    pass


class ModelInvocationInProgressError(ModelGatewayError):
    pass


class ModelInvocationTerminalError(ModelGatewayError):
    pass


class ModelOutputContractError(ModelGatewayError):
    pass


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=256)
    tier: ModelTier
    input_price_microusd_per_million_tokens: int = Field(ge=0, le=10**12)
    output_price_microusd_per_million_tokens: int = Field(ge=0, le=10**12)
    maximum_output_tokens: int = Field(ge=1, le=10_000_000)
    enabled: bool = True


class ModelCatalog:
    """Select the cheapest model in the lowest policy-sufficient tier."""

    def __init__(self, specs: Sequence[ModelSpec]) -> None:
        by_identity: dict[tuple[str, str], ModelSpec] = {}
        for spec in specs:
            key = (spec.provider_id, spec.model_id)
            if key in by_identity:
                raise ValueError(f"duplicate model specification {key!r}")
            by_identity[key] = spec
        self._specs = tuple(by_identity.values())

    def select(
        self,
        *,
        allowed_tiers: Sequence[ModelTier],
        minimum_tier: ModelTier | None = None,
    ) -> ModelSpec:
        if not allowed_tiers:
            raise ModelSelectionError("model policy does not allow any model tier")
        allowed = set(allowed_tiers)
        minimum_rank = _TIER_RANK[minimum_tier] if minimum_tier is not None else 0
        candidates = [
            spec
            for spec in self._specs
            if spec.enabled
            and spec.tier in allowed
            and _TIER_RANK[spec.tier] >= minimum_rank
        ]
        if not candidates:
            raise ModelSelectionError(
                "no enabled model satisfies allowed tiers and minimum tier"
            )
        selected_rank = min(_TIER_RANK[spec.tier] for spec in candidates)
        sufficient = [
            spec for spec in candidates if _TIER_RANK[spec.tier] == selected_rank
        ]
        return min(
            sufficient,
            key=lambda spec: (
                spec.input_price_microusd_per_million_tokens
                + spec.output_price_microusd_per_million_tokens,
                spec.output_price_microusd_per_million_tokens,
                spec.provider_id,
                spec.model_id,
            ),
        )


class BudgetedModelRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    invocation_id: UUID
    request_id: UUID
    agent_id: str = Field(min_length=1, max_length=128)
    agent_version: str = Field(min_length=1, max_length=32)
    operation: str = Field(min_length=1, max_length=128)
    input_text: str = Field(min_length=1, max_length=200_000)
    instructions: str | None = Field(default=None, max_length=20_000)
    allowed_tiers: tuple[ModelTier, ...] = Field(min_length=1, max_length=4)
    minimum_tier: ModelTier | None = None
    maximum_output_tokens: int = Field(ge=1, le=1_000_000)
    cancellation_owner_id: UUID | None = None
    policy_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )

    @field_validator("allowed_tiers")
    @classmethod
    def validate_unique_tiers(
        cls,
        value: tuple[ModelTier, ...],
    ) -> tuple[ModelTier, ...]:
        if len(set(value)) != len(value):
            raise ValueError("allowed model tiers must be unique")
        return value


class BudgetedModelResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: UUID
    text: str
    provider_id: str
    model_id: str
    provider_request_id: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_microusd: int = Field(ge=0)
    replayed: bool = False


class BudgetedModelGateway:
    """One durable model call with pre-reservation and exact restart replay."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        provider_id: str,
        catalog: ModelCatalog,
        invocation_store: InvocationStore,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self._provider = provider
        self._provider_id = provider_id
        self._catalog = catalog
        self._invocations = invocation_store
        self._trace_sink = trace_sink or NullTraceSink()

    async def generate(
        self,
        *,
        request: BudgetedModelRequest,
        budget: BudgetAccount,
    ) -> BudgetedModelResult:
        self._require_budget_identity(request=request, budget=budget)
        request_fingerprint = canonical_fingerprint(request)
        existing = self._load_existing_invocation(request.invocation_id)
        if existing is not None:
            return self._resolve_existing_invocation(
                request=request,
                record=existing,
                request_fingerprint=request_fingerprint,
            )
        spec = self._select_model(request)
        selected_output_limit = min(
            request.maximum_output_tokens,
            spec.maximum_output_tokens,
        )
        fingerprint = request_fingerprint
        try:
            started = self._invocations.begin(
                invocation_id=request.invocation_id,
                request_id=request.request_id,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                operation=request.operation,
                input_fingerprint=fingerprint,
                kind=InvocationKind.MODEL,
                effect=InvocationEffect.READ_ONLY,
                provider_id=spec.provider_id,
                model_id=spec.model_id,
                cancellation_owner_id=request.cancellation_owner_id,
            )
        except InvocationStoreError as exc:
            raise ModelGatewayError(
                "model invocation identity could not be durably claimed"
            ) from exc

        if started.kind == InvocationStartKind.REPLAY:
            return self._replay_result(
                request=request,
                spec=spec,
                payload=started.record.result_payload,
                committed_usage=started.record.committed_usage,
            )
        if started.kind == InvocationStartKind.IN_PROGRESS:
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                outcome="in_progress",
                reason="model invocation identity is already in progress",
            )
            raise ModelInvocationInProgressError(
                f"model invocation {request.invocation_id} is already in progress"
            )
        if started.kind == InvocationStartKind.TERMINAL:
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                outcome="terminal",
                reason="model invocation identity is already terminal",
            )
            raise ModelInvocationTerminalError(
                started.record.failure_detail
                or f"model invocation ended in {started.record.state.value}"
            )

        estimated_input_tokens = conservative_token_upper_bound(
            request.input_text,
            request.instructions,
        )
        reserved_usage = UsageVector(
            model_calls=1,
            input_tokens=estimated_input_tokens,
            output_tokens=selected_output_limit,
            estimated_cost_microusd=estimate_cost_microusd(
                input_tokens=estimated_input_tokens,
                output_tokens=selected_output_limit,
                spec=spec,
            ),
        )
        try:
            reservation = budget.reserve(
                kind=ReservationKind.MODEL,
                usage=reserved_usage,
            )
        except BudgetError as exc:
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="budget_exhausted",
                failure_detail=str(exc),
                committed_usage=UsageVector(),
            )
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                outcome="budget_exhausted",
                reason=str(exc),
            )
            raise

        try:
            self._invocations.reserve(
                invocation_id=request.invocation_id,
                usage=reserved_usage,
            )
        except InvocationStoreError:
            with suppress(
                BudgetCancelledError,
                BudgetReservationNotFoundError,
            ):
                budget.release(reservation.reservation_id)
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                outcome="invocation_store_failure",
                reason="model call was not issued because durable reservation failed",
            )
            raise ModelGatewayError(
                "model invocation could not be durably reserved"
            ) from None

        self._emit(
            request=request,
            kind=TraceEventKind.BUDGET_RESERVED,
            spec=spec,
            usage=reserved_usage,
            outcome="reserved",
            reason="model call budget and durable invocation usage were reserved",
        )
        self._emit(
            request=request,
            kind=TraceEventKind.MODEL_STARTED,
            spec=spec,
            cache=CacheDisposition.MISS,
            outcome="started",
            reason="cheapest policy-sufficient model invocation started",
            output_limit=selected_output_limit,
        )
        try:
            output = await self._provider.generate_text(
                input_text=request.input_text,
                model=spec.model_id,
                instructions=request.instructions,
                max_output_tokens=selected_output_limit,
            )
        except asyncio.CancelledError:
            with suppress(ModelGatewayError):
                self._mark_unknown_and_settle(
                    invocation_id=request.invocation_id,
                    failure_code="provider_call_cancelled",
                    failure_detail=(
                        "model provider coroutine was cancelled after durable reservation; "
                        "completion is uncertain"
                    ),
                    budget=budget,
                    reservation_id=reservation.reservation_id,
                )
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                usage=reserved_usage,
                outcome="unknown",
                reason="model provider coroutine was cancelled after reservation",
                output_limit=selected_output_limit,
            )
            raise
        except Exception as exc:
            self._mark_unknown_and_settle(
                invocation_id=request.invocation_id,
                failure_code="provider_transport_uncertain",
                failure_detail=exc.__class__.__name__,
                budget=budget,
                reservation_id=reservation.reservation_id,
            )
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                usage=reserved_usage,
                outcome="unknown",
                reason=f"model transport became uncertain with {exc.__class__.__name__}",
                output_limit=selected_output_limit,
            )
            raise ModelGatewayError("model provider invocation failed") from None

        actual_input_tokens = usage_value(
            output,
            "input_tokens",
            fallback=estimated_input_tokens,
        )
        actual_output_tokens = usage_value(
            output,
            "output_tokens",
            fallback=selected_output_limit,
        )
        actual_usage = UsageVector(
            model_calls=1,
            input_tokens=actual_input_tokens,
            output_tokens=actual_output_tokens,
            estimated_cost_microusd=estimate_cost_microusd(
                input_tokens=actual_input_tokens,
                output_tokens=actual_output_tokens,
                spec=spec,
            ),
        )
        try:
            budget.reconcile(
                reservation_id=reservation.reservation_id,
                actual_usage=actual_usage,
            )
        except BudgetError as exc:
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="budget_reconciliation_failed",
                failure_detail=str(exc),
                committed_usage=actual_usage,
            )
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                usage=actual_usage,
                outcome="budget_reconciliation_failed",
                reason=str(exc),
                output_limit=selected_output_limit,
            )
            raise

        self._emit(
            request=request,
            kind=TraceEventKind.BUDGET_RECONCILED,
            spec=spec,
            usage=actual_usage,
            outcome="reconciled",
            reason="provider-reported or conservative model usage was reconciled",
            output_limit=selected_output_limit,
        )
        identity_failure = provider_identity_failure(output=output, spec=spec)
        if actual_output_tokens > selected_output_limit:
            identity_failure = (
                f"provider reported {actual_output_tokens} output tokens above "
                f"the selected limit {selected_output_limit}"
            )
        if identity_failure is not None:
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="provider_contract_invalid",
                failure_detail=identity_failure,
                committed_usage=actual_usage,
            )
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                usage=actual_usage,
                outcome="provider_contract_invalid",
                reason=identity_failure,
                output_limit=selected_output_limit,
            )
            raise ModelOutputContractError(identity_failure)

        result = BudgetedModelResult(
            invocation_id=request.invocation_id,
            text=output.text,
            provider_id=spec.provider_id,
            model_id=spec.model_id,
            provider_request_id=output.request_id,
            input_tokens=actual_input_tokens,
            output_tokens=actual_output_tokens,
            cost_microusd=actual_usage.estimated_cost_microusd,
        )
        try:
            self._invocations.complete(
                invocation_id=request.invocation_id,
                result_payload=result.model_dump(mode="json"),
                committed_usage=actual_usage,
            )
        except InvocationStateError:
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="result_contract_invalid",
                failure_detail="typed_model_result_rejected",
                committed_usage=actual_usage,
            )
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                usage=actual_usage,
                outcome="result_contract_invalid",
                reason="model result failed the durable typed result contract",
                output_limit=selected_output_limit,
            )
            raise ModelOutputContractError(
                "model result failed durable contract validation"
            ) from None
        except InvocationStoreError:
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                usage=actual_usage,
                outcome="invocation_store_failure",
                reason="model result could not be durably committed",
                output_limit=selected_output_limit,
            )
            raise ModelGatewayError(
                "model result could not be durably committed"
            ) from None
        self._emit(
            request=request,
            kind=TraceEventKind.MODEL_COMPLETED,
            spec=spec,
            usage=actual_usage,
            outcome="completed",
            reason="model output passed identity, budget, and durable-store validation",
            output_limit=selected_output_limit,
        )
        return result

    def _require_budget_identity(
        self,
        *,
        request: BudgetedModelRequest,
        budget: BudgetAccount,
    ) -> None:
        if budget.request_id == request.request_id:
            return
        self._emit(
            request=request,
            kind=TraceEventKind.MODEL_FAILED,
            outcome="budget_identity_mismatch",
            reason="model request and request budget identities do not match",
        )
        raise ModelGatewayError(
            "model request budget identity does not match request"
        )

    def _load_existing_invocation(
        self,
        invocation_id: UUID,
    ) -> InvocationRecord | None:
        try:
            return self._invocations.get(invocation_id)
        except InvocationNotFoundError:
            return None
        except InvocationStoreError:
            raise ModelGatewayError(
                "durable model invocation could not be read"
            ) from None

    def _resolve_existing_invocation(
        self,
        *,
        request: BudgetedModelRequest,
        record: InvocationRecord,
        request_fingerprint: str,
    ) -> BudgetedModelResult:
        if (
            record.kind != InvocationKind.MODEL
            or record.effect != InvocationEffect.READ_ONLY
            or record.provider_id != self._provider_id
            or record.model_id is None
        ):
            raise ModelGatewayError(
                "durable model invocation target does not match this gateway"
            )
        try:
            started = self._invocations.begin(
                invocation_id=request.invocation_id,
                request_id=request.request_id,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                operation=request.operation,
                input_fingerprint=request_fingerprint,
                kind=InvocationKind.MODEL,
                effect=InvocationEffect.READ_ONLY,
                provider_id=record.provider_id,
                model_id=record.model_id,
            )
        except InvocationStoreError:
            raise ModelGatewayError(
                "durable model invocation identity could not be validated"
            ) from None
        if started.kind == InvocationStartKind.REPLAY:
            return self._replay_stored_result(request=request, record=started.record)
        if started.kind == InvocationStartKind.IN_PROGRESS:
            raise ModelInvocationInProgressError(
                f"model invocation {request.invocation_id} is already in progress"
            )
        raise ModelInvocationTerminalError(
            started.record.failure_detail
            or f"model invocation ended in {started.record.state.value}"
        )

    def _replay_stored_result(
        self,
        *,
        request: BudgetedModelRequest,
        record: InvocationRecord,
    ) -> BudgetedModelResult:
        if record.result_payload is None:
            raise ModelOutputContractError(
                "completed model invocation has no result payload"
            )
        try:
            replayed = BudgetedModelResult.model_validate(record.result_payload)
        except ValueError:
            raise ModelOutputContractError(
                "durable model replay payload failed typed validation"
            ) from None
        expected_usage = UsageVector(
            model_calls=1,
            input_tokens=replayed.input_tokens,
            output_tokens=replayed.output_tokens,
            estimated_cost_microusd=replayed.cost_microusd,
        )
        if (
            replayed.invocation_id != request.invocation_id
            or replayed.provider_id != record.provider_id
            or replayed.model_id != record.model_id
            or record.committed_usage != expected_usage
        ):
            raise ModelOutputContractError(
                "durable model replay identity or usage is inconsistent"
            )
        self._emit(
            request=request,
            kind=TraceEventKind.INVOCATION_REPLAYED,
            cache=CacheDisposition.HIT,
            outcome="completed",
            reason="exact completed model invocation was replayed from durable state",
            provider_id_override=record.provider_id,
            model_id_override=record.model_id,
        )
        return replayed.model_copy(update={"replayed": True})

    def _mark_unknown_and_settle(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
        budget: BudgetAccount,
        reservation_id: UUID,
    ) -> None:
        store_failed = False
        try:
            self._invocations.mark_unknown(
                invocation_id=invocation_id,
                failure_code=failure_code,
                failure_detail=failure_detail,
            )
        except InvocationStoreError:
            store_failed = True

        # Always attempt request-budget settlement even when durable persistence
        # failed. Cancellation can clear the process-local reservation; in that
        # case the durable invocation remains detailed cost authority and startup
        # reconciliation raises the retained parent aggregate.
        try:
            budget.commit_reserved(reservation_id)
        except (BudgetCancelledError, BudgetReservationNotFoundError):
            pass
        except BudgetError:
            # BudgetAccount records truthful over-limit usage before raising.
            pass

        if store_failed:
            raise ModelGatewayError(
                "model invocation uncertainty could not be durably recorded"
            ) from None

    def _select_model(self, request: BudgetedModelRequest) -> ModelSpec:
        try:
            spec = self._catalog.select(
                allowed_tiers=request.allowed_tiers,
                minimum_tier=request.minimum_tier,
            )
            if spec.provider_id != self._provider_id:
                raise ModelSelectionError(
                    f"selected provider {spec.provider_id!r} is not available in this gateway"
                )
            return spec
        except ModelSelectionError as exc:
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                outcome="selection_failed",
                reason=str(exc),
            )
            raise

    def _replay_result(
        self,
        *,
        request: BudgetedModelRequest,
        spec: ModelSpec,
        payload: dict[str, Any] | None,
        committed_usage: UsageVector,
    ) -> BudgetedModelResult:
        if payload is None:
            raise ModelOutputContractError(
                "completed model invocation has no result payload"
            )
        replayed = BudgetedModelResult.model_validate(payload)
        expected_usage = UsageVector(
            model_calls=1,
            input_tokens=replayed.input_tokens,
            output_tokens=replayed.output_tokens,
            estimated_cost_microusd=replayed.cost_microusd,
        )
        if replayed.invocation_id != request.invocation_id:
            raise ModelOutputContractError(
                "durable model result invocation identity does not match request"
            )
        if replayed.provider_id != spec.provider_id or replayed.model_id != spec.model_id:
            raise ModelOutputContractError(
                "durable model result target identity does not match selected model"
            )
        if committed_usage != expected_usage:
            raise ModelOutputContractError(
                "durable model result usage does not match invocation accounting"
            )
        self._emit(
            request=request,
            kind=TraceEventKind.INVOCATION_REPLAYED,
            spec=spec,
            cache=CacheDisposition.HIT,
            outcome="completed",
            reason="exact completed model invocation was replayed from durable state",
        )
        return replayed.model_copy(update={"replayed": True})

    def _record_failure(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
        committed_usage: UsageVector,
    ) -> None:
        try:
            self._invocations.fail(
                invocation_id=invocation_id,
                failure_code=failure_code,
                failure_detail=failure_detail,
                committed_usage=committed_usage,
            )
        except InvocationStoreError as exc:
            raise ModelGatewayError(
                "model invocation failure could not be durably recorded"
            ) from exc

    def _mark_unknown(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> None:
        try:
            self._invocations.mark_unknown(
                invocation_id=invocation_id,
                failure_code=failure_code,
                failure_detail=failure_detail,
            )
        except InvocationStoreError as exc:
            raise ModelGatewayError(
                "model invocation uncertainty could not be durably recorded"
            ) from exc

    def _emit(
        self,
        *,
        request: BudgetedModelRequest,
        kind: TraceEventKind,
        spec: ModelSpec | None = None,
        cache: CacheDisposition = CacheDisposition.NOT_APPLICABLE,
        usage: UsageVector | None = None,
        outcome: str | None = None,
        reason: str | None = None,
        output_limit: int | None = None,
        provider_id_override: str | None = None,
        model_id_override: str | None = None,
    ) -> None:
        metadata: dict[str, str | int | bool | None] = {
            "operation": request.operation,
        }
        if spec is not None:
            metadata["tier"] = spec.tier.value
        if output_limit is not None:
            metadata["output_limit"] = output_limit
        self._trace_sink.emit(
            trace_event(
                request_id=request.request_id,
                invocation_id=request.invocation_id,
                kind=kind,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                provider_id=(
                    provider_id_override
                    if provider_id_override is not None
                    else spec.provider_id if spec is not None else self._provider_id
                ),
                model_id=(
                    model_id_override
                    if model_id_override is not None
                    else spec.model_id if spec is not None else None
                ),
                cache=cache,
                usage=usage,
                outcome=outcome,
                reason=reason,
                metadata=metadata,
            )
        )


class BudgetedAgentClassifier:
    """Strict JSON classifier using one budgeted, idempotent model invocation."""

    def __init__(
        self,
        *,
        gateway: BudgetedModelGateway,
        policy_hash: str,
        allowed_tiers: tuple[ModelTier, ...] = (ModelTier.FAST,),
        minimum_tier: ModelTier | None = ModelTier.FAST,
        maximum_output_tokens: int = 256,
    ) -> None:
        self._gateway = gateway
        self._policy_hash = policy_hash
        self._allowed_tiers = allowed_tiers
        self._minimum_tier = minimum_tier
        self._maximum_output_tokens = maximum_output_tokens

    async def classify(
        self,
        *,
        task: TaskEnvelope,
        candidates: Sequence[SpecialistDefinition],
        budget: BudgetAccount,
        invocation_id: UUID,
    ) -> AgentClassification:
        candidate_payload = [
            {
                "agent_id": candidate.agent_id,
                "display_name": candidate.display_name,
                "task_kinds": sorted(kind.value for kind in candidate.task_kinds),
                "side_effect_policy": candidate.side_effect_policy.value,
            }
            for candidate in candidates
        ]
        input_payload = {
            "locale": task.locale,
            "input_text": task.input_text,
            "requested_outcome": task.requested_outcome,
            "risk_class": task.risk_class.value,
            "freshness": task.freshness.value,
            "execution_mode": task.execution_mode.value,
            "candidates": candidate_payload,
        }
        result = await self._gateway.generate(
            request=BudgetedModelRequest(
                invocation_id=invocation_id,
                request_id=task.request_id,
                agent_id="system.specialist-router",
                agent_version="1.0.0",
                operation="classify-primary-specialist",
                input_text=json.dumps(
                    input_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                instructions=(
                    "Return only one JSON object with keys selected_agent_id, "
                    "confidence_bps (0..10000), and reason. Select exactly one agent_id "
                    "from candidates. Do not propose tools, subagents, or side effects."
                ),
                allowed_tiers=self._allowed_tiers,
                minimum_tier=self._minimum_tier,
                maximum_output_tokens=self._maximum_output_tokens,
                policy_hash=self._policy_hash,
            ),
            budget=budget,
        )
        try:
            decoded: Any = json.loads(result.text)
            if not isinstance(decoded, dict):
                raise TypeError("classifier output must be a JSON object")
            return AgentClassification.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ModelOutputContractError(
                f"classifier output failed strict JSON contract validation: {exc}"
            ) from exc


def conservative_token_upper_bound(*values: str | None) -> int:
    """UTF-8 byte count is intentionally conservative and tokenizer-independent."""

    return max(
        1,
        sum(len(value.encode()) for value in values if value is not None),
    )


def estimate_cost_microusd(
    *,
    input_tokens: int,
    output_tokens: int,
    spec: ModelSpec,
) -> int:
    input_cost = ceil_div(
        input_tokens * spec.input_price_microusd_per_million_tokens,
        _PRICE_DENOMINATOR,
    )
    output_cost = ceil_div(
        output_tokens * spec.output_price_microusd_per_million_tokens,
        _PRICE_DENOMINATOR,
    )
    return min(_MICROUSD_PER_USD * 1_000_000, input_cost + output_cost)


def provider_identity_failure(*, output: ModelOutput, spec: ModelSpec) -> str | None:
    if output.provider != spec.provider_id:
        return (
            f"provider identity {output.provider!r} does not match selected "
            f"provider {spec.provider_id!r}"
        )
    if output.model != spec.model_id:
        return (
            f"provider model identity {output.model!r} does not match selected "
            f"model {spec.model_id!r}"
        )
    return None


def usage_value(output: ModelOutput, key: str, *, fallback: int) -> int:
    usage = output.usage or {}
    raw = usage.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return fallback
    return raw


def ceil_div(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ValueError("ceil_div requires a non-negative numerator and positive denominator")
    return (numerator + denominator - 1) // denominator
