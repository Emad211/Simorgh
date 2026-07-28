from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.contracts import RoutingMethod, UsageVector
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.tracing import CacheDisposition, TraceEventKind

TRACE_AUTHORITY_SCHEMA_VERSION: Literal["1.0"] = "1.0"
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
_POLICY_VERSION_PATTERN = r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$"


class TraceAuthorityError(RuntimeError):
    """Base class for deterministic correlated-trace failures."""


class TraceContractError(TraceAuthorityError):
    pass


class TracePhase(StrEnum):
    TASK = "task"
    ROUTING = "routing"
    INVOCATION = "invocation"
    CONTEXT = "context"
    SPECIALIST = "specialist"
    MODEL = "model"
    TOOL = "tool"
    RESULT = "result"
    CANCELLATION = "cancellation"
    TERMINAL = "terminal"


class TraceUncertaintyDisposition(StrEnum):
    NONE = "none"
    UNKNOWN = "unknown"
    UNKNOWN_SIDE_EFFECT = "unknown_side_effect"


_PHASE_BY_KIND: dict[TraceEventKind, TracePhase] = {
    TraceEventKind.ROUTING_STARTED: TracePhase.ROUTING,
    TraceEventKind.ROUTING_COMPLETED: TracePhase.ROUTING,
    TraceEventKind.BUDGET_RESERVED: TracePhase.INVOCATION,
    TraceEventKind.BUDGET_RECONCILED: TracePhase.INVOCATION,
    TraceEventKind.INVOCATION_REPLAYED: TracePhase.INVOCATION,
    TraceEventKind.MODEL_STARTED: TracePhase.MODEL,
    TraceEventKind.MODEL_COMPLETED: TracePhase.MODEL,
    TraceEventKind.MODEL_FAILED: TracePhase.MODEL,
    TraceEventKind.TOOL_STARTED: TracePhase.TOOL,
    TraceEventKind.TOOL_COMPLETED: TracePhase.TOOL,
    TraceEventKind.TOOL_FAILED: TracePhase.TOOL,
    TraceEventKind.SPECIALIST_STARTED: TracePhase.SPECIALIST,
    TraceEventKind.SPECIALIST_COMPLETED: TracePhase.SPECIALIST,
    TraceEventKind.SPECIALIST_FAILED: TracePhase.SPECIALIST,
    TraceEventKind.RESULT_COMMITTED: TracePhase.RESULT,
    TraceEventKind.RESULT_REPLAYED: TracePhase.RESULT,
    TraceEventKind.RESULT_FAILED: TracePhase.RESULT,
    TraceEventKind.CANCELLATION_SETTLED: TracePhase.CANCELLATION,
    TraceEventKind.CANCELLATION_REPLAYED: TracePhase.CANCELLATION,
    TraceEventKind.CONTEXT_COMPILED: TracePhase.CONTEXT,
    TraceEventKind.CONTEXT_REPLAYED: TracePhase.CONTEXT,
    TraceEventKind.CONTEXT_FAILED: TracePhase.CONTEXT,
    TraceEventKind.ESCALATION: TracePhase.TERMINAL,
    TraceEventKind.TERMINAL: TracePhase.TERMINAL,
}


