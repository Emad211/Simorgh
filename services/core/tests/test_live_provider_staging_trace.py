from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.contracts import InvocationState, UsageVector
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    InvocationNotFoundError,
    InvocationRecord,
    canonical_fingerprint,
)
from simorgh_core.agents.live_provider_staging_contracts import (
    LiveProviderPreflight,
    LiveProviderReconciliationCode,
    LiveProviderStagingDisposition,
    LiveProviderStagingResult,
    live_provider_staging_result_id_for,
    live_provider_staging_result_sha256,
    live_provider_staging_terminal_event_id_for,
    live_provider_staging_trace_id_for,
)
from simorgh_core.agents.live_provider_staging_sqlite_store import (
    SQLiteLiveProviderStagingResultStore,
)
from simorgh_core.agents.live_provider_staging_store import (
    InMemoryLiveProviderStagingResultStore,
    LiveProviderStagingClaimKind,
)
from simorgh_core.agents.live_provider_staging_trace import (
    LiveProviderStagingTraceLinkError,
    LiveProviderStagingTraceProtection,
    TraceLinkedLiveProviderStagingResultStore,
    live_provider_staging_trace_evidence,
)
from simorgh_core.agents.sqlite_trace_store import SQLiteTraceStore
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceInvocationDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceTaskDetails,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore, TraceStore
from simorgh_core.providers.avalai_user_api import AvalAICreditSummary

_SHA_A = "a" * 64
_SHA_B = "b" * 64


class _InvocationStore:
    def __init__(self, record: InvocationRecord) -> None:
        self.record = record

    def get(self, invocation_id: UUID) -> InvocationRecord:
        if invocation_id != self.record.invocation_id:
            raise InvocationNotFoundError("invocation does not exist")
        return self.record

    def load(self) -> list[InvocationRecord]:
        return [self.record]


class _Protection:
    def __init__(self, protected: frozenset[UUID]) -> None:
        self._protected = protected

    def protected_request_ids(self) -> frozenset[UUID]:
        return self._protected


def _credit() -> AvalAICreditSummary:
    return AvalAICreditSummary(
        limit_irt=Decimal("0"),
        remaining_irt=Decimal("100000"),
        remaining_unit=Decimal("1"),
        total_unit=Decimal("1"),
        exchange_rate_irt_per_unit=100000,
        account_tier=1,
    )


def _invocation() -> InvocationRecord:
    invocation_id = uuid4()
    request_id = uuid4()
    payload = {
        "schema_version": "1.0",
        "invocation_id": str(invocation_id),
        "status": "completed",
    }
    return InvocationRecord(
        schema_version=2,
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="system.live-provider-staging",
        agent_version="1.0.0",
        operation="avalai-live-canary",
        input_fingerprint=_SHA_A,
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="avalai",
        model_id="gpt-5.4-mini",
        state=InvocationState.COMPLETED,
        attempt=1,
        created_at_ms=1_000,
        updated_at_ms=1_100,
        committed_usage=UsageVector(
            model_calls=1,
            input_tokens=8,
            output_tokens=2,
            estimated_cost_microusd=10,
        ),
        result_payload=payload,
        result_payload_sha256=canonical_fingerprint(payload),
    )


def _staging_result(invocation: InvocationRecord) -> LiveProviderStagingResult:
    staging_run_id = uuid4()
    provisional = LiveProviderStagingResult.model_construct(
        schema_version="1.0",
        staging_result_id=UUID(int=0),
        canonical_sha256="0" * 64,
        staging_run_id=staging_run_id,
        request_id=invocation.request_id,
        invocation_id=invocation.invocation_id,
        trace_id=live_provider_staging_trace_id_for(invocation.request_id),
        invocation_terminal_event_id=(
            live_provider_staging_terminal_event_id_for(
                request_id=invocation.request_id,
                invocation_id=invocation.invocation_id,
            )
        ),
        provider_id="avalai",
        model_id="gpt-5.4-mini",
        transaction_provider_id="openai",
        invocation_state=invocation.state,
        disposition=LiveProviderStagingDisposition.INCOMPLETE,
        replayed=False,
        committed_usage=invocation.committed_usage,
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
            checked_at_ms=900,
        ),
        provider_request_id=None,
        output_sha256=None,
        output_characters=None,
        transaction=None,
        reconciliation_codes=(
            LiveProviderReconciliationCode.TRANSACTION_PENDING,
        ),
        started_at_ms=900,
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


