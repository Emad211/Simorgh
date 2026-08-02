from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one anchor in {path}, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def append_once(path: str, marker: str, content: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        raise RuntimeError(f"marker already exists in {path}")
    target.write_text(text.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "from simorgh_core.agents.invocations import canonical_fingerprint\n",
    "from simorgh_core.agents.invocations import canonical_fingerprint\n"
    "from simorgh_core.agents.trace_contracts import (\n"
    "    DurableTraceEventKind,\n"
    "    DurableTraceReplayDisposition,\n"
    "    TraceSourceAuthorityKind,\n"
    "    trace_event_id_for,\n"
    "    trace_id_for,\n"
    ")\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "    invocation_id: UUID\n    provider_id: Literal[\"avalai\"] = AVALAI_PROVIDER_ID\n",
    "    invocation_id: UUID\n"
    "    trace_id: UUID\n"
    "    invocation_terminal_event_id: UUID\n"
    "    provider_id: Literal[\"avalai\"] = AVALAI_PROVIDER_ID\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "    def validate_result(self) -> Self:\n"
    "        if self.completed_at_ms < self.started_at_ms:\n",
    "    def validate_result(self) -> Self:\n"
    "        if self.trace_id != live_provider_staging_trace_id_for(self.request_id):\n"
    "            raise ValueError(\"staging trace ID does not match request identity\")\n"
    "        expected_terminal_event_id = (\n"
    "            live_provider_staging_terminal_event_id_for(\n"
    "                request_id=self.request_id,\n"
    "                invocation_id=self.invocation_id,\n"
    "            )\n"
    "        )\n"
    "        if self.invocation_terminal_event_id != expected_terminal_event_id:\n"
    "            raise ValueError(\n"
    "                \"staging terminal event ID does not match invocation identity\"\n"
    "            )\n"
    "        if self.completed_at_ms < self.started_at_ms:\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "\ndef live_provider_staging_result_payload(\n",
    "\ndef live_provider_staging_trace_id_for(request_id: UUID) -> UUID:\n"
    "    return trace_id_for(request_id)\n\n\n"
    "def live_provider_staging_terminal_event_id_for(\n"
    "    *,\n"
    "    request_id: UUID,\n"
    "    invocation_id: UUID,\n"
    ") -> UUID:\n"
    "    return trace_event_id_for(\n"
    "        trace_id=live_provider_staging_trace_id_for(request_id),\n"
    "        source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,\n"
    "        source_authority_id=invocation_id,\n"
    "        event_kind=DurableTraceEventKind.INVOCATION_TERMINAL,\n"
    "        replay=DurableTraceReplayDisposition.FRESH,\n"
    "    )\n\n\n"
    "def live_provider_staging_result_payload(\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "        \"replayed\",\n        \"started_at_ms\",\n",
    "        \"replayed\",\n"
    "        \"trace_id\",\n"
    "        \"invocation_terminal_event_id\",\n"
    "        \"started_at_ms\",\n",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "    \"live_provider_staging_result_sha256\",\n]",
    "    \"live_provider_staging_result_sha256\",\n"
    "    \"live_provider_staging_terminal_event_id_for\",\n"
    "    \"live_provider_staging_trace_id_for\",\n"
    "]",
)

replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging.py",
    "    live_provider_staging_result_sha256,\n)",
    "    live_provider_staging_result_sha256,\n"
    "    live_provider_staging_terminal_event_id_for,\n"
    "    live_provider_staging_trace_id_for,\n"
    ")",
)
replace_once(
    "services/core/src/simorgh_core/agents/live_provider_staging.py",
    "        invocation_id=request.invocation_id,\n        provider_id=policy.provider_id,\n",
    "        invocation_id=request.invocation_id,\n"
    "        trace_id=live_provider_staging_trace_id_for(request.request_id),\n"
    "        invocation_terminal_event_id=(\n"
    "            live_provider_staging_terminal_event_id_for(\n"
    "                request_id=request.request_id,\n"
    "                invocation_id=request.invocation_id,\n"
    "            )\n"
    "        ),\n"
    "        provider_id=policy.provider_id,\n",
)

replace_once(
    "services/core/tests/test_live_provider_staging_store.py",
    "    live_provider_staging_result_sha256,\n)",
    "    live_provider_staging_result_sha256,\n"
    "    live_provider_staging_terminal_event_id_for,\n"
    "    live_provider_staging_trace_id_for,\n"
    ")",
)
replace_once(
    "services/core/tests/test_live_provider_staging_store.py",
    "        invocation_id=invocation_id,\n        provider_id=\"avalai\",\n",
    "        invocation_id=invocation_id,\n"
    "        trace_id=live_provider_staging_trace_id_for(request_id),\n"
    "        invocation_terminal_event_id=(\n"
    "            live_provider_staging_terminal_event_id_for(\n"
    "                request_id=request_id,\n"
    "                invocation_id=invocation_id,\n"
    "            )\n"
    "        ),\n"
    "        provider_id=\"avalai\",\n",
)

trace_module = '''from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.contracts import InvocationState
from simorgh_core.agents.invocations import (
    InvocationKind,
    InvocationNotFoundError,
    InvocationStore,
    InvocationStoreError,
    canonical_fingerprint,
)
from simorgh_core.agents.live_provider_staging_contracts import (
    LiveProviderStagingResult,
    live_provider_staging_terminal_event_id_for,
    live_provider_staging_trace_id_for,
)
from simorgh_core.agents.live_provider_staging_store import (
    LiveProviderStagingClaim,
    LiveProviderStagingResultStore,
)
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    DurableTraceReplayDisposition,
    TraceInvocationDetails,
    TraceSourceAuthorityKind,
    TraceStage,
)
from simorgh_core.agents.trace_retention import TraceProtectionAuthority
from simorgh_core.agents.trace_store import TraceNotFoundError, TraceStore, TraceStoreError

_TERMINAL_INVOCATION_STATES = frozenset(
    {
        InvocationState.COMPLETED,
        InvocationState.FAILED,
        InvocationState.CANCELLED,
        InvocationState.EXPIRED,
        InvocationState.UNKNOWN,
        InvocationState.UNKNOWN_SIDE_EFFECT,
    }
)
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"


class LiveProviderStagingTraceLinkError(RuntimeError):
    """A staging result could not be linked to immutable native Trace evidence."""


class LiveProviderStagingTraceEvidence(BaseModel):
    """Validated read projection over one immutable invocation-terminal event."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = "1.0"
    trace_id: UUID
    request_id: UUID
    invocation_id: UUID
    terminal_event_id: UUID
    terminal_event_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    terminal_source_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    terminal_sequence: int = Field(ge=1)
    invocation_state: InvocationState

    @model_validator(mode="after")
    def validate_identity(self) -> "LiveProviderStagingTraceEvidence":
        if self.trace_id != live_provider_staging_trace_id_for(self.request_id):
            raise ValueError("staging trace evidence request identity is invalid")
        if self.terminal_event_id != live_provider_staging_terminal_event_id_for(
            request_id=self.request_id,
            invocation_id=self.invocation_id,
        ):
            raise ValueError("staging trace evidence terminal identity is invalid")
        if self.invocation_state not in _TERMINAL_INVOCATION_STATES:
            raise ValueError("staging trace evidence requires terminal invocation state")
        return self


def live_provider_staging_trace_evidence(
    record: LiveProviderStagingResult,
    *,
    invocation_store: InvocationStore,
    trace_store: TraceStore,
) -> LiveProviderStagingTraceEvidence:
    """Resolve and validate native immutable evidence without creating authority."""

    expected_trace_id = live_provider_staging_trace_id_for(record.request_id)
    expected_event_id = live_provider_staging_terminal_event_id_for(
        request_id=record.request_id,
        invocation_id=record.invocation_id,
    )
    if record.trace_id != expected_trace_id:
        raise LiveProviderStagingTraceLinkError(
            "staging result carries an invalid trace identity"
        )
    if record.invocation_terminal_event_id != expected_event_id:
        raise LiveProviderStagingTraceLinkError(
            "staging result carries an invalid terminal event identity"
        )

    try:
        invocation = invocation_store.get(record.invocation_id)
    except (InvocationNotFoundError, InvocationStoreError):
        raise LiveProviderStagingTraceLinkError(
            "staging invocation authority is unavailable for trace linkage"
        ) from None
    if (
        invocation.request_id != record.request_id
        or invocation.kind != InvocationKind.MODEL
        or not invocation.terminal
        or invocation.state != record.invocation_state
        or invocation.committed_usage != record.committed_usage
    ):
        raise LiveProviderStagingTraceLinkError(
            "staging result conflicts with invocation authority"
        )

    try:
        event = trace_store.get_event(expected_event_id)
    except (TraceNotFoundError, TraceStoreError):
        raise LiveProviderStagingTraceLinkError(
            "staging invocation terminal Trace evidence is unavailable"
        ) from None

    details = event.details
    expected_source_sha256 = canonical_fingerprint(invocation)
    if (
        event.trace_id != expected_trace_id
        or event.request_id != record.request_id
        or event.event_id != expected_event_id
        or event.event_kind != DurableTraceEventKind.INVOCATION_TERMINAL
        or event.stage != TraceStage.MODEL
        or event.source_authority_kind
        != TraceSourceAuthorityKind.INVOCATION_RECORD
        or event.source_authority_id != record.invocation_id
        or event.source_authority_sha256 != expected_source_sha256
        or event.replay != DurableTraceReplayDisposition.FRESH
        or event.invocation_id != record.invocation_id
        or event.usage != invocation.committed_usage
        or not isinstance(details, TraceInvocationDetails)
        or details.invocation_kind != InvocationKind.MODEL
        or details.state != invocation.state
        or details.result_payload_sha256 != invocation.result_payload_sha256
    ):
        raise LiveProviderStagingTraceLinkError(
            "staging result conflicts with immutable terminal Trace evidence"
        )

    return LiveProviderStagingTraceEvidence(
        trace_id=event.trace_id,
        request_id=event.request_id,
        invocation_id=record.invocation_id,
        terminal_event_id=event.event_id,
        terminal_event_sha256=event.canonical_sha256,
        terminal_source_sha256=event.source_authority_sha256,
        terminal_sequence=event.sequence,
        invocation_state=invocation.state,
    )


class TraceLinkedLiveProviderStagingResultStore:
    """Require native Invocation and Trace evidence on every staging read/write."""

    def __init__(
        self,
        *,
        store: LiveProviderStagingResultStore,
        invocation_store: InvocationStore,
        trace_store: TraceStore,
    ) -> None:
        self._store = store
        self._invocation_store = invocation_store
        self._trace_store = trace_store

    @property
    def underlying_store(self) -> LiveProviderStagingResultStore:
        return self._store

    def claim(self, record: LiveProviderStagingResult) -> LiveProviderStagingClaim:
        self._validate(record)
        claim = self._store.claim(record)
        self._validate(claim.record)
        return claim

    def get(self, staging_run_id: UUID) -> LiveProviderStagingResult:
        record = self._store.get(staging_run_id)
        self._validate(record)
        return record

    def get_by_invocation(self, invocation_id: UUID) -> LiveProviderStagingResult:
        record = self._store.get_by_invocation(invocation_id)
        self._validate(record)
        return record

    def load(self) -> list[LiveProviderStagingResult]:
        records = self._store.load()
        for record in records:
            self._validate(record)
        return records

    def close(self) -> None:
        self._store.close()

    def _validate(self, record: LiveProviderStagingResult) -> None:
        live_provider_staging_trace_evidence(
            record,
            invocation_store=self._invocation_store,
            trace_store=self._trace_store,
        )


class LiveProviderStagingTraceProtection:
    """Protect every trace referenced by durable staging-result authority."""

    def __init__(
        self,
        *,
        base: TraceProtectionAuthority,
        result_store: LiveProviderStagingResultStore,
    ) -> None:
        self._base = base
        self._result_store = result_store

    def protected_request_ids(self) -> frozenset[UUID]:
        staging_request_ids = {
            record.request_id for record in self._result_store.load()
        }
        return self._base.protected_request_ids().union(staging_request_ids)


__all__ = [
    "LiveProviderStagingTraceEvidence",
    "LiveProviderStagingTraceLinkError",
    "LiveProviderStagingTraceProtection",
    "TraceLinkedLiveProviderStagingResultStore",
    "live_provider_staging_trace_evidence",
]
'''
(ROOT / "services/core/src/simorgh_core/agents/live_provider_staging_trace.py").write_text(
    trace_module,
    encoding="utf-8",
)

replace_once(
    "services/core/src/simorgh_core/app.py",
    "from simorgh_core.agents.live_provider_staging_sqlite_store import (\n",
    "from simorgh_core.agents.live_provider_staging_trace import (\n"
    "    LiveProviderStagingTraceProtection,\n"
    "    TraceLinkedLiveProviderStagingResultStore,\n"
    ")\n"
    "from simorgh_core.agents.live_provider_staging_sqlite_store import (\n",
)
replace_once(
    "services/core/src/simorgh_core/app.py",
    "    staging_result_store: LiveProviderStagingResultStore | None = None\n"
    "    raw_trace_store: SQLiteTraceStore | None = None\n",
    "    raw_staging_result_store: LiveProviderStagingResultStore | None = None\n"
    "    staging_result_store: LiveProviderStagingResultStore | None = None\n"
    "    raw_trace_store: SQLiteTraceStore | None = None\n",
)
replace_once(
    "services/core/src/simorgh_core/app.py",
    "        staging_result_store = SQLiteLiveProviderStagingResultStore(\n"
    "            settings.simorgh_live_provider_staging_result_store_path,\n"
    "        )\n",
    "        raw_staging_result_store = SQLiteLiveProviderStagingResultStore(\n"
    "            settings.simorgh_live_provider_staging_result_store_path,\n"
    "        )\n",
)
replace_once(
    "services/core/src/simorgh_core/app.py",
    "            protection=StoreBackedTraceProtection(\n"
    "                task_store=task_store,\n"
    "                invocation_store=invocation_store,\n"
    "            ),\n",
    "            protection=LiveProviderStagingTraceProtection(\n"
    "                base=StoreBackedTraceProtection(\n"
    "                    task_store=task_store,\n"
    "                    invocation_store=invocation_store,\n"
    "                ),\n"
    "                result_store=raw_staging_result_store,\n"
    "            ),\n",
)
replace_once(
    "services/core/src/simorgh_core/app.py",
    "        raw_trace_store = None\n"
    "        trace_store.prune_terminal()\n"
    "        await action_broker.configure_journal(\n",
    "        raw_trace_store = None\n"
    "        trace_store.prune_terminal()\n"
    "        staging_result_store = TraceLinkedLiveProviderStagingResultStore(\n"
    "            store=raw_staging_result_store,\n"
    "            invocation_store=invocation_store,\n"
    "            trace_store=trace_store,\n"
    "        )\n"
    "        raw_staging_result_store = None\n"
    "        await action_broker.configure_journal(\n",
)
replace_once(
    "services/core/src/simorgh_core/app.py",
    "        elif staging_result_store is not None:\n"
    "            staging_result_store.close()\n"
    "        if trace_store_configured:\n",
    "        elif staging_result_store is not None:\n"
    "            staging_result_store.close()\n"
    "        elif raw_staging_result_store is not None:\n"
    "            raw_staging_result_store.close()\n"
    "        if trace_store_configured:\n",
)

replace_once(
    "services/core/tests/test_live_provider_staging_lifespan.py",
    "from simorgh_core.agents.live_provider_staging_sqlite_store import (\n",
    "from simorgh_core.agents.live_provider_staging_trace import (\n"
    "    TraceLinkedLiveProviderStagingResultStore,\n"
    ")\n"
    "from simorgh_core.agents.live_provider_staging_sqlite_store import (\n",
)
replace_once(
    "services/core/tests/test_live_provider_staging_lifespan.py",
    "        assert isinstance(started, SQLiteLiveProviderStagingResultStore)\n"
    "        assert started.path == str(staging_path.resolve())\n"
    "        assert started.load() == []\n",
    "        assert isinstance(\n"
    "            started,\n"
    "            TraceLinkedLiveProviderStagingResultStore,\n"
    "        )\n"
    "        assert isinstance(\n"
    "            started.underlying_store,\n"
    "            SQLiteLiveProviderStagingResultStore,\n"
    "        )\n"
    "        assert started.underlying_store.path == str(staging_path.resolve())\n"
    "        assert started.load() == []\n",
)
replace_once(
    "services/core/tests/test_live_provider_staging_lifespan.py",
    "            live_provider_staging_result_store_registry.current(),\n"
    "            SQLiteLiveProviderStagingResultStore,\n"
    "        )\n\n"
    "    assert order == [\"staging\", \"invocations\"]\n",
    "            live_provider_staging_result_store_registry.current(),\n"
    "            TraceLinkedLiveProviderStagingResultStore,\n"
    "        )\n\n"
    "    assert order == [\"staging\", \"invocations\"]\n",
)

trace_tests = '''from __future__ import annotations

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
'''
(ROOT / "services/core/tests/test_live_provider_staging_trace.py").write_text(
    trace_tests,
    encoding="utf-8",
)

append_once(
    "docs/validation/phase-1-9-user-api-contract-candidate.md",
    "## Deterministic Trace linkage",
    '''## Deterministic Trace linkage

The staging-result payload now carries the canonical request-level `trace_id`
and the canonical fresh invocation-terminal event identity. These identities are
derived from existing Trace contracts and are excluded from the staging result
content hash because they are deterministic projections of request/invocation
identity rather than an independent authority.

Core publishes a `TraceLinkedLiveProviderStagingResultStore` that validates every
claim, lookup, invocation lookup and load against the retained terminal model
invocation event and its exact native `InvocationRecord`. Validation checks the
immutable event identity, source-authority hash, state, committed usage and
result-payload hash. Missing, changed or corrupt evidence fails closed before a
new staging result is persisted. Exact replay performs only durable local reads
and does not call the provider or User API.

Trace retention now unions request identities referenced by durable staging
results with the existing task/invocation protection set, preventing a retained
staging result from outliving its required audit Trace. This increment adds no
new Trace event kind, does not make Trace execution authority and stores no raw
prompt, output, provider body, header, credential, IP address or private User API
field.''',
)

replace_once(
    "docs/DEVELOPMENT_HANDOFF.md",
    "- Next substep: deterministic staging-result linkage to correlated Trace\n"
    "  identity and terminal evidence\n",
    "- Active substep: deterministic staging-result linkage to correlated Trace\n"
    "  identity and terminal evidence\n",
)
replace_once(
    "docs/DEVELOPMENT_HANDOFF.md",
    "## Exact continuation point\n\nFirst verify the current branch Head and its ordinary CI, then audit how\n",
    "## Trace-link candidate in this commit\n\n"
    "- Adds canonical `trace_id` and invocation-terminal event identity to every\n"
    "  staging result without changing its content-addressed result identity.\n"
    "- Validates every published staging-result store read/write against exact\n"
    "  Invocation and immutable Trace authority.\n"
    "- Protects traces referenced by durable staging results from retention\n"
    "  pruning.\n"
    "- Adds positive, replay, mismatch/tamper and SQLite restart coverage.\n\n"
    "This candidate has not yet passed the exact resulting-head CI. The next\n"
    "execution must verify that CI and update this file with the product SHA, run\n"
    "ID, test counts and artifact IDs before starting cancellation durability.\n\n"
    "## Exact continuation point\n\nFirst verify the current branch Head and its ordinary CI. If the Trace-link\n"
    "candidate is not fully green, inspect and fix only candidate-caused failures.\n"
    "Once its exact Head passes Core and Android gates, update this Handoff with\n"
    "the verified SHA and CI evidence. Then start only the next Phase 1.9 substep:\n"
    "persist sanitized cancellation and transport-uncertainty outcomes without a\n"
    "second provider request. Do not start reconciliation-disposition changes, the\n"
    "protected live workflow or a real provider call in the same increment.\n\n"
    "<!-- Previous continuation rationale retained below for audit. -->\n\n"
    "First verify the current branch Head and its ordinary CI, then audit how\n",
)

for path in (
    "services/core/src/simorgh_core/agents/live_provider_staging_contracts.py",
    "services/core/src/simorgh_core/agents/live_provider_staging.py",
    "services/core/src/simorgh_core/agents/live_provider_staging_trace.py",
    "services/core/src/simorgh_core/app.py",
    "services/core/tests/test_live_provider_staging_store.py",
    "services/core/tests/test_live_provider_staging_lifespan.py",
    "services/core/tests/test_live_provider_staging_trace.py",
):
    compile((ROOT / path).read_text(encoding="utf-8"), path, "exec")

print("Phase 1.9 deterministic Trace-link candidate applied.")