class TraceSafeMetadata(BaseModel):
    """Explicit non-content metadata admitted to durable trace authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    effect: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN, max_length=64)
    state_before: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=64,
    )
    state_after: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=64,
    )
    schema_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    schema_version: str | None = Field(
        default=None,
        pattern=_POLICY_VERSION_PATTERN,
        max_length=32,
    )
    context_sha256: str | None = Field(
        default=None,
        pattern=_FINGERPRINT_PATTERN,
        min_length=64,
        max_length=64,
    )
    result_sha256: str | None = Field(
        default=None,
        pattern=_FINGERPRINT_PATTERN,
        min_length=64,
        max_length=64,
    )
    projection_sha256: str | None = Field(
        default=None,
        pattern=_FINGERPRINT_PATTERN,
        min_length=64,
        max_length=64,
    )
    usage_snapshot_sha256: str | None = Field(
        default=None,
        pattern=_FINGERPRINT_PATTERN,
        min_length=64,
        max_length=64,
    )
    ownership_snapshot_sha256: str | None = Field(
        default=None,
        pattern=_FINGERPRINT_PATTERN,
        min_length=64,
        max_length=64,
    )
    source_reference_sha256: str | None = Field(
        default=None,
        pattern=_FINGERPRINT_PATTERN,
        min_length=64,
        max_length=64,
    )
    section_count: int | None = Field(default=None, ge=0, le=1_000_000)
    item_count: int | None = Field(default=None, ge=0, le=1_000_000)
    byte_count: int | None = Field(default=None, ge=0, le=2_147_483_647)
    estimated_tokens: int | None = Field(default=None, ge=0, le=2_147_483_647)
    omission_count: int | None = Field(default=None, ge=0, le=1_000_000)
    evidence_count: int | None = Field(default=None, ge=0, le=1_000_000)
    artifact_count: int | None = Field(default=None, ge=0, le=1_000_000)
    terminal_count: int | None = Field(default=None, ge=0, le=1_000_000)
    pending_count: int | None = Field(default=None, ge=0, le=1_000_000)
    reserved_count: int | None = Field(default=None, ge=0, le=1_000_000)
    replayed: bool | None = None


class TraceEventCandidate(BaseModel):
    """Strict Core-authored candidate before causal sequence allocation."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = TRACE_AUTHORITY_SCHEMA_VERSION
    request_id: UUID
    occurred_at_ms: int = Field(ge=0)
    kind: TraceEventKind
    phase: TracePhase
    operation_id: UUID | None = None
    invocation_id: UUID | None = None
    parent_invocation_id: UUID | None = None
    context_bundle_id: UUID | None = None
    result_id: UUID | None = None
    evidence_id: UUID | None = None
    cancellation_id: UUID | None = None
    agent_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    agent_version: str | None = Field(
        default=None,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$",
        max_length=32,
    )
    routing_method: RoutingMethod | None = None
    rule_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    provider_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    model_id: str | None = Field(default=None, min_length=1, max_length=256)
    tool_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    connector_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    cache: CacheDisposition = CacheDisposition.NOT_APPLICABLE
    usage_delta: UsageVector = Field(default_factory=UsageVector)
    outcome: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    reason_code: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    uncertainty: TraceUncertaintyDisposition = TraceUncertaintyDisposition.NONE
    privacy: PrivacyClassification = PrivacyClassification.INTERNAL
    retention: RetentionDisposition = RetentionDisposition.PROJECT
    tainted: bool = False
    metadata: TraceSafeMetadata = Field(default_factory=TraceSafeMetadata)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("trace model identity must be one bounded line")
        return normalized

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        expected_phase = _PHASE_BY_KIND.get(self.kind)
        if expected_phase is None or self.phase != expected_phase:
            raise ValueError("trace event kind does not match its authority phase")
        if self.parent_invocation_id == self.invocation_id and self.invocation_id is not None:
            raise ValueError("trace invocation cannot parent itself")
        if self.phase in {
            TracePhase.INVOCATION,
            TracePhase.SPECIALIST,
            TracePhase.MODEL,
            TracePhase.TOOL,
        } and self.invocation_id is None:
            raise ValueError("invocation trace phase requires invocation identity")
        if self.phase == TracePhase.SPECIALIST and self.agent_id is None:
            raise ValueError("specialist trace phase requires agent identity")
        if self.phase == TracePhase.MODEL and (
            self.provider_id is None or self.model_id is None
        ):
            raise ValueError("model trace phase requires provider and model identity")
        if self.phase == TracePhase.TOOL and self.tool_id is None:
            raise ValueError("tool trace phase requires tool identity")
        if self.kind in {
            TraceEventKind.CONTEXT_COMPILED,
            TraceEventKind.CONTEXT_REPLAYED,
        } and self.context_bundle_id is None:
            raise ValueError("completed context trace requires context identity")
        if self.kind in {
            TraceEventKind.RESULT_COMMITTED,
            TraceEventKind.RESULT_REPLAYED,
        } and self.result_id is None:
            raise ValueError("completed result trace requires result identity")
        if self.phase == TracePhase.CANCELLATION and self.cancellation_id is None:
            raise ValueError("cancellation trace phase requires cancellation identity")
        if self.uncertainty == TraceUncertaintyDisposition.UNKNOWN_SIDE_EFFECT and (
            self.metadata.effect != "mutation"
        ):
            raise ValueError("unknown-side-effect trace requires mutation effect")
        return self


