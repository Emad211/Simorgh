from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.invocations import canonical_fingerprint

LIVE_PROVIDER_STAGING_CONTRACT_VERSION: Literal["1.0"] = "1.0"
AVALAI_PROVIDER_ID: Literal["avalai"] = "avalai"
AVALAI_API_BASE_URL: Literal["https://api.avalai.ir/v1"] = (
    "https://api.avalai.ir/v1"
)
AVALAI_USER_API_BASE_URL: Literal["https://api.avalai.ir/user/v1"] = (
    "https://api.avalai.ir/user/v1"
)
_MODEL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"


class LiveProviderStagingContractError(RuntimeError):
    """Base class for deterministic live-provider staging contract failures."""


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
    minimum_credit_floor_microusd: int = Field(
        default=100_000,
        ge=0,
        le=10**12,
    )
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
        return self

    @property
    def canonical_sha256(self) -> str:
        return canonical_fingerprint(self)


__all__ = [
    "AVALAI_API_BASE_URL",
    "AVALAI_PROVIDER_ID",
    "AVALAI_USER_API_BASE_URL",
    "LIVE_PROVIDER_STAGING_CONTRACT_VERSION",
    "LiveProviderStagingContractError",
    "LiveProviderStagingPolicy",
]
