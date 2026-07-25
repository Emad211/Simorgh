from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from simorgh_core.agents.contracts import RoutingMethod, UsageVector

TraceScalar = str | int | bool | None
_FORBIDDEN_METADATA_FRAGMENTS = (
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "cookie",
    "raw_input",
    "input_text",
    "document_content",
    "email_body",
    "accessibility_tree",
)


class TraceEventKind(StrEnum):
    ROUTING_STARTED = "routing_started"
    ROUTING_COMPLETED = "routing_completed"
    BUDGET_RESERVED = "budget_reserved"
    BUDGET_RECONCILED = "budget_reconciled"
    INVOCATION_REPLAYED = "invocation_replayed"
    MODEL_STARTED = "model_started"
    MODEL_COMPLETED = "model_completed"
    MODEL_FAILED = "model_failed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    ESCALATION = "escalation"
    TERMINAL = "terminal"


class CacheDisposition(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    MISS = "miss"
    HIT = "hit"
    BYPASSED_FRESHNESS = "bypassed_freshness"
    BYPASSED_POLICY = "bypassed_policy"


class TraceEvent(BaseModel):
    """Non-secret audit metadata; task and private content are intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    invocation_id: UUID | None = None
    occurred_at_ms: int = Field(ge=0)
    kind: TraceEventKind
    agent_id: str | None = Field(default=None, max_length=128)
    agent_version: str | None = Field(default=None, max_length=32)
    routing_method: RoutingMethod | None = None
    rule_id: str | None = Field(default=None, max_length=128)
    provider_id: str | None = Field(default=None, max_length=128)
    model_id: str | None = Field(default=None, max_length=256)
    tool_id: str | None = Field(default=None, max_length=128)
    cache: CacheDisposition = CacheDisposition.NOT_APPLICABLE
    usage: UsageVector = Field(default_factory=UsageVector)
    outcome: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=1_000)
    metadata: dict[str, TraceScalar] = Field(default_factory=dict, max_length=64)

    @field_validator("metadata")
    @classmethod
    def validate_safe_metadata(
        cls,
        value: dict[str, TraceScalar],
    ) -> dict[str, TraceScalar]:
        for key, item in value.items():
            normalized = key.casefold().replace("-", "_")
            if any(fragment in normalized for fragment in _FORBIDDEN_METADATA_FRAGMENTS):
                raise ValueError(f"trace metadata key {key!r} is forbidden")
            if not key or len(key) > 128:
                raise ValueError("trace metadata keys must be in 1..128 characters")
            if isinstance(item, str) and len(item) > 1_000:
                raise ValueError("trace metadata string values are limited to 1000 characters")
        return value


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None: ...


class NullTraceSink:
    def emit(self, event: TraceEvent) -> None:
        del event


class InMemoryTraceSink:
    """Bounded process-local sink for tests and the first control-plane increment."""

    def __init__(self, *, maximum_events: int = 10_000) -> None:
        if maximum_events <= 0:
            raise ValueError("maximum_events must be positive")
        self._maximum_events = maximum_events
        self._lock = RLock()
        self._events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        validated = TraceEvent.model_validate(event.model_dump(mode="json"))
        with self._lock:
            self._events.append(validated)
            overflow = len(self._events) - self._maximum_events
            if overflow > 0:
                del self._events[:overflow]

    def for_request(self, request_id: UUID) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(
                event for event in self._events if event.request_id == request_id
            )

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def trace_event(
    *,
    request_id: UUID,
    kind: TraceEventKind,
    invocation_id: UUID | None = None,
    agent_id: str | None = None,
    agent_version: str | None = None,
    routing_method: RoutingMethod | None = None,
    rule_id: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    tool_id: str | None = None,
    cache: CacheDisposition = CacheDisposition.NOT_APPLICABLE,
    usage: UsageVector | None = None,
    outcome: str | None = None,
    reason: str | None = None,
    metadata: Mapping[str, TraceScalar] | None = None,
    wall_clock_millis: Callable[[], int] | None = None,
) -> TraceEvent:
    now = wall_clock_millis or (lambda: int(time.time() * 1_000))
    return TraceEvent(
        request_id=request_id,
        invocation_id=invocation_id,
        occurred_at_ms=max(0, int(now())),
        kind=kind,
        agent_id=agent_id,
        agent_version=agent_version,
        routing_method=routing_method,
        rule_id=rule_id,
        provider_id=provider_id,
        model_id=model_id,
        tool_id=tool_id,
        cache=cache,
        usage=usage or UsageVector(),
        outcome=outcome,
        reason=reason,
        metadata=dict(metadata or {}),
    )