class CorrelatedTraceEvent(TraceEventCandidate):
    """Immutable append-only event persisted by the trace authority."""

    trace_id: UUID
    event_id: UUID
    causal_sequence: int = Field(ge=1, le=9_223_372_036_854_775_807)
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )

    @model_validator(mode="after")
    def validate_authoritative_identity(self) -> Self:
        if self.trace_id != trace_id_for_request(self.request_id):
            raise ValueError("trace identity does not match request authority")
        if self.event_id != event_id_for_candidate(self):
            raise ValueError("trace event identity does not match event slot")
        if self.canonical_sha256 != canonical_trace_event_sha256(self):
            raise ValueError("trace event canonical hash does not match payload")
        return self


def trace_id_for_request(request_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"simorgh-execution-trace:{request_id}")


def event_id_for_candidate(candidate: TraceEventCandidate) -> UUID:
    slot = {
        "request_id": str(candidate.request_id),
        "kind": candidate.kind.value,
        "phase": candidate.phase.value,
        "operation_id": _uuid_text(candidate.operation_id),
        "invocation_id": _uuid_text(candidate.invocation_id),
        "parent_invocation_id": _uuid_text(candidate.parent_invocation_id),
        "context_bundle_id": _uuid_text(candidate.context_bundle_id),
        "result_id": _uuid_text(candidate.result_id),
        "evidence_id": _uuid_text(candidate.evidence_id),
        "cancellation_id": _uuid_text(candidate.cancellation_id),
        "agent_id": candidate.agent_id,
        "provider_id": candidate.provider_id,
        "model_id": candidate.model_id,
        "tool_id": candidate.tool_id,
        "connector_id": candidate.connector_id,
    }
    return uuid5(
        NAMESPACE_URL,
        "simorgh-trace-event-slot:" + canonical_fingerprint(slot),
    )


def materialize_trace_event(
    candidate: TraceEventCandidate,
    *,
    causal_sequence: int,
) -> CorrelatedTraceEvent:
    validated = TraceEventCandidate.model_validate(candidate.model_dump(mode="json"))
    trace_id = trace_id_for_request(validated.request_id)
    event_id = event_id_for_candidate(validated)
    payload = validated.model_dump(mode="json")
    authoritative = {
        **payload,
        "trace_id": str(trace_id),
        "event_id": str(event_id),
        "causal_sequence": causal_sequence,
    }
    return CorrelatedTraceEvent(
        **payload,
        trace_id=trace_id,
        event_id=event_id,
        causal_sequence=causal_sequence,
        canonical_sha256=canonical_fingerprint(authoritative),
    )


def canonical_trace_event_sha256(event: CorrelatedTraceEvent) -> str:
    payload = event.model_dump(mode="json", exclude={"canonical_sha256"})
    return canonical_fingerprint(payload)


def _uuid_text(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "TRACE_AUTHORITY_SCHEMA_VERSION",
    "CorrelatedTraceEvent",
    "TraceAuthorityError",
    "TraceContractError",
    "TraceEventCandidate",
    "TracePhase",
    "TraceSafeMetadata",
    "TraceUncertaintyDisposition",
    "canonical_trace_event_sha256",
    "event_id_for_candidate",
    "materialize_trace_event",
    "trace_id_for_request",
]
