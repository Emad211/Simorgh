from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.contracts import InvocationState, UsageVector
from simorgh_core.agents.live_provider_staging import _reconcile_transaction
from simorgh_core.agents.live_provider_staging_contracts import (
    LiveProviderModelPricing,
    LiveProviderPreflight,
    LiveProviderReconciliationCode,
    LiveProviderReconciliationDisposition,
    LiveProviderStagingDisposition,
    LiveProviderStagingPolicy,
    LiveProviderStagingResult,
    live_provider_reconciliation_disposition_for,
    live_provider_staging_result_id_for,
    live_provider_staging_result_sha256,
    live_provider_staging_terminal_event_id_for,
    live_provider_staging_trace_id_for,
)
from simorgh_core.agents.live_provider_staging_sqlite_store import (
    LiveProviderStagingStoreCorruptionError,
    SQLiteLiveProviderStagingResultStore,
)
from simorgh_core.agents.live_provider_staging_store import (
    LiveProviderStagingClaimKind,
)
from simorgh_core.agents.model_gateway import BudgetedModelResult
from simorgh_core.providers.avalai_user_api import (
    AvalAICostSource,
    AvalAICreditSummary,
    AvalAIExactCost,
    AvalAITokenUsage,
    AvalAITransactionSummary,
)

_TRANSACTION_A = UUID("019ac4a0-a8f4-7041-845f-3ea8f15dcf1a")
_TRANSACTION_B = UUID("019ac4a0-a8f4-7041-845f-3ea8f15dcf1b")
_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _credit() -> AvalAICreditSummary:
    return AvalAICreditSummary(
        limit_irt=Decimal("0"),
        remaining_irt=Decimal("100000"),
        remaining_unit=Decimal("1"),
        total_unit=Decimal("1"),
        exchange_rate_irt_per_unit=100000,
        account_tier=1,
    )


