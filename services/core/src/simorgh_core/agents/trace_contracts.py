from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.contracts import (
    InvocationState,
    RoutingMethod,
    RoutingState,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    canonical_fingerprint,
)
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.task_state import AgentTaskPhase

TRACE_CONTRACT_VERSION: Literal["1.0"] = "1.0"
MAX_TRACE_EVENTS = 100_000
MAX_TRACE_GAPS = 256
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
_AGENT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_SCHEMA_VERSION_PATTERN = r"^[0-9]+\.[0-9]+$"
_POLICY_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"client[_-]?secret|password)\b\s*[:=]\s*[\"']?"
        r"[A-Za-z0-9_./+=-]{16,}"
    ),
)


class TraceContractError(RuntimeError):
    """Base class for deterministic durable-trace contract failures."""


class TraceStage(StrEnum):
    TASK = "task"
    ROUTING = "routing"
    BUDGET = "budget"
    CONTEXT = "context"
    MODEL = "model"
    TOOL = "tool"
    SPECIALIST = "specialist"
    RESULT = "result"
    CANCELLATION = "cancellation"
    TERMINAL = "terminal"


class TraceSourceAuthorityKind(StrEnum):
    TASK_RECORD = "task_record"
    ROUTING_DECISION = "routing_decision"
    INVOCATION_RECORD = "invocation_record"
    CONTEXT_BUNDLE = "context_bundle"
    RESULT_RECORD = "result_record"
    CANCELLATION_RECORD = "cancellation_record"
    TRACE_RECONCILIATION = "trace_reconciliation"


class DurableTraceEventKind(StrEnum):
    TASK_CLAIMED = "task_claimed"
    TASK_TERMINAL = "task_terminal"
    ROUTING_DECIDED = "routing_decided"
    BUDGET_RESERVED = "budget_reserved"
    BUDGET_RECONCILED = "budget_reconciled"
    INVOCATION_STARTED = "invocation_started"
    INVOCATION_TERMINAL = "invocation_terminal"
    INVOCATION_REPLAYED = "invocation_replayed"
    CONTEXT_COMPILED = "context_compiled"
    CONTEXT_REPLAYED = "context_replayed"
    CONTEXT_FAILED = "context_failed"
    RESULT_COMMITTED = "result_committed"
    RESULT_REPLAYED = "result_replayed"
    RESULT_FAILED = "result_failed"
    CANCELLATION_SETTLED = "cancellation_settled"
    CANCELLATION_REPLAYED = "cancellation_replayed"
    TRACE_TERMINAL = "trace_terminal"
    TRACE_GAP = "trace_gap"


class DurableTraceReplayDisposition(StrEnum):
    FRESH = "fresh"
    REPLAYED = "replayed"


