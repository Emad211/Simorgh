from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    canonical_fingerprint,
)
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.tracing import CacheDisposition, TraceEventKind

TRACE_AUTHORITY_SCHEMA_VERSION: Literal["1.0"] = "1.0"
MAX_TRACE_REFERENCE_IDS = 64
MAX_TRACE_EVENTS_PER_PROJECTION = 100_000
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
_POLICY_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_SCHEMA_VERSION_PATTERN = r"^[0-9]+\.[0-9]+$"


class TraceAuthorityError(RuntimeError):
    """Base class for deterministic correlated-trace authority failures."""


class TraceContractError(TraceAuthorityError):
    pass


class TraceOutcomeCode(StrEnum):
    STARTED = "started"
    RESERVED = "reserved"
    RECONCILED = "reconciled"
    ROUTED = "routed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"
    UNKNOWN_SIDE_EFFECT = "unknown_side_effect"
    REPLAYED = "replayed"
    POLICY_BLOCKED = "policy_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ESCALATED = "escalated"
    GAP_DETECTED = "gap_detected"
    RECOVERED = "recovered"


class TraceReasonCode(StrEnum):
    ROUTE_SELECTED = "route_selected"
    POLICY_BLOCKED = "policy_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXPIRED = "deadline_expired"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLATION_SETTLED = "cancellation_settled"
    CONTRACT_INVALID = "contract_invalid"
    STORE_FAILURE = "store_failure"
    TRANSPORT_UNCERTAIN = "transport_uncertain"
    REPLAY_HIT = "replay_hit"
    CONTEXT_COMPILED = "context_compiled"
    RESULT_COMMITTED = "result_committed"
    GAP_MISSING_EVENT = "gap_missing_event"
    GAP_AUTHORITY_MISMATCH = "gap_authority_mismatch"
    GAP_USAGE_MISMATCH = "gap_usage_mismatch"
    STARTED_APPROVED_WORK = "started_approved_work"
    COMPLETED_APPROVED_WORK = "completed_approved_work"


class TraceGapCode(StrEnum):
    MISSING_EVENT = "missing_event"
    AUTHORITY_MISMATCH = "authority_mismatch"
    USAGE_MISMATCH = "usage_mismatch"
    NON_CONTIGUOUS_SEQUENCE = "non_contiguous_sequence"


class TraceCompletenessStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"
    UNKNOWN_SIDE_EFFECT = "unknown_side_effect"
    REPLAYED = "replayed"
    GAP_DETECTED = "gap_detected"


class TraceAttributes(BaseModel):
    """Closed, metadata-only attributes; raw task and provider content cannot enter."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    routing_decision_id: UUID | None = None
    invocation_kind: InvocationKind | None = None
    invocation_effect: InvocationEffect | None = None
    context_sha256: str | None = Field(default=None, pattern=_HASH_PATTERN, max_length=64)
    result_sha256: str | None = Field(default=None, pattern=_HASH_PATTERN, max_length=64)
    projection_sha256: str | None = Field(default=None, pattern=_HASH_PATTERN, max_length=64)
    schema_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    schema_version: str | None = Field(
        default=None,
        pattern=_SCHEMA_VERSION_PATTERN,
        max_length=16,
    )
    privacy: PrivacyClassification | None = None
    retention: RetentionDisposition | None = None
    tainted: bool | None = None
    untrusted_source: bool | None = None
    source_count: int | None = Field(default=None, ge=0, le=1_000_000)
    section_count: int | None = Field(default=None, ge=0, le=1_000_000)
    omission_count: int | None = Field(default=None, ge=0, le=1_000_000)
    evidence_count: int | None = Field(default=None, ge=0, le=1_000_000)
    tool_count: int | None = Field(default=None, ge=0, le=1_000_000)
    byte_count: int | None = Field(default=None, ge=0, le=2_147_483_647)
    token_count: int | None = Field(default=None, ge=0, le=2_147_483_647)
    gap_code: TraceGapCode | None = None


class TraceEventDraft(BaseModel):
    """Caller-authored, metadata-only logical trace emission before store sequencing."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = TRACE_AUTHORITY_SCHEMA_VERSION
    event_id: UUID
    trace_id: UUID
    request_id: UUID
    kind: TraceEventKind
    occurred_at_ms: int = Field(ge=0)
    invocation_id: UUID | None = None
    parent_invocation_id: UUID | None = None
    context_bundle_id: UUID | None = None
    result_id: UUID | None = None
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=MAX_TRACE_REFERENCE_IDS)
    artifact_ids: tuple[UUID, ...] = Field(default=(), max_length=MAX_TRACE_REFERENCE_IDS)
    agent_id: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN, max_length=128)
    agent_version: str | None = Field(
        default=None,
        pattern=_POLICY_VERSION_PATTERN,
        max_length=32,
    )
    provider_id: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN, max_length=128)
    model_id: str | None = Field(default=None, min_length=1, max_length=256)
    tool_id: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN, max_length=128)
    connector_id: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN, max_length=128)
    cache: CacheDisposition = CacheDisposition.NOT_APPLICABLE
    outcome: TraceOutcomeCode
    reason_code: TraceReasonCode | None = None
    usage_delta: UsageVector = Field(default_factory=UsageVector)
    committed_usage: UsageVector | None = None
    attributes: TraceAttributes = Field(default_factory=TraceAttributes)

    @field_validator("evidence_ids", "artifact_ids")
    @classmethod
    def normalize_reference_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        ordered = tuple(sorted(value, key=str))
        if len(set(ordered)) != len(ordered):
            raise ValueError("trace reference identities must be unique")
        return ordered

    @model_validator(mode="after")
    def validate_trace_identity(self) -> Self:
        if self.trace_id != trace_id_for(self.request_id):
            raise ValueError("trace identity does not match request authority")
        if self.parent_invocation_id == self.invocation_id and self.invocation_id is not None:
            raise ValueError("trace invocation cannot parent itself")
        if self.outcome == TraceOutcomeCode.GAP_DETECTED:
            if self.attributes.gap_code is None:
                raise ValueError("gap-detected trace event requires a typed gap code")
        elif self.attributes.gap_code is not None:
            raise ValueError("typed gap code requires a gap-detected trace outcome")
        if (self.agent_id is None) != (self.agent_version is None):
            raise ValueError("trace agent identity requires ID and version together")
        return self


