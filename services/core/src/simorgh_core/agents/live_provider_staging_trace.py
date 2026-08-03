from __future__ import annotations

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
    def validate_identity(self) -> LiveProviderStagingTraceEvidence:
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
