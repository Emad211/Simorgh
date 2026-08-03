from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.contracts import InvocationState, ModelTier, UsageVector
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    DurableTraceReplayDisposition,
    TraceSourceAuthorityKind,
    trace_event_id_for,
    trace_id_for,
)
from simorgh_core.providers.avalai_constants import (
    AVALAI_API_BASE_URL,
    AVALAI_PROVIDER_ID,
    AVALAI_USER_API_BASE_URL,
)
from simorgh_core.providers.avalai_user_api import (
    AvalAICreditSummary,
    AvalAITransactionSummary,
)

LIVE_PROVIDER_STAGING_CONTRACT_VERSION: Literal["1.0"] = "1.0"
LIVE_PROVIDER_CANARY_INPUT: Literal["SIMORGH_CANARY"] = "SIMORGH_CANARY"
LIVE_PROVIDER_CANARY_INSTRUCTIONS: Literal[
    "Reply exactly SIMORGH_CANARY_OK."
] = "Reply exactly SIMORGH_CANARY_OK."
LIVE_PROVIDER_CANARY_OUTPUT: Literal["SIMORGH_CANARY_OK"] = "SIMORGH_CANARY_OK"
_MODEL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"
_AGENT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_POLICY_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"


class LiveProviderStagingContractError(RuntimeError):
    """Base class for deterministic live-provider staging contract failures."""


