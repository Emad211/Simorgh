from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Protocol, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CANCELLATION_CONTRACT_VERSION: Literal["1.0"] = "1.0"
_REASON_CODE_PATTERN = r"^[a-z][a-z0-9_.-]{0,127}$"
_RESOURCE_PATTERN = r"^[a-z][a-z0-9_.:-]{0,127}$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class CancellationContractError(RuntimeError):
    """Base class for deterministic cancellation-contract failures."""


class CancellationRequesterAuthority(StrEnum):
    OPERATOR = "operator"
    SYSTEM = "system"
    INTERNAL_CONTROL_PLANE = "internal_control_plane"


class CancellationDisposition(StrEnum):
    APPLIED = "applied"
    OBSERVED_TERMINAL = "observed_terminal"
    PARTIALLY_UNCERTAIN = "partially_uncertain"


class CancellationReplayDisposition(StrEnum):
    FRESH = "fresh"
    REPLAYED = "replayed"


class CancellationSignalDisposition(StrEnum):
    SIGNALLED = "signalled"
    ALREADY_SIGNALLED = "already_signalled"
    NOT_REGISTERED = "not_registered"
    LATE_REGISTRATION_BLOCKED = "late_registration_blocked"
    SIGNAL_FAILED = "signal_failed"


class AdapterCancellationDisposition(StrEnum):
    ACCEPTED = "accepted"
    ALREADY_TERMINAL = "already_terminal"
    NOT_SUPPORTED = "not_supported"
    NOT_FOUND = "not_found"
    PROVEN_NOT_ENTERED = "proven_not_entered"
    UNCERTAIN = "uncertain"


class TaskCancellationRequest(BaseModel):
    """Immutable operator/control-plane request accepted before propagation begins."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CANCELLATION_CONTRACT_VERSION
    request_id: UUID
    cancellation_id: UUID
    requested_at_ms: int = Field(ge=0)
    reason_code: str = Field(
        default="operator_requested",
        pattern=_REASON_CODE_PATTERN,
        max_length=128,
    )
    operator_reason: str | None = Field(default=None, max_length=1_000)
    requester_authority: CancellationRequesterAuthority
    observed_task_phase: str = Field(pattern=_RESOURCE_PATTERN, max_length=128)
    observed_task_version: int = Field(ge=0)

    @field_validator("operator_reason")
    @classmethod
    def sanitize_operator_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            return None
        return normalized[:1_000]

    @property
    def canonical_sha256(self) -> str:
        return canonical_cancellation_hash(self)


class InvocationOwnershipReference(BaseModel):
    """Bounded immutable ownership projection derived from invocation authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    request_id: UUID
    invocation_id: UUID
    kind: str = Field(pattern=_RESOURCE_PATTERN, max_length=128)
    effect: str = Field(pattern=_RESOURCE_PATTERN, max_length=128)
    state: str = Field(pattern=_RESOURCE_PATTERN, max_length=128)
    parent_invocation_id: UUID | None = None
    cancellation_owner_id: UUID | None = None
    created_at_ms: int = Field(ge=0)
    terminal: bool

    @model_validator(mode="after")
    def validate_parent(self) -> Self:
        if self.parent_invocation_id == self.invocation_id:
            raise ValueError("owned invocation cannot parent itself")
        return self


class InvocationCancellationFence(BaseModel):
    """Durable admission fence plus the exact ownership snapshot it captured."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CANCELLATION_CONTRACT_VERSION
    request: TaskCancellationRequest
    accepted_at_ms: int = Field(ge=0)
    owned_invocations: tuple[InvocationOwnershipReference, ...] = Field(
        default=(),
        max_length=100_000,
    )
    ownership_snapshot_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_HASH_PATTERN,
    )

    @property
    def request_id(self) -> UUID:
        return self.request.request_id

    @property
    def cancellation_id(self) -> UUID:
        return self.request.cancellation_id

    @model_validator(mode="after")
    def validate_fence(self) -> Self:
        if self.accepted_at_ms < self.request.requested_at_ms:
            raise ValueError("cancellation acceptance cannot precede request time")
        expected_order = tuple(
            sorted(
                self.owned_invocations,
                key=lambda item: (item.created_at_ms, str(item.invocation_id)),
            )
        )
        if expected_order != self.owned_invocations:
            raise ValueError("owned invocation snapshot must use deterministic order")
        if any(item.request_id != self.request_id for item in self.owned_invocations):
            raise ValueError("owned invocation snapshot contains another task")
        if (
            ownership_snapshot_sha256(self.owned_invocations)
            != self.ownership_snapshot_sha256
        ):
            raise ValueError("ownership snapshot hash does not match invocation identities")
        return self


class InvocationCancellationAcknowledgement(BaseModel):
    """Typed optional adapter/provider cancellation acknowledgement."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CANCELLATION_CONTRACT_VERSION
    invocation_id: UUID
    cancellation_owner_id: UUID | None = None
    disposition: AdapterCancellationDisposition
    acknowledged_at_ms: int = Field(ge=0)
    usage_reservation_released: bool = False

    @model_validator(mode="after")
    def validate_non_entry_proof(self) -> Self:
        if self.disposition == AdapterCancellationDisposition.PROVEN_NOT_ENTERED:
            if not self.usage_reservation_released:
                raise ValueError(
                    "proven_not_entered acknowledgement must release its reservation"
                )
        elif self.usage_reservation_released:
            raise ValueError(
                "only proven_not_entered acknowledgement may release reservation"
            )
        return self