def _append_trace(
    store: TraceStore,
    invocation: InvocationRecord,
    *,
    terminal_source_sha256: str | None = None,
) -> None:
    task_claim = store.append(
        new_trace_event_candidate(
            request_id=invocation.request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=invocation.request_id,
            source_authority_sha256=_SHA_B,
            details=TraceTaskDetails(
                task_fingerprint=_SHA_B,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=800,
        ),
        ingested_at_ms=800,
    ).record
    start = store.append(
        new_trace_event_candidate(
            request_id=invocation.request_id,
            event_kind=DurableTraceEventKind.INVOCATION_STARTED,
            stage=TraceStage.MODEL,
            source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
            source_authority_id=invocation.invocation_id,
            source_authority_sha256=_SHA_A,
            parent_event_id=task_claim.event_id,
            causation_event_id=task_claim.event_id,
            invocation_id=invocation.invocation_id,
            details=TraceInvocationDetails(
                invocation_kind=InvocationKind.MODEL,
                effect=InvocationEffect.READ_ONLY,
                state=InvocationState.PENDING,
                operation_id="avalai-live-canary",
                input_fingerprint=invocation.input_fingerprint,
            ),
            occurred_at_ms=invocation.created_at_ms,
        ),
        ingested_at_ms=801,
    ).record
    store.append(
        new_trace_event_candidate(
            request_id=invocation.request_id,
            event_kind=DurableTraceEventKind.INVOCATION_TERMINAL,
            stage=TraceStage.MODEL,
            source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
            source_authority_id=invocation.invocation_id,
            source_authority_sha256=(
                terminal_source_sha256 or canonical_fingerprint(invocation)
            ),
            parent_event_id=start.event_id,
            causation_event_id=start.event_id,
            invocation_id=invocation.invocation_id,
            usage=invocation.committed_usage,
            details=TraceInvocationDetails(
                invocation_kind=InvocationKind.MODEL,
                effect=InvocationEffect.READ_ONLY,
                state=invocation.state,
                operation_id="avalai-live-canary",
                input_fingerprint=invocation.input_fingerprint,
                result_payload_sha256=invocation.result_payload_sha256,
            ),
            occurred_at_ms=invocation.updated_at_ms,
        ),
        ingested_at_ms=802,
    )


def test_trace_link_is_deterministic_and_validated_on_claim_and_replay() -> None:
    invocation = _invocation()
    result = _staging_result(invocation)
    trace_store = InMemoryTraceStore()
    _append_trace(trace_store, invocation)
    linked = TraceLinkedLiveProviderStagingResultStore(
        store=InMemoryLiveProviderStagingResultStore(),
        invocation_store=_InvocationStore(invocation),  # type: ignore[arg-type]
        trace_store=trace_store,
    )

    created = linked.claim(result)
    replay = linked.claim(result.model_copy(update={"replayed": True}))
    evidence = live_provider_staging_trace_evidence(
        result,
        invocation_store=_InvocationStore(invocation),  # type: ignore[arg-type]
        trace_store=trace_store,
    )

    assert created.kind == LiveProviderStagingClaimKind.NEW
    assert replay.kind == LiveProviderStagingClaimKind.REPLAY
    assert evidence.trace_id == result.trace_id
    assert evidence.terminal_event_id == result.invocation_terminal_event_id
    assert evidence.terminal_source_sha256 == canonical_fingerprint(invocation)
    assert evidence.invocation_state == invocation.state


def test_trace_link_rejects_missing_mismatched_and_tampered_evidence() -> None:
    invocation = _invocation()
    result = _staging_result(invocation)
    invocation_store = _InvocationStore(invocation)

    missing = TraceLinkedLiveProviderStagingResultStore(
        store=InMemoryLiveProviderStagingResultStore(),
        invocation_store=invocation_store,  # type: ignore[arg-type]
        trace_store=InMemoryTraceStore(),
    )
    with pytest.raises(LiveProviderStagingTraceLinkError, match="unavailable"):
        missing.claim(result)
    assert missing.underlying_store.load() == []

    mismatched_trace = InMemoryTraceStore()
    _append_trace(mismatched_trace, invocation, terminal_source_sha256="c" * 64)
    mismatched = TraceLinkedLiveProviderStagingResultStore(
        store=InMemoryLiveProviderStagingResultStore(),
        invocation_store=invocation_store,  # type: ignore[arg-type]
        trace_store=mismatched_trace,
    )
    with pytest.raises(LiveProviderStagingTraceLinkError, match="conflicts"):
        mismatched.claim(result)

    valid_trace = InMemoryTraceStore()
    _append_trace(valid_trace, invocation)
    tampered = TraceLinkedLiveProviderStagingResultStore(
        store=InMemoryLiveProviderStagingResultStore(),
        invocation_store=invocation_store,  # type: ignore[arg-type]
        trace_store=valid_trace,
    )
    changed = result.model_copy(update={"invocation_terminal_event_id": uuid4()})
    with pytest.raises(LiveProviderStagingTraceLinkError, match="invalid"):
        tampered.claim(changed)


def test_sqlite_restart_preserves_trace_link_validation(tmp_path: Path) -> None:
    invocation = _invocation()
    result = _staging_result(invocation)
    trace_path = tmp_path / "traces.sqlite3"
    staging_path = tmp_path / "staging.sqlite3"

    trace_store = SQLiteTraceStore(trace_path)
    _append_trace(trace_store, invocation)
    linked = TraceLinkedLiveProviderStagingResultStore(
        store=SQLiteLiveProviderStagingResultStore(staging_path),
        invocation_store=_InvocationStore(invocation),  # type: ignore[arg-type]
        trace_store=trace_store,
    )
    linked.claim(result)
    linked.close()
    trace_store.close()

    reopened_trace = SQLiteTraceStore(trace_path)
    reopened = TraceLinkedLiveProviderStagingResultStore(
        store=SQLiteLiveProviderStagingResultStore(staging_path),
        invocation_store=_InvocationStore(invocation),  # type: ignore[arg-type]
        trace_store=reopened_trace,
    )
    assert reopened.load() == [result]
    reopened.close()
    reopened_trace.close()


def test_staging_results_extend_trace_retention_protection() -> None:
    invocation = _invocation()
    result = _staging_result(invocation)
    staging_store = InMemoryLiveProviderStagingResultStore()
    staging_store.claim(result)
    unrelated = uuid4()
    protection = LiveProviderStagingTraceProtection(
        base=_Protection(frozenset({unrelated})),
        result_store=staging_store,
    )

    assert protection.protected_request_ids() == frozenset(
        {unrelated, invocation.request_id}
    )