class LiveProviderStagingDisposition(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


class LiveProviderReconciliationCode(StrEnum):
    OUTPUT_CONTRACT_INVALID = "output_contract_invalid"
    PROVIDER_INVOCATION_CANCELLED = "provider_invocation_cancelled"
    PROVIDER_INVOCATION_FAILED = "provider_invocation_failed"
    PROVIDER_INVOCATION_UNKNOWN = "provider_invocation_unknown"
    PROVIDER_REQUEST_ID_MISSING = "provider_request_id_missing"
    PROVIDER_REQUEST_ID_INVALID = "provider_request_id_invalid"
    TRANSACTION_LOOKUP_UNAVAILABLE = "transaction_lookup_unavailable"
    TRANSACTION_PENDING = "transaction_pending"
    TRANSACTION_MODEL_MISMATCH = "transaction_model_mismatch"
    TRANSACTION_PROVIDER_MISMATCH = "transaction_provider_mismatch"
    TRANSACTION_STATUS_INVALID = "transaction_status_invalid"
    TRANSACTION_STREAM_INVALID = "transaction_stream_invalid"
    TRANSACTION_USAGE_MISMATCH = "transaction_usage_mismatch"
    TRANSACTION_COST_EXCEEDED = "transaction_cost_exceeded"


class LiveProviderStagingPolicy(BaseModel):
    """Disabled-by-default authority for one manually approved AvalAI canary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    schema_version: Literal["1.0"] = LIVE_PROVIDER_STAGING_CONTRACT_VERSION
    enabled: bool = False
    provider_id: Literal["avalai"] = AVALAI_PROVIDER_ID
    api_base_url: Literal["https://api.avalai.ir/v1"] = AVALAI_API_BASE_URL
    user_api_base_url: Literal["https://api.avalai.ir/user/v1"] = (
        AVALAI_USER_API_BASE_URL
    )
    allowed_model_ids: tuple[str, ...] = ("gpt-5.4-mini",)
    selected_model_id: str = Field(
        default="gpt-5.4-mini",
        pattern=_MODEL_ID_PATTERN,
        max_length=128,
    )
    max_model_calls: Literal[1] = 1
    max_input_tokens: int = Field(default=128, ge=1, le=2_048)
    max_output_tokens: int = Field(default=16, ge=1, le=128)
    max_estimated_cost_microusd: int = Field(default=20_000, ge=1, le=1_000_000)
    minimum_credit_floor_unit: Decimal = Field(
        default=Decimal("0.10"),
        ge=0,
        max_digits=30,
        decimal_places=15,
    )
    max_exact_cost_unit: Decimal = Field(
        default=Decimal("0.01"),
        gt=0,
        max_digits=30,
        decimal_places=15,
    )
    max_elapsed_ms: int = Field(default=60_000, ge=5_000, le=300_000)
    transaction_poll_attempts: int = Field(default=6, ge=1, le=12)
    transaction_poll_interval_ms: int = Field(default=5_000, ge=1_000, le=10_000)
    user_api_timeout_ms: int = Field(default=10_000, ge=1_000, le=30_000)
    user_api_max_response_bytes: int = Field(
        default=256_000,
        ge=1_024,
        le=1_000_000,
    )

    @field_validator("allowed_model_ids")
    @classmethod
    def validate_model_allowlist(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("staging policy requires at least one reviewed model")
        if len(value) > 16:
            raise ValueError("staging model allowlist exceeds reviewed limit")
        if len(set(value)) != len(value):
            raise ValueError("staging model allowlist contains duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("staging model allowlist must be canonically sorted")
        for model_id in value:
            if not model_id or len(model_id) > 128:
                raise ValueError("staging model identity is not bounded")
        return value

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.selected_model_id not in self.allowed_model_ids:
            raise ValueError("selected staging model is outside reviewed allowlist")
        if self.max_output_tokens > self.max_input_tokens:
            raise ValueError("staging output-token limit cannot exceed input-token limit")
        polling_window_ms = (
            max(0, self.transaction_poll_attempts - 1)
            * self.transaction_poll_interval_ms
        )
        if polling_window_ms >= self.max_elapsed_ms:
            raise ValueError("staging polling window must fit elapsed-time ceiling")
        return self

    @property
    def canonical_sha256(self) -> str:
        return canonical_fingerprint(self)


class LiveProviderModelPricing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    provider_id: Literal["avalai"] = AVALAI_PROVIDER_ID
    model_id: str = Field(pattern=_MODEL_ID_PATTERN, max_length=128)
    transaction_provider_id: str = Field(pattern=_MODEL_ID_PATTERN, max_length=128)
    tier: Literal[ModelTier.FAST] = ModelTier.FAST
    input_price_microusd_per_million_tokens: int = Field(ge=0, le=10**12)
    output_price_microusd_per_million_tokens: int = Field(ge=0, le=10**12)
    maximum_output_tokens: int = Field(ge=1, le=128)

    @property
    def canonical_sha256(self) -> str:
        return canonical_fingerprint(self)


class LiveProviderStagingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = LIVE_PROVIDER_STAGING_CONTRACT_VERSION
    staging_run_id: UUID
    request_id: UUID
    invocation_id: UUID
    manual_approval: Literal[True]
    agent_id: str = Field(
        default="system.live-provider-staging",
        pattern=_AGENT_ID_PATTERN,
        max_length=128,
    )
    agent_version: str = Field(
        default="1.0.0",
        pattern=_POLICY_VERSION_PATTERN,
        max_length=32,
    )
    operation: Literal["avalai-live-canary"] = "avalai-live-canary"


class LiveProviderPreflight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = LIVE_PROVIDER_STAGING_CONTRACT_VERSION
    provider_id: Literal["avalai"] = AVALAI_PROVIDER_ID
    model_id: str = Field(pattern=_MODEL_ID_PATTERN, max_length=128)
    transaction_provider_id: str = Field(pattern=_MODEL_ID_PATTERN, max_length=128)
    policy_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    pricing_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    model_available: Literal[True] = True
    estimated_input_tokens: int = Field(ge=1, le=2_048)
    maximum_output_tokens: int = Field(ge=1, le=128)
    worst_case_estimated_cost_microusd: int = Field(ge=0, le=1_000_000)
    required_credit_unit: Decimal = Field(
        ge=0,
        max_digits=30,
        decimal_places=15,
    )
    credit_before: AvalAICreditSummary
    checked_at_ms: int = Field(ge=0)


class LiveProviderStagingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = LIVE_PROVIDER_STAGING_CONTRACT_VERSION
    staging_result_id: UUID
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    staging_run_id: UUID
    request_id: UUID
    invocation_id: UUID
    trace_id: UUID
    invocation_terminal_event_id: UUID
    provider_id: Literal["avalai"] = AVALAI_PROVIDER_ID
    model_id: str = Field(pattern=_MODEL_ID_PATTERN, max_length=128)
    transaction_provider_id: str = Field(pattern=_MODEL_ID_PATTERN, max_length=128)
    invocation_state: InvocationState
    disposition: LiveProviderStagingDisposition
    replayed: bool = False
    committed_usage: UsageVector = Field(default_factory=UsageVector)
    preflight: LiveProviderPreflight
    provider_request_id: UUID | None = None
    output_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    output_characters: int | None = Field(default=None, ge=0, le=1_000)
    transaction: AvalAITransactionSummary | None = None
    reconciliation_codes: tuple[LiveProviderReconciliationCode, ...] = Field(
        default=(),
        max_length=16,
    )
    started_at_ms: int = Field(ge=0)
    completed_at_ms: int = Field(ge=0)

    @field_validator("reconciliation_codes")
    @classmethod
    def validate_codes(
        cls,
        value: tuple[LiveProviderReconciliationCode, ...],
    ) -> tuple[LiveProviderReconciliationCode, ...]:
        if len(set(value)) != len(value):
            raise ValueError("staging reconciliation codes must be unique")
        if value != tuple(sorted(value, key=lambda item: item.value)):
            raise ValueError("staging reconciliation codes must be canonically sorted")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.trace_id != live_provider_staging_trace_id_for(self.request_id):
            raise ValueError("staging trace ID does not match request identity")
        expected_terminal_event_id = (
            live_provider_staging_terminal_event_id_for(
                request_id=self.request_id,
                invocation_id=self.invocation_id,
            )
        )
        if self.invocation_terminal_event_id != expected_terminal_event_id:
            raise ValueError(
                "staging terminal event ID does not match invocation identity"
            )
        if self.completed_at_ms < self.started_at_ms:
            raise ValueError("staging completion cannot precede start")
        if self.disposition == LiveProviderStagingDisposition.COMPLETED:
            if self.reconciliation_codes:
                raise ValueError("completed staging result cannot carry failure codes")
            if self.invocation_state != InvocationState.COMPLETED:
                raise ValueError("completed staging result requires completed invocation")
            if self.provider_request_id is None or self.transaction is None:
                raise ValueError("completed staging result requires exact transaction")
            if self.output_sha256 is None or self.output_characters is None:
                raise ValueError("completed staging result requires output fingerprint")
        elif not self.reconciliation_codes:
            raise ValueError("incomplete staging result requires a typed code")
        cancellation_recorded = (
            LiveProviderReconciliationCode.PROVIDER_INVOCATION_CANCELLED
            in self.reconciliation_codes
        )
        uncertainty_recorded = (
            LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN
            in self.reconciliation_codes
        )
        if self.invocation_state == InvocationState.CANCELLED:
            if not cancellation_recorded:
                raise ValueError(
                    "cancelled staging result requires cancellation code"
                )
            if self.committed_usage != UsageVector():
                raise ValueError(
                    "cancelled-before-entry staging result requires zero usage"
                )
        if cancellation_recorded and self.invocation_state not in {
            InvocationState.CANCELLED,
            InvocationState.COMPLETED,
            InvocationState.UNKNOWN,
        }:
            raise ValueError(
                "staging cancellation code conflicts with invocation state"
            )
        if self.invocation_state == InvocationState.UNKNOWN and not uncertainty_recorded:
            raise ValueError(
                "unknown staging invocation requires uncertainty code"
            )
        if uncertainty_recorded and self.invocation_state != InvocationState.UNKNOWN:
            raise ValueError(
                "staging uncertainty code conflicts with invocation state"
            )
        if self.provider_request_id is not None and self.provider_request_id.version != 7:
            raise ValueError("staging provider request identity must be UUIDv7")
        if (
            self.transaction is not None
            and self.provider_request_id != self.transaction.transaction_id
        ):
            raise ValueError("staging transaction identity does not match provider request")
        if self.canonical_sha256 != live_provider_staging_result_sha256(self):
            raise ValueError("staging result hash does not match authoritative content")
        expected_id = live_provider_staging_result_id_for(
            staging_run_id=self.staging_run_id,
            canonical_sha256=self.canonical_sha256,
        )
        if self.staging_result_id != expected_id:
            raise ValueError("staging result ID does not match canonical identity")
        return self


def live_provider_staging_trace_id_for(request_id: UUID) -> UUID:
    return trace_id_for(request_id)


def live_provider_staging_terminal_event_id_for(
    *,
    request_id: UUID,
    invocation_id: UUID,
) -> UUID:
    return trace_event_id_for(
        trace_id=live_provider_staging_trace_id_for(request_id),
        source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
        source_authority_id=invocation_id,
        event_kind=DurableTraceEventKind.INVOCATION_TERMINAL,
        replay=DurableTraceReplayDisposition.FRESH,
    )


def live_provider_staging_result_payload(
    value: LiveProviderStagingResult | dict[str, object],
) -> dict[str, object]:
    payload = (
        value.model_dump(mode="json")
        if isinstance(value, LiveProviderStagingResult)
        else dict(value)
    )
    for field in (
        "staging_result_id",
        "canonical_sha256",
        "replayed",
        "trace_id",
        "invocation_terminal_event_id",
        "started_at_ms",
        "completed_at_ms",
    ):
        payload.pop(field, None)
    return payload


def live_provider_staging_result_sha256(
    value: LiveProviderStagingResult | dict[str, object],
) -> str:
    return canonical_fingerprint(live_provider_staging_result_payload(value))


def live_provider_staging_result_id_for(
    *,
    staging_run_id: UUID,
    canonical_sha256: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"simorgh-live-provider-staging:{staging_run_id}:{canonical_sha256}",
    )


__all__ = [
    "AVALAI_API_BASE_URL",
    "AVALAI_PROVIDER_ID",
    "AVALAI_USER_API_BASE_URL",
    "LIVE_PROVIDER_CANARY_INPUT",
    "LIVE_PROVIDER_CANARY_INSTRUCTIONS",
    "LIVE_PROVIDER_CANARY_OUTPUT",
    "LIVE_PROVIDER_STAGING_CONTRACT_VERSION",
    "LiveProviderModelPricing",
    "LiveProviderPreflight",
    "LiveProviderReconciliationCode",
    "LiveProviderStagingContractError",
    "LiveProviderStagingDisposition",
    "LiveProviderStagingPolicy",
    "LiveProviderStagingRequest",
    "LiveProviderStagingResult",
    "live_provider_staging_result_id_for",
    "live_provider_staging_result_payload",
    "live_provider_staging_result_sha256",
    "live_provider_staging_terminal_event_id_for",
    "live_provider_staging_trace_id_for",
]