def _transaction(
    *,
    transaction_id: UUID = _TRANSACTION_A,
    model: str = "gpt-5.4-mini",
    provider: str = "openai",
    prompt_tokens: int = 8,
    completion_tokens: int = 2,
    exact_unit: str = "0.001",
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


def _preflight() -> LiveProviderPreflight:
    return LiveProviderPreflight(
        model_id="gpt-5.4-mini",
        transaction_provider_id="openai",
        policy_sha256=_SHA_A,
        pricing_sha256=_SHA_B,
        estimated_input_tokens=20,
        maximum_output_tokens=16,
        worst_case_estimated_cost_microusd=36,
        required_credit_unit=Decimal("0.11"),
        credit_before=_credit(),
        checked_at_ms=1_000,
    )


def _result(
    *,
    transaction: AvalAITransactionSummary | None = None,
    provider_request_id: UUID | None = None,
    codes: tuple[LiveProviderReconciliationCode, ...] = (
        LiveProviderReconciliationCode.TRANSACTION_PENDING,
    ),
    staging_run_id: UUID | None = None,
    request_id: UUID | None = None,
    invocation_id: UUID | None = None,
) -> LiveProviderStagingResult:
    staging_run_id = staging_run_id or uuid4()
    request_id = request_id or uuid4()
    invocation_id = invocation_id or uuid4()
    provisional = LiveProviderStagingResult.model_construct(
        schema_version="1.0",
        staging_result_id=UUID(int=0),
        canonical_sha256="0" * 64,
        staging_run_id=staging_run_id,
        request_id=request_id,
        invocation_id=invocation_id,
        trace_id=live_provider_staging_trace_id_for(request_id),
        invocation_terminal_event_id=(
            live_provider_staging_terminal_event_id_for(
                request_id=request_id,
                invocation_id=invocation_id,
            )
        ),
        provider_id="avalai",
        model_id="gpt-5.4-mini",
        transaction_provider_id="openai",
        invocation_state=InvocationState.COMPLETED,
        disposition=LiveProviderStagingDisposition.INCOMPLETE,
        replayed=False,
        committed_usage=UsageVector(
            model_calls=1,
            input_tokens=8,
            output_tokens=2,
            estimated_cost_microusd=10,
        ),
        preflight=_preflight(),
        provider_request_id=provider_request_id,
        output_sha256=_SHA_A,
        output_characters=17,
        transaction=transaction,
        reconciliation_codes=codes,
        started_at_ms=1_100,
        completed_at_ms=1_200,
    )
    canonical_sha256 = live_provider_staging_result_sha256(provisional)
    return LiveProviderStagingResult.model_validate(
        {
            **provisional.model_dump(mode="json"),
            "staging_result_id": live_provider_staging_result_id_for(
                staging_run_id=staging_run_id,
                canonical_sha256=canonical_sha256,
            ),
            "canonical_sha256": canonical_sha256,
        }
    )


@pytest.mark.parametrize(
    ("transaction_present", "codes", "expected"),
    (
        (True, (), LiveProviderReconciliationDisposition.EXACT),
        (
            False,
            (LiveProviderReconciliationCode.TRANSACTION_PENDING,),
            LiveProviderReconciliationDisposition.PENDING,
        ),
        (
            False,
            (LiveProviderReconciliationCode.TRANSACTION_LOOKUP_UNAVAILABLE,),
            LiveProviderReconciliationDisposition.UNAVAILABLE,
        ),
        (
            False,
            (LiveProviderReconciliationCode.PROVIDER_INVOCATION_UNKNOWN,),
            LiveProviderReconciliationDisposition.UNAVAILABLE,
        ),
        (
            True,
            (LiveProviderReconciliationCode.TRANSACTION_MODEL_MISMATCH,),
            LiveProviderReconciliationDisposition.MISMATCH,
        ),
        (
            False,
            (
                LiveProviderReconciliationCode.OUTPUT_CONTRACT_INVALID,
                LiveProviderReconciliationCode.PROVIDER_REQUEST_ID_MISSING,
            ),
            LiveProviderReconciliationDisposition.MISMATCH,
        ),
    ),
)
def test_reconciliation_disposition_is_deterministic(
    transaction_present: bool,
    codes: tuple[LiveProviderReconciliationCode, ...],
    expected: LiveProviderReconciliationDisposition,
) -> None:
    assert live_provider_reconciliation_disposition_for(
        transaction_present=transaction_present,
        codes=codes,
    ) == expected


def test_reconciliation_disposition_rejects_missing_or_mixed_evidence() -> None:
    with pytest.raises(ValueError, match="requires transaction evidence"):
        live_provider_reconciliation_disposition_for(
            transaction_present=False,
            codes=(),
        )
    with pytest.raises(ValueError, match="pending evidence conflicts"):
        live_provider_reconciliation_disposition_for(
            transaction_present=False,
            codes=(
                LiveProviderReconciliationCode.TRANSACTION_PENDING,
                LiveProviderReconciliationCode.TRANSACTION_LOOKUP_UNAVAILABLE,
            ),
        )
    with pytest.raises(ValueError, match="exact transaction conflicts"):
        live_provider_reconciliation_disposition_for(
            transaction_present=True,
            codes=(LiveProviderReconciliationCode.TRANSACTION_LOOKUP_UNAVAILABLE,),
        )


def test_result_derives_canonical_disposition_and_rejects_changed_projection() -> None:
    result = _result()
    assert result.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.PENDING
    )

    payload = result.model_dump(mode="json")
    payload["reconciliation_disposition"] = (
        LiveProviderReconciliationDisposition.EXACT.value
    )
    changed_hash = live_provider_staging_result_sha256(payload)
    payload["canonical_sha256"] = changed_hash
    payload["staging_result_id"] = str(
        live_provider_staging_result_id_for(
            staging_run_id=result.staging_run_id,
            canonical_sha256=changed_hash,
        )
    )
    with pytest.raises(ValidationError, match="does not match evidence"):
        LiveProviderStagingResult.model_validate(payload)


