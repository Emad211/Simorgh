from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.live_provider_staging_contracts import (
    AVALAI_API_BASE_URL,
    AVALAI_USER_API_BASE_URL,
    LiveProviderStagingPolicy,
    LiveProviderStagingRequest,
)


def test_staging_policy_is_disabled_and_single_call_by_default() -> None:
    policy = LiveProviderStagingPolicy()

    assert policy.enabled is False
    assert policy.max_model_calls == 1
    assert policy.api_base_url == AVALAI_API_BASE_URL
    assert policy.user_api_base_url == AVALAI_USER_API_BASE_URL
    assert policy.selected_model_id in policy.allowed_model_ids
    assert policy.minimum_credit_floor_unit == Decimal("0.10")
    assert policy.max_exact_cost_unit == Decimal("0.01")
    assert len(policy.canonical_sha256) == 64


def test_staging_policy_rejects_unreviewed_url_and_model() -> None:
    with pytest.raises(ValidationError):
        LiveProviderStagingPolicy(api_base_url="https://example.invalid/v1")

    with pytest.raises(ValidationError, match="outside reviewed allowlist"):
        LiveProviderStagingPolicy(
            allowed_model_ids=("gpt-5.4-mini",),
            selected_model_id="unreviewed-model",
        )


def test_staging_policy_requires_unique_canonical_model_allowlist() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        LiveProviderStagingPolicy(
            allowed_model_ids=("gpt-5.4-mini", "gpt-5.4-mini"),
        )

    with pytest.raises(ValidationError, match="canonically sorted"):
        LiveProviderStagingPolicy(
            allowed_model_ids=("gpt-5.4-mini", "gpt-5.4"),
            selected_model_id="gpt-5.4-mini",
        )


def test_staging_policy_rejects_widened_call_token_and_polling_limits() -> None:
    with pytest.raises(ValidationError):
        LiveProviderStagingPolicy(max_model_calls=2)
    with pytest.raises(ValidationError):
        LiveProviderStagingPolicy(max_output_tokens=129)
    with pytest.raises(ValidationError, match="cannot exceed input-token"):
        LiveProviderStagingPolicy(max_input_tokens=8, max_output_tokens=16)
    with pytest.raises(ValidationError):
        LiveProviderStagingPolicy(transaction_poll_attempts=13)
    with pytest.raises(ValidationError, match="must fit elapsed-time"):
        LiveProviderStagingPolicy(
            max_elapsed_ms=10_000,
            transaction_poll_attempts=3,
            transaction_poll_interval_ms=5_000,
        )


def test_staging_request_requires_explicit_manual_approval() -> None:
    with pytest.raises(ValidationError):
        LiveProviderStagingRequest(
            staging_run_id=uuid4(),
            request_id=uuid4(),
            invocation_id=uuid4(),
            manual_approval=False,
        )
