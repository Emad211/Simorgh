from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from simorgh_core.agents.budget import (
    BudgetAccount,
    BudgetError,
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
    InMemoryInvocationStore,
    InvocationStartKind,
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
    model_config = ConfigDict(extra="forbid", frozen=True)

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
    model_config = ConfigDict(extra="forbid", frozen=True)

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
    """One model call with pre-reservation, usage reconciliation, and safe replay."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        provider_id: str,
        catalog: ModelCatalog,
        invocation_store: InMemoryInvocationStore,
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
        try:
            spec = self._catalog.select(
                allowed_tiers=request.allowed_tiers,
                minimum_tier=request.minimum_tier,
            )
            if spec.provider_id != self._provider_id:
                raise ModelSelectionError(
                    f"selected provider {spec.provider_id!r} is not available in this gateway"
                )
        except ModelSelectionError as exc:
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                outcome="selection_failed",
                reason=str(exc),
            )
            raise

        selected_output_limit = min(
            request.maximum_output_tokens,
            spec.maximum_output_tokens,
        )
        fingerprint = canonical_fingerprint(
            {
                **request.model_dump(mode="json"),
                "selected_provider": spec.provider_id,
                "selected_model": spec.model_id,
                "selected_output_limit": selected_output_limit,
            }
        )
        started = self._invocations.begin(
            invocation_id=request.invocation_id,
            request_id=request.request_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            operation=request.operation,
            input_fingerprint=fingerprint,
        )
        if started.kind == InvocationStartKind.REPLAY:
            payload = started.record.result_payload
            if payload is None:
                raise ModelOutputContractError(
                    "completed model invocation has no result payload"
                )
            replayed = BudgetedModelResult.model_validate(payload)
            self._emit(
                request=request,
                kind=TraceEventKind.INVOCATION_REPLAYED,
                spec=spec,
                cache=CacheDisposition.HIT,
                outcome="completed",
                reason="exact completed model invocation was replayed",
            )
            return replayed.model_copy(update={"replayed": True})
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
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="budget_exhausted",
                failure_detail=str(exc),
            )
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                outcome="budget_exhausted",
                reason=str(exc),
            )
            raise

        self._emit(
            request=request,
            kind=TraceEventKind.BUDGET_RESERVED,
            spec=spec,
            usage=reserved_usage,
            outcome="reserved",
            reason="model call budget was reserved before provider invocation",
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
        except Exception as exc:
            # A provider may have accepted the request before the local exception. Commit the
            # conservative reservation rather than pretending a failed transport was free.
            budget.commit_reserved(reservation.reservation_id)
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="provider_failure",
                failure_detail=f"{exc.__class__.__name__}: {exc}",
            )
            self._emit(
                request=request,
                kind=TraceEventKind.MODEL_FAILED,
                spec=spec,
                usage=reserved_usage,
                outcome="provider_failure",
                reason=f"model provider failed closed with {exc.__class__.__name__}",
                output_limit=selected_output_limit,
            )
            raise ModelGatewayError("model provider invocation failed") from exc

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
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="budget_reconciliation_failed",
                failure_detail=str(exc),
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
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="provider_contract_invalid",
                failure_detail=identity_failure,
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
        self._invocations.complete(
            invocation_id=request.invocation_id,
            result_payload=result.model_dump(mode="json"),
        )
        self._emit(
            request=request,
            kind=TraceEventKind.MODEL_COMPLETED,
            spec=spec,
            usage=actual_usage,
            outcome="completed",
            reason="model output passed provider identity and budget validation",
            output_limit=selected_output_limit,
        )
        return result

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
                provider_id=spec.provider_id if spec is not None else self._provider_id,
                model_id=spec.model_id if spec is not None else None,
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
        sum(len(value.encode("utf-8")) for value in values if value is not None),
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
