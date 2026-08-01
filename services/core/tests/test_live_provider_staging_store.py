from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.contracts import InvocationState, UsageVector
from simorgh_core.agents.live_provider_staging_contracts import (
    LiveProviderPreflight,
    LiveProviderReconciliationCode,
    LiveProviderStagingDisposition,
    LiveProviderStagingResult,
    live_provider_staging_result_id_for,
    live_provider_staging_result_sha256,
)
from simorgh_core.agents.live_provider_staging_sqlite_store import (
    LiveProviderStagingStoreCorruptionError,
    LiveProviderStagingStoreInUseError,
    LiveProviderStagingStoreSchemaError,
    SQLiteLiveProviderStagingResultStore,
)
from simorgh_core.agents.live_provider_staging_store import (
    InMemoryLiveProviderStagingResultStore,
    LiveProviderStagingClaimKind,
    LiveProviderStagingStoreClosedError,
    LiveProviderStagingStoreConflictError,
    LiveProviderStagingStoreNotFoundError,
)
from simorgh_core.providers.avalai_user_api import AvalAICreditSummary

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


def _result(
    *,
    staging_run_id: UUID | None = None,
    request_id: UUID | None = None,
    invocation_id: UUID | None = None,
    completed_at_ms: int = 2_000,
    code: LiveProviderReconciliationCode = (
        LiveProviderReconciliationCode.TRANSACTION_PENDING
    ),
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
        preflight=LiveProviderPreflight(
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
        ),
        provider_request_id=None,
        output_sha256=None,
        output_characters=None,
        transaction=None,
        reconciliation_codes=(code,),
        started_at_ms=1_100,
        completed_at_ms=completed_at_ms,
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


def test_in_memory_store_enforces_one_result_per_invocation_and_close() -> None:
    invocation_id = uuid4()
    first = _result(invocation_id=invocation_id)
    store = InMemoryLiveProviderStagingResultStore()

    created = store.claim(first)
    replay = store.claim(first.model_copy(update={"replayed": True}))

    assert created.kind == LiveProviderStagingClaimKind.NEW
    assert replay.kind == LiveProviderStagingClaimKind.REPLAY
    assert replay.record.replayed is False
    assert store.get(first.staging_run_id) == first
    assert store.get_by_invocation(invocation_id) == first
    assert store.load() == [first]

    changed = _result(invocation_id=invocation_id)
    with pytest.raises(LiveProviderStagingStoreConflictError):
        store.claim(changed)

    store.close()
    with pytest.raises(LiveProviderStagingStoreClosedError):
        store.load()


def test_sqlite_round_trip_restart_and_exact_replay(tmp_path: Path) -> None:
    path = tmp_path / "staging.sqlite3"
    first = _result()
    store = SQLiteLiveProviderStagingResultStore(path)

    created = store.claim(first)
    assert created.kind == LiveProviderStagingClaimKind.NEW
    assert store.get(first.staging_run_id) == first
    assert store.get_by_invocation(first.invocation_id) == first
    store.close()

    reopened = SQLiteLiveProviderStagingResultStore(path)
    replay = reopened.claim(first.model_copy(update={"replayed": True}))
    assert replay.kind == LiveProviderStagingClaimKind.REPLAY
    assert replay.record == first
    assert reopened.load() == [first]
    reopened.close()


def test_sqlite_changed_identity_conflicts_without_mutating_store(tmp_path: Path) -> None:
    path = tmp_path / "staging.sqlite3"
    invocation_id = uuid4()
    first = _result(invocation_id=invocation_id)
    store = SQLiteLiveProviderStagingResultStore(path)
    store.claim(first)

    with pytest.raises(LiveProviderStagingStoreConflictError):
        store.claim(_result(invocation_id=invocation_id))

    assert store.load() == [first]
    store.close()


def test_sqlite_process_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "staging.sqlite3"
    first = SQLiteLiveProviderStagingResultStore(path)

    with pytest.raises(LiveProviderStagingStoreInUseError):
        SQLiteLiveProviderStagingResultStore(path)

    first.close()
    reopened = SQLiteLiveProviderStagingResultStore(path)
    reopened.close()


def test_sqlite_payload_and_index_corruption_fail_closed(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.sqlite3"
    record = _result()
    store = SQLiteLiveProviderStagingResultStore(payload_path)
    store.claim(record)
    store.close()

    connection = sqlite3.connect(payload_path)
    connection.execute(
        "UPDATE live_provider_staging_results SET payload_json = '{}'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        LiveProviderStagingStoreCorruptionError,
        match="payload hash mismatch",
    ):
        SQLiteLiveProviderStagingResultStore(payload_path)

    index_path = tmp_path / "index.sqlite3"
    store = SQLiteLiveProviderStagingResultStore(index_path)
    store.claim(record)
    store.close()
    connection = sqlite3.connect(index_path)
    connection.execute(
        "UPDATE live_provider_staging_results SET model_id = 'different-model'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        LiveProviderStagingStoreCorruptionError,
        match="indexed columns do not match",
    ):
        SQLiteLiveProviderStagingResultStore(index_path)


def test_sqlite_unsupported_schema_and_not_found_are_typed(tmp_path: Path) -> None:
    path = tmp_path / "staging.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE live_provider_staging_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    connection.execute(
        """
        INSERT INTO live_provider_staging_metadata(key, value)
        VALUES('schema_version', '999')
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        LiveProviderStagingStoreSchemaError,
        match="unsupported staging result store schema",
    ):
        SQLiteLiveProviderStagingResultStore(path)

    memory = InMemoryLiveProviderStagingResultStore()
    with pytest.raises(LiveProviderStagingStoreNotFoundError):
        memory.get(uuid4())