class DurableTraceCacheDisposition(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    HIT = "hit"
    MISS = "miss"
    BYPASSED_POLICY = "bypassed_policy"


class TraceDisposition(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"
    NEEDS_ESCALATION = "needs_escalation"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_BLOCKED = "policy_blocked"
    CONTRACT_INVALID = "contract_invalid"
    UNKNOWN = "unknown"
    UNKNOWN_SIDE_EFFECT = "unknown_side_effect"
    INCOMPLETE_GAP = "incomplete_gap"
    CORRUPT = "corrupt"


class TraceBudgetAction(StrEnum):
    RESERVED = "reserved"
    RECONCILED = "reconciled"
    RELEASED = "released"
    EXHAUSTED = "exhausted"


class TraceGapCode(StrEnum):
    MISSING_TASK = "missing_task"
    MISSING_ROUTING = "missing_routing"
    MISSING_CONTEXT = "missing_context"
    MISSING_INVOCATION = "missing_invocation"
    MISSING_RESULT = "missing_result"
    MISSING_PARENT_EVENT = "missing_parent_event"
    SOURCE_HASH_MISMATCH = "source_hash_mismatch"
    RETENTION_GAP = "retention_gap"


class TraceTaskDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["task"] = "task"
    task_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    phase: AgentTaskPhase


class TraceRoutingDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["routing"] = "routing"
    routing_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    state: RoutingState
    method: RoutingMethod | None = None
    selected_agent_id: str | None = Field(
        default=None,
        pattern=_AGENT_ID_PATTERN,
        max_length=128,
    )
    selected_agent_version: str | None = Field(
        default=None,
        pattern=_POLICY_VERSION_PATTERN,
        max_length=32,
    )

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        selected = self.selected_agent_id is not None
        versioned = self.selected_agent_version is not None
        if selected != versioned:
            raise ValueError("routing agent identity and version must appear together")
        if self.state == RoutingState.ROUTED:
            if not selected or self.method is None:
                raise ValueError("routed trace detail requires method and selected agent")
        elif selected:
            raise ValueError("non-routed trace detail cannot select an agent")
        return self


class TraceBudgetDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["budget"] = "budget"
    action: TraceBudgetAction
    budget_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    exhausted_dimension: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=64,
    )

    @field_validator("exhausted_dimension")
    @classmethod
    def validate_dimension(cls, value: str | None) -> str | None:
        return _safe_optional_identifier(value)

    @model_validator(mode="after")
    def validate_exhaustion(self) -> Self:
        if self.action == TraceBudgetAction.EXHAUSTED:
            if self.exhausted_dimension is None:
                raise ValueError("exhausted budget detail requires a dimension")
        elif self.exhausted_dimension is not None:
            raise ValueError("non-exhausted budget detail cannot carry a dimension")
        return self


class TraceInvocationDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["invocation"] = "invocation"
    invocation_kind: InvocationKind
    effect: InvocationEffect
    state: InvocationState
    operation_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    input_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    attempt: int = Field(default=1, ge=1, le=1_000)
    result_payload_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    failure_code: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )

    @field_validator("operation_id")
    @classmethod
    def validate_operation_id(cls, value: str) -> str:
        return _safe_required_identifier(value)

    @field_validator("failure_code")
    @classmethod
    def validate_failure_code(cls, value: str | None) -> str | None:
        return _safe_optional_identifier(value)

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.state == InvocationState.COMPLETED:
            if self.result_payload_sha256 is None:
                raise ValueError("completed invocation detail requires result hash")
            if self.failure_code is not None:
                raise ValueError("completed invocation detail cannot carry failure code")
        elif self.result_payload_sha256 is not None:
            raise ValueError("non-completed invocation detail cannot carry result hash")
        return self


class TraceContextDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["context"] = "context"
    context_bundle_id: UUID
    context_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    source_manifest_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    section_count: int = Field(ge=1, le=256)
    omission_count: int = Field(ge=0, le=256)


class TraceResultDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["result"] = "result"
    result_id: UUID
    result_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    result_schema_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    result_schema_version: str = Field(pattern=_SCHEMA_VERSION_PATTERN, max_length=32)

    @field_validator("result_schema_id")
    @classmethod
    def validate_schema_id(cls, value: str) -> str:
        return _safe_required_identifier(value)


class TraceCancellationDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["cancellation"] = "cancellation"
    cancellation_id: UUID
    cancellation_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    settled_invocation_count: int = Field(ge=0, le=100_000)
    uncertain_invocation_count: int = Field(ge=0, le=100_000)


class TraceTerminalDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["terminal"] = "terminal"
    disposition: TraceDisposition
    reason_code: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str) -> str:
        return _safe_required_identifier(value)

    @model_validator(mode="after")
    def validate_terminal_disposition(self) -> Self:
        if self.disposition in {
            TraceDisposition.IN_PROGRESS,
            TraceDisposition.INCOMPLETE_GAP,
            TraceDisposition.CORRUPT,
        }:
            raise ValueError("terminal event requires an authoritative terminal disposition")
        return self


class TraceGapDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    family: Literal["gap"] = "gap"
    gap_code: TraceGapCode
    missing_stage: TraceStage
    missing_source_kind: TraceSourceAuthorityKind
    missing_source_id: UUID | None = None


type TraceEventDetails = Annotated[
    TraceTaskDetails
    | TraceRoutingDetails
    | TraceBudgetDetails
    | TraceInvocationDetails
    | TraceContextDetails
    | TraceResultDetails
    | TraceCancellationDetails
    | TraceTerminalDetails
    | TraceGapDetails,
    Field(discriminator="family"),
]