def test_request_identity_mismatch_is_typed_and_canonical() -> None:
    mismatch = _result(
        provider_request_id=_TRANSACTION_A,
        transaction=_transaction(transaction_id=_TRANSACTION_B),
        codes=(LiveProviderReconciliationCode.TRANSACTION_REQUEST_MISMATCH,),
    )
    assert mismatch.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.MISMATCH
    )

    payload = mismatch.model_dump(mode="json")
    payload["reconciliation_codes"] = []
    payload["disposition"] = LiveProviderStagingDisposition.COMPLETED.value
    payload.pop("reconciliation_disposition")
    changed_hash = live_provider_staging_result_sha256(payload)
    payload["canonical_sha256"] = changed_hash
    payload["staging_result_id"] = str(
        live_provider_staging_result_id_for(
            staging_run_id=mismatch.staging_run_id,
            canonical_sha256=changed_hash,
        )
    )
    with pytest.raises(ValidationError, match="request identity"):
        LiveProviderStagingResult.model_validate(payload)


def test_transaction_reconciliation_types_request_model_provider_usage_and_cost() -> None:
    codes: set[LiveProviderReconciliationCode] = set()
    _reconcile_transaction(
        transaction=_transaction(
            transaction_id=_TRANSACTION_B,
            model="other-model",
            provider="other-provider",
            prompt_tokens=9,
            completion_tokens=3,
            exact_unit="0.02",
        ),
        provider_request_id=_TRANSACTION_A,
        gateway_result=BudgetedModelResult(
            invocation_id=uuid4(),
            text="SIMORGH_CANARY_OK",
            provider_id="avalai",
            model_id="gpt-5.4-mini",
            provider_request_id=str(_TRANSACTION_A),
            input_tokens=8,
            output_tokens=2,
            cost_microusd=10,
        ),
        pricing=LiveProviderModelPricing(
            model_id="gpt-5.4-mini",
            transaction_provider_id="openai",
            input_price_microusd_per_million_tokens=1_000_000,
            output_price_microusd_per_million_tokens=1_000_000,
            maximum_output_tokens=16,
        ),
        policy=LiveProviderStagingPolicy(
            enabled=True,
            max_exact_cost_unit=Decimal("0.01"),
        ),
        codes=codes,
    )
    assert codes == {
        LiveProviderReconciliationCode.TRANSACTION_REQUEST_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_MODEL_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_PROVIDER_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_USAGE_MISMATCH,
        LiveProviderReconciliationCode.TRANSACTION_COST_EXCEEDED,
    }


def test_sqlite_restart_replay_preserves_canonical_disposition(tmp_path: Path) -> None:
    path = tmp_path / "staging.sqlite3"
    result = _result()
    store = SQLiteLiveProviderStagingResultStore(path)
    assert store.claim(result).kind == LiveProviderStagingClaimKind.NEW
    store.close()

    reopened = SQLiteLiveProviderStagingResultStore(path)
    replay = reopened.claim(result.model_copy(update={"replayed": True}))
    assert replay.kind == LiveProviderStagingClaimKind.REPLAY
    assert replay.record.reconciliation_disposition == (
        LiveProviderReconciliationDisposition.PENDING
    )
    assert replay.record.canonical_sha256 == result.canonical_sha256
    reopened.close()


def test_sqlite_rejects_rehashed_disposition_corruption(tmp_path: Path) -> None:
    path = tmp_path / "staging.sqlite3"
    result = _result()
    store = SQLiteLiveProviderStagingResultStore(path)
    store.claim(result)
    store.close()

    connection = sqlite3.connect(path)
    payload_json = connection.execute(
        "SELECT payload_json FROM live_provider_staging_results"
    ).fetchone()[0]
    payload = json.loads(payload_json)
    payload["reconciliation_disposition"] = (
        LiveProviderReconciliationDisposition.EXACT.value
    )
    changed_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    connection.execute(
        """
        UPDATE live_provider_staging_results
        SET payload_json = ?, payload_sha256 = ?
        """,
        (
            changed_json,
            hashlib.sha256(changed_json.encode("utf-8")).hexdigest(),
        ),
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        LiveProviderStagingStoreCorruptionError,
        match="payload contract is invalid",
    ):
        SQLiteLiveProviderStagingResultStore(path)
