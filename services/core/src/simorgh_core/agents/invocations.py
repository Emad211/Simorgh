from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from enum import StrEnum
from threading import RLock
from typing import Any, Protocol, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.contracts import UsageVector

MAX_INVOCATION_RESULT_BYTES = 1_000_000
_ZERO_USAGE = UsageVector()


class InvocationStoreError(RuntimeError):
    """Base class for deterministic invocation-store failures."""


class InvocationConflictError(InvocationStoreError):
    pass


class InvocationNotFoundError(InvocationStoreError):
    pass


class InvocationStateError(InvocationStoreError):
    pass


class InvocationStoreClosedError(InvocationStoreError):
    pass


class InvocationStoreCorruptionError(InvocationStoreError):
    pass


class InvocationStoreSchemaError(InvocationStoreError):
    pass


class InvocationStoreUnhealthyError(InvocationStoreError):
    pass


class InvocationStartKind(StrEnum):
    NEW = "new"
    REPLAY = "replay"
    IN_PROGRESS = "in_progress"
    TERMINAL = "terminal"


class InvocationPhase(StrEnum):
    PENDING = "pending"
    RESERVED = "reserved"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"
    UNKNOWN_SIDE_EFFECT = "unknown_side_effect"


class InvocationKind(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    SPECIALIST = "specialist"


class InvocationEffect(StrEnum):
    READ_ONLY = "read_only"
    PROPOSAL = "proposal"
    MUTATION = "mutation"


_TERMINAL_PHASES = frozenset(
    {
        InvocationPhase.COMPLETED,
        InvocationPhase.FAILED,
        InvocationPhase.CANCELLED,
        InvocationPhase.EXPIRED,
        InvocationPhase.UNKNOWN,
        InvocationPhase.UNKNOWN_SIDE_EFFECT,
    }
)


class InvocationRecord(BaseModel):
    """One immutable invocation identity with versionable operational state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    request_id: UUID
    agent_id: str = Field(min_length=1, max_length=128)
    agent_version: str = Field(min_length=1, max_length=32)
    operation: str = Field(min_length=1, max_length=128)
    input_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    kind: InvocationKind = InvocationKind.SPECIALIST
    effect: InvocationEffect = InvocationEffect.READ_ONLY
    provider_id: str | None = Field(default=None, max_length=128)
    model_id: str | None = Field(default=None, max_length=256)
    tool_id: str | None = Field(default=None, max_length=128)
    connector_id: str | None = Field(default=None, max_length=128)
    parent_invocation_id: UUID | None = None
    state: InvocationPhase
    attempt: int = Field(default=1, ge=1, le=1_000)
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    reserved_usage: UsageVector = Field(default_factory=UsageVector)
    committed_usage: UsageVector = Field(default_factory=UsageVector)
    result_payload: dict[str, Any] | None = None
    result_payload_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    failure_code: str | None = Field(default=None, max_length=128)
    failure_detail: str | None = Field(default=None, max_length=2_000)

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL_PHASES

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms cannot precede created_at_ms")
        if self.parent_invocation_id == self.invocation_id:
            raise ValueError("invocation cannot be its own retry parent")
        self._validate_target_identity()
        self._validate_state_shape()
        return self

    def _validate_target_identity(self) -> None:
        if self.kind == InvocationKind.MODEL:
            if self.provider_id is None or self.model_id is None:
                raise ValueError("model invocation requires provider_id and model_id")
            if self.tool_id is not None or self.connector_id is not None:
                raise ValueError("model invocation cannot carry tool identity")
        elif self.kind == InvocationKind.TOOL:
            if self.tool_id is None or self.connector_id is None:
                raise ValueError("tool invocation requires tool_id and connector_id")
            if self.provider_id is not None or self.model_id is not None:
                raise ValueError("tool invocation cannot carry model identity")
        elif any(
            value is not None
            for value in (
                self.provider_id,
                self.model_id,
                self.tool_id,
                self.connector_id,
            )
        ):
            raise ValueError("specialist invocation cannot carry model or tool identity")

    def _validate_state_shape(self) -> None:
        if self.state == InvocationPhase.PENDING:
            self._require_no_usage_or_terminal_payload()
            return
        if self.state == InvocationPhase.RESERVED:
            if self.reserved_usage == _ZERO_USAGE:
                raise ValueError("reserved invocation requires non-zero reserved usage")
            if self.committed_usage != _ZERO_USAGE:
                raise ValueError("reserved invocation cannot contain committed usage")
            self._require_no_result_or_failure()
            return
        if self.reserved_usage != _ZERO_USAGE:
            raise ValueError("terminal invocation cannot retain reserved usage")
        if self.state == InvocationPhase.COMPLETED:
            if self.result_payload is None or self.result_payload_sha256 is None:
                raise ValueError("completed invocation requires result payload and hash")
            if self.failure_code is not None or self.failure_detail is not None:
                raise ValueError("completed invocation cannot contain failure metadata")
            if canonical_fingerprint(self.result_payload) != self.result_payload_sha256:
                raise ValueError("result_payload_sha256 does not match result payload")
            if canonical_size_bytes(self.result_payload) > MAX_INVOCATION_RESULT_BYTES:
                raise ValueError("invocation result exceeds durable payload limit")
            return
        if self.result_payload is not None or self.result_payload_sha256 is not None:
            raise ValueError("non-completed invocation cannot contain result payload")
        if self.failure_code is None:
            raise ValueError("terminal non-completed invocation requires failure_code")
        if (
            self.state == InvocationPhase.UNKNOWN_SIDE_EFFECT
            and self.effect != InvocationEffect.MUTATION
        ):
            raise ValueError("unknown_side_effect requires a mutation invocation")
        if (
            self.effect == InvocationEffect.MUTATION
            and self.state == InvocationPhase.UNKNOWN
        ):
            raise ValueError("uncertain mutation must use unknown_side_effect")

    def _require_no_usage_or_terminal_payload(self) -> None:
        if self.reserved_usage != _ZERO_USAGE or self.committed_usage != _ZERO_USAGE:
            raise ValueError("pending invocation cannot contain usage")
        self._require_no_result_or_failure()

    def _require_no_result_or_failure(self) -> None:
        if self.result_payload is not None or self.result_payload_sha256 is not None:
            raise ValueError("non-terminal invocation cannot contain result payload")
        if self.failure_code is not None or self.failure_detail is not None:
            raise ValueError("non-terminal invocation cannot contain failure metadata")


class InvocationStart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: InvocationStartKind
    record: InvocationRecord


class InvocationStore(Protocol):
    def begin(
        self,
        *,
        invocation_id: UUID,
        request_id: UUID,
        agent_id: str,
        agent_version: str,
        operation: str,
        input_fingerprint: str,
        kind: InvocationKind = InvocationKind.SPECIALIST,
        effect: InvocationEffect = InvocationEffect.READ_ONLY,
        provider_id: str | None = None,
        model_id: str | None = None,
        tool_id: str | None = None,
        connector_id: str | None = None,
        parent_invocation_id: UUID | None = None,
        attempt: int = 1,
    ) -> InvocationStart: ...

    def reserve(
        self,
        *,
        invocation_id: UUID,
        usage: UsageVector,
    ) -> InvocationRecord: ...

    def complete(
        self,
        *,
        invocation_id: UUID,
        result_payload: dict[str, Any],
        committed_usage: UsageVector = UsageVector(),
    ) -> InvocationRecord: ...

    def fail(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
        committed_usage: UsageVector | None = None,
    ) -> InvocationRecord: ...

    def mark_unknown(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> InvocationRecord: ...

    def cancel(self, invocation_id: UUID) -> InvocationRecord: ...

    def expire(self, invocation_id: UUID) -> InvocationRecord: ...

    def get(self, invocation_id: UUID) -> InvocationRecord: ...

    def load(self) -> list[InvocationRecord]: ...

    def clear(self) -> None: ...

    def close(self) -> None: ...


class InMemoryInvocationStore:
    """Strict process-local implementation of the durable invocation contract."""

    def __init__(
        self,
        *,
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )
        self._lock = RLock()
        self._records: dict[UUID, InvocationRecord] = {}
        self._closed = False

    def begin(
        self,
        *,
        invocation_id: UUID,
        request_id: UUID,
        agent_id: str,
        agent_version: str,
        operation: str,
        input_fingerprint: str,
        kind: InvocationKind = InvocationKind.SPECIALIST,
        effect: InvocationEffect = InvocationEffect.READ_ONLY,
        provider_id: str | None = None,
        model_id: str | None = None,
        tool_id: str | None = None,
        connector_id: str | None = None,
        parent_invocation_id: UUID | None = None,
        attempt: int = 1,
    ) -> InvocationStart:
        with self._lock:
            self._require_open_locked()
            existing = self._records.get(invocation_id)
            if existing is not None:
                require_same_invocation_identity(
                    existing=existing,
                    request_id=request_id,
                    agent_id=agent_id,
                    agent_version=agent_version,
                    operation=operation,
                    input_fingerprint=input_fingerprint,
                    kind=kind,
                    effect=effect,
                    provider_id=provider_id,
                    model_id=model_id,
                    tool_id=tool_id,
                    connector_id=connector_id,
                    parent_invocation_id=parent_invocation_id,
                    attempt=attempt,
                )
                return InvocationStart(
                    kind=start_kind_for_record(existing),
                    record=existing,
                )

            now = self._now_ms()
            record = InvocationRecord(
                invocation_id=invocation_id,
                request_id=request_id,
                agent_id=agent_id,
                agent_version=agent_version,
                operation=operation,
                input_fingerprint=input_fingerprint,
                kind=kind,
                effect=effect,
                provider_id=provider_id,
                model_id=model_id,
                tool_id=tool_id,
                connector_id=connector_id,
                parent_invocation_id=parent_invocation_id,
                state=InvocationPhase.PENDING,
                attempt=attempt,
                created_at_ms=now,
                updated_at_ms=now,
            )
            self._records[invocation_id] = record
            return InvocationStart(kind=InvocationStartKind.NEW, record=record)

    def reserve(
        self,
        *,
        invocation_id: UUID,
        usage: UsageVector,
    ) -> InvocationRecord:
        if usage == _ZERO_USAGE:
            raise ValueError("invocation reservation usage cannot be zero")
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationPhase.RESERVED:
                if existing.reserved_usage != usage:
                    raise InvocationConflictError(
                        "invocation reservation was replayed with different usage"
                    )
                return existing
            if existing.state != InvocationPhase.PENDING:
                raise InvocationStateError(
                    f"cannot reserve invocation in state {existing.state.value}"
                )
            candidate = validated_record_copy(
                existing,
                state=InvocationPhase.RESERVED,
                reserved_usage=usage,
                updated_at_ms=self._next_time(existing.updated_at_ms),
            )
            self._records[invocation_id] = candidate
            return candidate

    def complete(
        self,
        *,
        invocation_id: UUID,
        result_payload: dict[str, Any],
        committed_usage: UsageVector = _ZERO_USAGE,
    ) -> InvocationRecord:
        result_hash = canonical_fingerprint(result_payload)
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationPhase.COMPLETED:
                if (
                    existing.result_payload != result_payload
                    or existing.committed_usage != committed_usage
                ):
                    raise InvocationConflictError(
                        "completed invocation was replayed with different result or usage"
                    )
                return existing
            if existing.state not in {
                InvocationPhase.PENDING,
                InvocationPhase.RESERVED,
            }:
                raise InvocationStateError(
                    f"cannot complete invocation in state {existing.state.value}"
                )
            candidate = validated_record_copy(
                existing,
                state=InvocationPhase.COMPLETED,
                reserved_usage=_ZERO_USAGE,
                committed_usage=committed_usage,
                result_payload=result_payload,
                result_payload_sha256=result_hash,
                failure_code=None,
                failure_detail=None,
                updated_at_ms=self._next_time(existing.updated_at_ms),
            )
            self._records[invocation_id] = candidate
            return candidate

    def fail(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
        committed_usage: UsageVector | None = None,
    ) -> InvocationRecord:
        normalized_code = failure_code.strip()[:128]
        if not normalized_code:
            raise ValueError("failure_code cannot be empty")
        normalized_detail = failure_detail.strip()[:2_000]
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            usage = _terminal_usage(existing, committed_usage)
            if existing.state == InvocationPhase.FAILED:
                if (
                    existing.failure_code != normalized_code
                    or existing.failure_detail != normalized_detail
                    or existing.committed_usage != usage
                ):
                    raise InvocationConflictError(
                        "failed invocation was replayed with different terminal content"
                    )
                return existing
            if existing.state not in {
                InvocationPhase.PENDING,
                InvocationPhase.RESERVED,
            }:
                raise InvocationStateError(
                    f"cannot fail invocation in state {existing.state.value}"
                )
            candidate = validated_record_copy(
                existing,
                state=InvocationPhase.FAILED,
                reserved_usage=_ZERO_USAGE,
                committed_usage=usage,
                failure_code=normalized_code,
                failure_detail=normalized_detail or None,
                updated_at_ms=self._next_time(existing.updated_at_ms),
            )
            self._records[invocation_id] = candidate
            return candidate

    def mark_unknown(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state in {
                InvocationPhase.UNKNOWN,
                InvocationPhase.UNKNOWN_SIDE_EFFECT,
            }:
                return existing
            if existing.state not in {
                InvocationPhase.PENDING,
                InvocationPhase.RESERVED,
            }:
                raise InvocationStateError(
                    f"cannot mark invocation unknown in state {existing.state.value}"
                )
            candidate = unknown_record(
                existing,
                failure_code=failure_code,
                failure_detail=failure_detail,
                updated_at_ms=self._next_time(existing.updated_at_ms),
            )
            self._records[invocation_id] = candidate
            return candidate

    def cancel(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationPhase.CANCELLED:
                return existing
            if existing.state == InvocationPhase.PENDING:
                candidate = validated_record_copy(
                    existing,
                    state=InvocationPhase.CANCELLED,
                    failure_code="cancelled",
                    failure_detail="invocation cancelled before external reservation",
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            elif existing.state == InvocationPhase.RESERVED:
                candidate = unknown_record(
                    existing,
                    failure_code="cancelled_after_reservation",
                    failure_detail=(
                        "invocation cancelled after external-call budget reservation; "
                        "completion is uncertain"
                    ),
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            else:
                raise InvocationStateError(
                    f"cannot cancel invocation in state {existing.state.value}"
                )
            self._records[invocation_id] = candidate
            return candidate

    def expire(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationPhase.EXPIRED:
                return existing
            if existing.state == InvocationPhase.PENDING:
                candidate = validated_record_copy(
                    existing,
                    state=InvocationPhase.EXPIRED,
                    failure_code="expired",
                    failure_detail="invocation expired before external reservation",
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            elif existing.state == InvocationPhase.RESERVED:
                candidate = unknown_record(
                    existing,
                    failure_code="expired_after_reservation",
                    failure_detail=(
                        "invocation expired after external-call budget reservation; "
                        "completion is uncertain"
                    ),
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            else:
                raise InvocationStateError(
                    f"cannot expire invocation in state {existing.state.value}"
                )
            self._records[invocation_id] = candidate
            return candidate

    def get(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            return self._require_record_locked(invocation_id)

    def load(self) -> list[InvocationRecord]:
        with self._lock:
            self._require_open_locked()
            return sorted(
                self._records.values(),
                key=lambda record: (record.created_at_ms, str(record.invocation_id)),
            )

    def clear(self) -> None:
        with self._lock:
            self._require_open_locked()
            self._records.clear()

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _require_record_locked(self, invocation_id: UUID) -> InvocationRecord:
        self._require_open_locked()
        record = self._records.get(invocation_id)
        if record is None:
            raise InvocationNotFoundError(f"invocation {invocation_id} does not exist")
        return record

    def _require_open_locked(self) -> None:
        if self._closed:
            raise InvocationStoreClosedError("invocation store is closed")

    def _next_time(self, previous_updated_at_ms: int) -> int:
        return max(previous_updated_at_ms, self._now_ms())

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))


def require_same_invocation_identity(
    *,
    existing: InvocationRecord,
    request_id: UUID,
    agent_id: str,
    agent_version: str,
    operation: str,
    input_fingerprint: str,
    kind: InvocationKind,
    effect: InvocationEffect,
    provider_id: str | None,
    model_id: str | None,
    tool_id: str | None,
    connector_id: str | None,
    parent_invocation_id: UUID | None,
    attempt: int,
) -> None:
    identity = (
        existing.request_id,
        existing.agent_id,
        existing.agent_version,
        existing.operation,
        existing.input_fingerprint,
        existing.kind,
        existing.effect,
        existing.provider_id,
        existing.model_id,
        existing.tool_id,
        existing.connector_id,
        existing.parent_invocation_id,
        existing.attempt,
    )
    incoming = (
        request_id,
        agent_id,
        agent_version,
        operation,
        input_fingerprint,
        kind,
        effect,
        provider_id,
        model_id,
        tool_id,
        connector_id,
        parent_invocation_id,
        attempt,
    )
    if identity != incoming:
        raise InvocationConflictError(
            "invocation_id was reused with different immutable identity"
        )


def start_kind_for_record(record: InvocationRecord) -> InvocationStartKind:
    if record.state == InvocationPhase.COMPLETED:
        return InvocationStartKind.REPLAY
    if record.state in {InvocationPhase.PENDING, InvocationPhase.RESERVED}:
        return InvocationStartKind.IN_PROGRESS
    return InvocationStartKind.TERMINAL


def unknown_record(
    record: InvocationRecord,
    *,
    failure_code: str,
    failure_detail: str,
    updated_at_ms: int,
) -> InvocationRecord:
    phase = (
        InvocationPhase.UNKNOWN_SIDE_EFFECT
        if record.effect == InvocationEffect.MUTATION
        else InvocationPhase.UNKNOWN
    )
    return validated_record_copy(
        record,
        state=phase,
        reserved_usage=_ZERO_USAGE,
        committed_usage=record.committed_usage.plus(record.reserved_usage),
        failure_code=failure_code.strip()[:128] or "unknown",
        failure_detail=failure_detail.strip()[:2_000] or None,
        updated_at_ms=updated_at_ms,
    )


def validated_record_copy(
    record: InvocationRecord,
    **updates: Any,
) -> InvocationRecord:
    candidate = record.model_copy(update=updates)
    return InvocationRecord.model_validate(candidate.model_dump(mode="json"))


def _terminal_usage(
    record: InvocationRecord,
    committed_usage: UsageVector | None,
) -> UsageVector:
    if committed_usage is not None:
        return committed_usage
    if record.state == InvocationPhase.RESERVED:
        return record.reserved_usage
    return record.committed_usage


def stable_invocation_id(
    *,
    request_id: UUID,
    agent_id: str,
    agent_version: str,
    operation: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"simorgh:{request_id}:{agent_id}:{agent_version}:{operation}",
    )


def canonical_json(value: BaseModel | dict[str, Any]) -> str:
    payload: Any = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_size_bytes(value: BaseModel | dict[str, Any]) -> int:
    return len(canonical_json(value).encode())


def canonical_fingerprint(value: BaseModel | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()