class TraceEventCandidate(BaseModel):
    """One immutable source-linked event before durable sequence assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = TRACE_CONTRACT_VERSION
    trace_id: UUID
    event_id: UUID
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    request_id: UUID
    event_kind: DurableTraceEventKind
    stage: TraceStage
    source_authority_kind: TraceSourceAuthorityKind
    source_authority_id: UUID
    source_authority_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    parent_event_id: UUID | None = None
    causation_event_id: UUID | None = None
    replay_of_event_id: UUID | None = None
    invocation_id: UUID | None = None
    parent_invocation_id: UUID | None = None
    context_bundle_id: UUID | None = None
    result_id: UUID | None = None
    replay: DurableTraceReplayDisposition = DurableTraceReplayDisposition.FRESH
    cache: DurableTraceCacheDisposition = DurableTraceCacheDisposition.NOT_APPLICABLE
    usage: UsageVector = Field(default_factory=UsageVector)
    occurred_at_ms: int = Field(ge=0)
    privacy: PrivacyClassification = PrivacyClassification.INTERNAL
    retention: RetentionDisposition = RetentionDisposition.PROJECT
    details: TraceEventDetails

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.trace_id != trace_id_for(self.request_id):
            raise ValueError("trace ID does not match request identity")
        expected_event_id = trace_event_id_for(
            trace_id=self.trace_id,
            source_authority_kind=self.source_authority_kind,
            source_authority_id=self.source_authority_id,
            event_kind=self.event_kind,
            replay=self.replay,
        )
        if self.event_id != expected_event_id:
            raise ValueError("trace event ID does not match source identity")
        _validate_event_family(self)
        if self.parent_event_id == self.event_id:
            raise ValueError("trace event cannot parent itself")
        if self.causation_event_id == self.event_id:
            raise ValueError("trace event cannot cause itself")
        if self.replay_of_event_id == self.event_id:
            raise ValueError("trace event cannot replay itself")
        if (
            self.invocation_id is not None
            and self.parent_invocation_id == self.invocation_id
        ):
            raise ValueError("trace invocation cannot parent itself")
        if self.replay == DurableTraceReplayDisposition.REPLAYED:
            if self.replay_of_event_id is None:
                raise ValueError("replayed trace event requires original event identity")
            if self.usage != UsageVector():
                raise ValueError("replayed trace event cannot report new usage")
        elif self.replay_of_event_id is not None:
            raise ValueError("fresh trace event cannot reference replay origin")
        if self.canonical_sha256 != trace_event_canonical_sha256(self):
            raise ValueError("trace event hash does not match authoritative content")
        return self


class TraceEventRecord(TraceEventCandidate):
    """Durably sequenced trace event; ingestion time is not event identity."""

    sequence: int = Field(ge=1, le=MAX_TRACE_EVENTS)
    ingested_at_ms: int = Field(ge=0)


class TraceGapSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    gap_event_id: UUID
    code: TraceGapCode
    missing_stage: TraceStage
    missing_source_kind: TraceSourceAuthorityKind
    missing_source_id: UUID | None = None


class TraceEnvelope(BaseModel):
    """Immutable request-level reconstruction summary over ordered event authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = TRACE_CONTRACT_VERSION
    trace_id: UUID
    request_id: UUID
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    disposition: TraceDisposition
    terminal: bool
    event_count: int = Field(ge=1, le=MAX_TRACE_EVENTS)
    first_sequence: int = Field(ge=1, le=MAX_TRACE_EVENTS)
    last_sequence: int = Field(ge=1, le=MAX_TRACE_EVENTS)
    first_observed_at_ms: int = Field(ge=0)
    last_observed_at_ms: int = Field(ge=0)
    last_ingested_at_ms: int = Field(ge=0)
    event_manifest_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    privacy: PrivacyClassification
    retention: RetentionDisposition
    gap_count: int = Field(ge=0, le=MAX_TRACE_GAPS)
    gaps: tuple[TraceGapSummary, ...] = Field(default=(), max_length=MAX_TRACE_GAPS)

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.trace_id != trace_id_for(self.request_id):
            raise ValueError("trace envelope ID does not match request identity")
        if self.first_sequence > self.last_sequence:
            raise ValueError("trace sequence range is invalid")
        if self.last_sequence - self.first_sequence + 1 != self.event_count:
            raise ValueError("trace sequence range is not contiguous")
        if self.first_observed_at_ms > self.last_observed_at_ms:
            raise ValueError("trace observation range is invalid")
        if self.gap_count != len(self.gaps):
            raise ValueError("trace gap count is invalid")
        if self.disposition == TraceDisposition.IN_PROGRESS:
            if self.terminal:
                raise ValueError("in-progress trace cannot be terminal")
        elif not self.terminal:
            raise ValueError("non-progress trace disposition must be terminal")
        if self.gap_count and self.disposition != TraceDisposition.INCOMPLETE_GAP:
            raise ValueError("trace gaps require incomplete-gap disposition")
        if not self.gap_count and self.disposition == TraceDisposition.INCOMPLETE_GAP:
            raise ValueError("incomplete-gap disposition requires a gap")
        if self.canonical_sha256 != trace_envelope_canonical_sha256(self):
            raise ValueError("trace envelope hash does not match authoritative summary")
        return self


class TraceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    envelope: TraceEnvelope
    events: tuple[TraceEventRecord, ...] = Field(
        min_length=1,
        max_length=MAX_TRACE_EVENTS,
    )

    @model_validator(mode="after")
    def validate_view(self) -> Self:
        if len(self.events) != self.envelope.event_count:
            raise ValueError("trace view event count does not match envelope")
        expected_sequences = tuple(range(1, len(self.events) + 1))
        if tuple(event.sequence for event in self.events) != expected_sequences:
            raise ValueError("trace view events must be strictly contiguous")
        if any(event.trace_id != self.envelope.trace_id for event in self.events):
            raise ValueError("trace view contains an event from another trace")
        if any(event.request_id != self.envelope.request_id for event in self.events):
            raise ValueError("trace view contains an event from another request")
        if trace_event_manifest_sha256(self.events) != self.envelope.event_manifest_sha256:
            raise ValueError("trace view manifest does not match envelope")
        return self


def trace_id_for(request_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"simorgh-trace:{request_id}")


def trace_event_id_for(
    *,
    trace_id: UUID,
    source_authority_kind: TraceSourceAuthorityKind,
    source_authority_id: UUID,
    event_kind: DurableTraceEventKind,
    replay: DurableTraceReplayDisposition,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "simorgh-trace-event:"
        f"{trace_id}:{source_authority_kind.value}:{source_authority_id}:"
        f"{event_kind.value}:{replay.value}",
    )


def trace_event_canonical_payload(
    value: TraceEventCandidate | TraceEventRecord | dict[str, Any],
) -> dict[str, Any]:
    payload = (
        value.model_dump(mode="json")
        if isinstance(value, BaseModel)
        else dict(value)
    )
    for field in (
        "event_id",
        "canonical_sha256",
        "occurred_at_ms",
        "sequence",
        "ingested_at_ms",
    ):
        payload.pop(field, None)
    return payload


def trace_event_canonical_sha256(
    value: TraceEventCandidate | TraceEventRecord | dict[str, Any],
) -> str:
    return canonical_fingerprint(trace_event_canonical_payload(value))


def trace_event_manifest_sha256(events: tuple[TraceEventRecord, ...]) -> str:
    return canonical_fingerprint(
        {
            "events": [
                {
                    "sequence": event.sequence,
                    "event_id": str(event.event_id),
                    "canonical_sha256": event.canonical_sha256,
                }
                for event in events
            ]
        }
    )


def trace_envelope_canonical_payload(
    value: TraceEnvelope | dict[str, Any],
) -> dict[str, Any]:
    payload = (
        value.model_dump(mode="json")
        if isinstance(value, BaseModel)
        else dict(value)
    )
    for field in (
        "canonical_sha256",
        "first_observed_at_ms",
        "last_observed_at_ms",
        "last_ingested_at_ms",
    ):
        payload.pop(field, None)
    return payload


def trace_envelope_canonical_sha256(value: TraceEnvelope | dict[str, Any]) -> str:
    return canonical_fingerprint(trace_envelope_canonical_payload(value))