class StoredTraceEvent(TraceEventDraft):
    """Durably sequenced immutable trace event."""

    sequence: int = Field(ge=1)
    canonical_sha256: str = Field(pattern=_HASH_PATTERN, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_canonical_hash(self) -> Self:
        if canonical_fingerprint(trace_event_payload(self)) != self.canonical_sha256:
            raise ValueError("trace event canonical hash is invalid")
        return self


class TraceGap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    code: TraceGapCode
    after_sequence: int | None = Field(default=None, ge=1)
    expected_kind: TraceEventKind | None = None
    invocation_id: UUID | None = None


class TraceProjection(BaseModel):
    """Deterministic privacy-safe ordered projection for one request trace."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = TRACE_AUTHORITY_SCHEMA_VERSION
    trace_id: UUID
    request_id: UUID
    events: tuple[StoredTraceEvent, ...] = Field(
        min_length=1,
        max_length=MAX_TRACE_EVENTS_PER_PROJECTION,
    )
    event_count: int = Field(ge=1)
    first_sequence: int = Field(ge=1)
    last_sequence: int = Field(ge=1)
    first_occurred_at_ms: int = Field(ge=0)
    last_occurred_at_ms: int = Field(ge=0)
    total_usage_delta: UsageVector = Field(default_factory=UsageVector)
    latest_committed_usage: UsageVector = Field(default_factory=UsageVector)
    completeness: TraceCompletenessStatus
    gaps: tuple[TraceGap, ...] = Field(default=(), max_length=256)
    canonical_sha256: str = Field(pattern=_HASH_PATTERN, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.trace_id != trace_id_for(self.request_id):
            raise ValueError("trace projection identity does not match request")
        if self.event_count != len(self.events):
            raise ValueError("trace projection event count is invalid")
        if self.first_sequence != 1:
            raise ValueError("complete trace projection must start at sequence one")
        if self.first_sequence != self.events[0].sequence:
            raise ValueError("trace projection first sequence is invalid")
        if self.last_sequence != self.events[-1].sequence:
            raise ValueError("trace projection last sequence is invalid")
        if self.first_occurred_at_ms != self.events[0].occurred_at_ms:
            raise ValueError("trace projection first timestamp is invalid")
        if self.last_occurred_at_ms != self.events[-1].occurred_at_ms:
            raise ValueError("trace projection last timestamp is invalid")
        expected_sequences = tuple(range(self.first_sequence, self.last_sequence + 1))
        actual_sequences = tuple(event.sequence for event in self.events)
        if actual_sequences != expected_sequences:
            raise ValueError("trace projection sequence is not contiguous")
        for event in self.events:
            if event.trace_id != self.trace_id or event.request_id != self.request_id:
                raise ValueError("trace projection contains a foreign event")
        if sum_usage(event.usage_delta for event in self.events) != self.total_usage_delta:
            raise ValueError("trace projection usage delta is invalid")
        if _latest_committed_usage(self.events) != self.latest_committed_usage:
            raise ValueError("trace projection committed usage is invalid")
        if self.gaps and self.completeness != TraceCompletenessStatus.GAP_DETECTED:
            raise ValueError("trace projection gaps require gap-detected completeness")
        if not self.gaps and self.completeness == TraceCompletenessStatus.GAP_DETECTED:
            raise ValueError("gap-detected trace projection requires a typed gap")
        if canonical_fingerprint(trace_projection_payload(self)) != self.canonical_sha256:
            raise ValueError("trace projection canonical hash is invalid")
        return self


def trace_id_for(request_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"simorgh-trace:{request_id}")


def trace_event_id_for(
    *,
    request_id: UUID,
    kind: TraceEventKind,
    logical_identity: str,
) -> UUID:
    normalized = logical_identity.strip()
    if not normalized or len(normalized) > 1_000 or "\n" in normalized or "\r" in normalized:
        raise ValueError("trace logical event identity must be one bounded line")
    return uuid5(
        NAMESPACE_URL,
        f"simorgh-trace-event:{request_id}:{kind.value}:{normalized}",
    )


def trace_event_payload(event: StoredTraceEvent) -> dict[str, object]:
    return event.model_dump(mode="json", exclude={"canonical_sha256"})


def trace_draft_fingerprint(event: TraceEventDraft | StoredTraceEvent) -> str:
    return canonical_fingerprint(
        event.model_dump(
            mode="json",
            exclude={"sequence", "canonical_sha256"},
        )
    )


def stored_trace_event(draft: TraceEventDraft, *, sequence: int) -> StoredTraceEvent:
    if sequence < 1:
        raise ValueError("trace sequence must be positive")
    payload: dict[str, object] = draft.model_dump(mode="json")
    payload["sequence"] = sequence
    payload["canonical_sha256"] = canonical_fingerprint(payload)
    return StoredTraceEvent.model_validate(payload)


def build_trace_projection(
    events: tuple[StoredTraceEvent, ...],
    *,
    gaps: tuple[TraceGap, ...] = (),
) -> TraceProjection:
    if not events:
        raise TraceContractError("trace projection requires at least one event")
    ordered = tuple(sorted(events, key=lambda event: event.sequence))
    trace_id = ordered[0].trace_id
    request_id = ordered[0].request_id
    completeness = _completeness_for(ordered, gaps=gaps)
    payload: dict[str, object] = {
        "schema_version": TRACE_AUTHORITY_SCHEMA_VERSION,
        "trace_id": str(trace_id),
        "request_id": str(request_id),
        "events": [event.model_dump(mode="json") for event in ordered],
        "event_count": len(ordered),
        "first_sequence": ordered[0].sequence,
        "last_sequence": ordered[-1].sequence,
        "first_occurred_at_ms": ordered[0].occurred_at_ms,
        "last_occurred_at_ms": ordered[-1].occurred_at_ms,
        "total_usage_delta": sum_usage(
            event.usage_delta for event in ordered
        ).model_dump(mode="json"),
        "latest_committed_usage": _latest_committed_usage(ordered).model_dump(
            mode="json"
        ),
        "completeness": completeness.value,
        "gaps": [gap.model_dump(mode="json") for gap in gaps],
    }
    payload["canonical_sha256"] = canonical_fingerprint(payload)
    return TraceProjection.model_validate(payload)


def trace_projection_payload(projection: TraceProjection) -> dict[str, object]:
    return projection.model_dump(mode="json", exclude={"canonical_sha256"})


def sum_usage(values: Iterable[UsageVector]) -> UsageVector:
    total = UsageVector()
    for value in values:
        total = total.plus(value)
    return total


def _latest_committed_usage(events: tuple[StoredTraceEvent, ...]) -> UsageVector:
    latest = UsageVector()
    for event in events:
        if event.committed_usage is not None:
            latest = event.committed_usage
    return latest


def _completeness_for(
    events: tuple[StoredTraceEvent, ...],
    *,
    gaps: tuple[TraceGap, ...],
) -> TraceCompletenessStatus:
    if gaps:
        return TraceCompletenessStatus.GAP_DETECTED
    outcome = events[-1].outcome
    return {
        TraceOutcomeCode.COMPLETED: TraceCompletenessStatus.COMPLETE,
        TraceOutcomeCode.FAILED: TraceCompletenessStatus.FAILED,
        TraceOutcomeCode.CANCELLED: TraceCompletenessStatus.CANCELLED,
        TraceOutcomeCode.EXPIRED: TraceCompletenessStatus.EXPIRED,
        TraceOutcomeCode.UNKNOWN: TraceCompletenessStatus.UNKNOWN,
        TraceOutcomeCode.UNKNOWN_SIDE_EFFECT: TraceCompletenessStatus.UNKNOWN_SIDE_EFFECT,
        TraceOutcomeCode.REPLAYED: TraceCompletenessStatus.REPLAYED,
    }.get(outcome, TraceCompletenessStatus.IN_PROGRESS)


__all__ = [
    "MAX_TRACE_EVENTS_PER_PROJECTION",
    "MAX_TRACE_REFERENCE_IDS",
    "TRACE_AUTHORITY_SCHEMA_VERSION",
    "StoredTraceEvent",
    "TraceAttributes",
    "TraceAuthorityError",
    "TraceCompletenessStatus",
    "TraceContractError",
    "TraceEventDraft",
    "TraceGap",
    "TraceGapCode",
    "TraceOutcomeCode",
    "TraceProjection",
    "TraceReasonCode",
    "build_trace_projection",
    "stored_trace_event",
    "sum_usage",
    "trace_draft_fingerprint",
    "trace_event_id_for",
    "trace_event_payload",
    "trace_id_for",
    "trace_projection_payload",
]