class InvocationCancellationAdapter(Protocol):
    async def cancel(
        self,
        *,
        invocation_id: UUID,
        cancellation_owner_id: UUID | None,
    ) -> InvocationCancellationAcknowledgement: ...


class InvocationCancellationOutcome(BaseModel):
    """Privacy-safe per-invocation settlement projection."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    invocation_id: UUID
    prior_state: str = Field(pattern=_RESOURCE_PATTERN, max_length=128)
    final_state: str = Field(pattern=_RESOURCE_PATTERN, max_length=128)
    signal_disposition: CancellationSignalDisposition
    adapter_disposition: AdapterCancellationDisposition
    usage_sha256: str = Field(min_length=64, max_length=64, pattern=_HASH_PATTERN)


class TaskCancellationResult(BaseModel):
    """Immutable bounded result; raw task/tool/provider content is excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CANCELLATION_CONTRACT_VERSION
    request: TaskCancellationRequest
    accepted_at_ms: int = Field(ge=0)
    completed_at_ms: int = Field(ge=0)
    ownership_snapshot_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_HASH_PATTERN,
    )
    outcomes: tuple[InvocationCancellationOutcome, ...] = Field(
        default=(),
        max_length=100_000,
    )
    terminal_count: int = Field(ge=0)
    pending_cancelled_count: int = Field(ge=0)
    reserved_uncertain_count: int = Field(ge=0)
    signalled_count: int = Field(ge=0)
    disposition: CancellationDisposition
    audit_event_id: UUID
    replay: CancellationReplayDisposition = CancellationReplayDisposition.FRESH

    @property
    def replayed(self) -> bool:
        return self.replay == CancellationReplayDisposition.REPLAYED

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.completed_at_ms < self.accepted_at_ms:
            raise ValueError("cancellation completion cannot precede acceptance")
        if len(self.outcomes) != (
            self.terminal_count
            + self.pending_cancelled_count
            + self.reserved_uncertain_count
        ):
            raise ValueError("cancellation outcome counts do not cover ownership snapshot")
        actual_signalled = sum(
            outcome.signal_disposition == CancellationSignalDisposition.SIGNALLED
            for outcome in self.outcomes
        )
        if actual_signalled != self.signalled_count:
            raise ValueError("cancellation signalled count does not match outcomes")
        return self


def stable_cancellation_id(
    *,
    request_id: UUID,
    reason_code: str,
    operator_reason: str | None,
    requester_authority: CancellationRequesterAuthority,
) -> UUID:
    normalized_reason = " ".join((operator_reason or "").strip().split())
    return uuid5(
        NAMESPACE_URL,
        "simorgh-task-cancellation:"
        f"{request_id}:{reason_code}:{normalized_reason}:{requester_authority.value}",
    )


def stable_cancellation_audit_id(
    *,
    request_id: UUID,
    cancellation_id: UUID,
    ownership_snapshot_sha256: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "simorgh-cancellation-audit:"
        f"{request_id}:{cancellation_id}:{ownership_snapshot_sha256}",
    )


def ownership_snapshot_sha256(
    values: tuple[InvocationOwnershipReference, ...],
) -> str:
    payload = {
        "owned_invocations": [value.model_dump(mode="json") for value in values]
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_cancellation_hash(value: BaseModel | dict[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "AdapterCancellationDisposition",
    "CancellationDisposition",
    "CancellationReplayDisposition",
    "CancellationRequesterAuthority",
    "CancellationSignalDisposition",
    "InvocationCancellationAcknowledgement",
    "InvocationCancellationAdapter",
    "InvocationCancellationFence",
    "InvocationCancellationOutcome",
    "InvocationOwnershipReference",
    "TaskCancellationRequest",
    "TaskCancellationResult",
    "canonical_cancellation_hash",
    "ownership_snapshot_sha256",
    "stable_cancellation_audit_id",
    "stable_cancellation_id",
]