def new_trace_event_candidate(
    *,
    request_id: UUID,
    event_kind: DurableTraceEventKind,
    stage: TraceStage,
    source_authority_kind: TraceSourceAuthorityKind,
    source_authority_id: UUID,
    source_authority_sha256: str,
    details: TraceEventDetails,
    occurred_at_ms: int,
    parent_event_id: UUID | None = None,
    causation_event_id: UUID | None = None,
    replay_of_event_id: UUID | None = None,
    invocation_id: UUID | None = None,
    parent_invocation_id: UUID | None = None,
    context_bundle_id: UUID | None = None,
    result_id: UUID | None = None,
    replay: DurableTraceReplayDisposition = DurableTraceReplayDisposition.FRESH,
    cache: DurableTraceCacheDisposition = DurableTraceCacheDisposition.NOT_APPLICABLE,
    usage: UsageVector | None = None,
    privacy: PrivacyClassification = PrivacyClassification.INTERNAL,
    retention: RetentionDisposition = RetentionDisposition.PROJECT,
) -> TraceEventCandidate:
    trace_id = trace_id_for(request_id)
    event_id = trace_event_id_for(
        trace_id=trace_id,
        source_authority_kind=source_authority_kind,
        source_authority_id=source_authority_id,
        event_kind=event_kind,
        replay=replay,
    )
    provisional = TraceEventCandidate.model_construct(
        schema_version=TRACE_CONTRACT_VERSION,
        trace_id=trace_id,
        event_id=event_id,
        canonical_sha256="0" * 64,
        request_id=request_id,
        event_kind=event_kind,
        stage=stage,
        source_authority_kind=source_authority_kind,
        source_authority_id=source_authority_id,
        source_authority_sha256=source_authority_sha256,
        parent_event_id=parent_event_id,
        causation_event_id=causation_event_id,
        replay_of_event_id=replay_of_event_id,
        invocation_id=invocation_id,
        parent_invocation_id=parent_invocation_id,
        context_bundle_id=context_bundle_id,
        result_id=result_id,
        replay=replay,
        cache=cache,
        usage=usage or UsageVector(),
        occurred_at_ms=occurred_at_ms,
        privacy=privacy,
        retention=retention,
        details=details,
    )
    return TraceEventCandidate.model_validate(
        {
            **provisional.model_dump(mode="json"),
            "canonical_sha256": trace_event_canonical_sha256(provisional),
        }
    )


def _safe_required_identifier(value: str) -> str:
    if any(pattern.search(value) is not None for pattern in _SECRET_PATTERNS):
        raise ValueError("trace identifier contains secret-like credential material")
    return value


def _safe_optional_identifier(value: str | None) -> str | None:
    return None if value is None else _safe_required_identifier(value)


def _validate_event_family(event: TraceEventCandidate) -> None:
    family = event.details.family
    allowed_kinds: dict[str, frozenset[DurableTraceEventKind]] = {
        "task": frozenset(
            {
                DurableTraceEventKind.TASK_CLAIMED,
                DurableTraceEventKind.TASK_TERMINAL,
            }
        ),
        "routing": frozenset({DurableTraceEventKind.ROUTING_DECIDED}),
        "budget": frozenset(
            {
                DurableTraceEventKind.BUDGET_RESERVED,
                DurableTraceEventKind.BUDGET_RECONCILED,
            }
        ),
        "invocation": frozenset(
            {
                DurableTraceEventKind.INVOCATION_STARTED,
                DurableTraceEventKind.INVOCATION_TERMINAL,
                DurableTraceEventKind.INVOCATION_REPLAYED,
            }
        ),
        "context": frozenset(
            {
                DurableTraceEventKind.CONTEXT_COMPILED,
                DurableTraceEventKind.CONTEXT_REPLAYED,
                DurableTraceEventKind.CONTEXT_FAILED,
            }
        ),
        "result": frozenset(
            {
                DurableTraceEventKind.RESULT_COMMITTED,
                DurableTraceEventKind.RESULT_REPLAYED,
                DurableTraceEventKind.RESULT_FAILED,
            }
        ),
        "cancellation": frozenset(
            {
                DurableTraceEventKind.CANCELLATION_SETTLED,
                DurableTraceEventKind.CANCELLATION_REPLAYED,
            }
        ),
        "terminal": frozenset({DurableTraceEventKind.TRACE_TERMINAL}),
        "gap": frozenset({DurableTraceEventKind.TRACE_GAP}),
    }
    if event.event_kind not in allowed_kinds[family]:
        raise ValueError("trace event kind does not match typed detail family")

    if isinstance(event.details, TraceInvocationDetails):
        expected_stage = {
            InvocationKind.MODEL: TraceStage.MODEL,
            InvocationKind.TOOL: TraceStage.TOOL,
            InvocationKind.SPECIALIST: TraceStage.SPECIALIST,
        }[event.details.invocation_kind]
    else:
        expected_stage = {
            "task": TraceStage.TASK,
            "routing": TraceStage.ROUTING,
            "budget": TraceStage.BUDGET,
            "context": TraceStage.CONTEXT,
            "result": TraceStage.RESULT,
            "cancellation": TraceStage.CANCELLATION,
            "terminal": TraceStage.TERMINAL,
            "gap": TraceStage.TERMINAL,
        }[family]
    if event.stage != expected_stage:
        raise ValueError("trace stage does not match typed detail family")

    expected_source = {
        "task": TraceSourceAuthorityKind.TASK_RECORD,
        "routing": TraceSourceAuthorityKind.ROUTING_DECISION,
        "invocation": TraceSourceAuthorityKind.INVOCATION_RECORD,
        "context": TraceSourceAuthorityKind.CONTEXT_BUNDLE,
        "result": TraceSourceAuthorityKind.RESULT_RECORD,
        "cancellation": TraceSourceAuthorityKind.CANCELLATION_RECORD,
        "terminal": TraceSourceAuthorityKind.TASK_RECORD,
        "gap": TraceSourceAuthorityKind.TRACE_RECONCILIATION,
    }.get(family)
    if family == "budget":
        if event.source_authority_kind not in {
            TraceSourceAuthorityKind.TASK_RECORD,
            TraceSourceAuthorityKind.INVOCATION_RECORD,
        }:
            raise ValueError("budget trace requires task or invocation authority")
    elif event.source_authority_kind != expected_source:
        raise ValueError("trace source authority does not match typed detail family")

    if isinstance(event.details, TraceInvocationDetails):
        if event.invocation_id != event.source_authority_id:
            raise ValueError("invocation trace source must equal invocation identity")
    elif event.invocation_id is not None and family not in {
        "budget",
        "cancellation",
        "context",
        "result",
        "routing",
    }:
        raise ValueError("trace family cannot carry invocation identity")

    if isinstance(event.details, TraceContextDetails):
        if event.context_bundle_id != event.details.context_bundle_id:
            raise ValueError("context detail identity does not match trace event")
        if event.source_authority_id != event.details.context_bundle_id:
            raise ValueError("context trace source must equal context identity")
    elif event.context_bundle_id is not None and family not in {"result", "terminal"}:
        raise ValueError("trace family cannot carry context identity")

    if isinstance(event.details, TraceResultDetails):
        if event.result_id != event.details.result_id:
            raise ValueError("result detail identity does not match trace event")
        if event.source_authority_id != event.details.result_id:
            raise ValueError("result trace source must equal result identity")
    elif event.result_id is not None and family != "terminal":
        raise ValueError("trace family cannot carry result identity")


__all__ = [
    "TRACE_CONTRACT_VERSION",
    "DurableTraceCacheDisposition",
    "DurableTraceEventKind",
    "DurableTraceReplayDisposition",
    "TraceBudgetAction",
    "TraceBudgetDetails",
    "TraceCancellationDetails",
    "TraceContextDetails",
    "TraceContractError",
    "TraceDisposition",
    "TraceEnvelope",
    "TraceEventCandidate",
    "TraceEventDetails",
    "TraceEventRecord",
    "TraceGapCode",
    "TraceGapDetails",
    "TraceGapSummary",
    "TraceInvocationDetails",
    "TraceResultDetails",
    "TraceRoutingDetails",
    "TraceSourceAuthorityKind",
    "TraceStage",
    "TraceTaskDetails",
    "TraceTerminalDetails",
    "TraceView",
    "new_trace_event_candidate",
    "trace_envelope_canonical_payload",
    "trace_envelope_canonical_sha256",
    "trace_event_canonical_payload",
    "trace_event_canonical_sha256",
    "trace_event_id_for",
    "trace_event_manifest_sha256",
    "trace_id_for",
]