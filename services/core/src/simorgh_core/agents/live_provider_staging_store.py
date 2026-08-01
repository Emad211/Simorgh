from __future__ import annotations

import threading
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from simorgh_core.agents.live_provider_staging_contracts import (
    LiveProviderStagingResult,
)


class LiveProviderStagingStoreError(RuntimeError):
    """Base class for immutable staging-result store failures."""


class LiveProviderStagingStoreConflictError(LiveProviderStagingStoreError):
    pass


class LiveProviderStagingStoreNotFoundError(LiveProviderStagingStoreError):
    pass


class LiveProviderStagingStoreClosedError(LiveProviderStagingStoreError):
    pass


class LiveProviderStagingClaimKind(StrEnum):
    NEW = "new"
    REPLAY = "replay"


class LiveProviderStagingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: LiveProviderStagingClaimKind
    record: LiveProviderStagingResult


class LiveProviderStagingResultStore(Protocol):
    def claim(self, record: LiveProviderStagingResult) -> LiveProviderStagingClaim: ...

    def get(self, staging_run_id: UUID) -> LiveProviderStagingResult: ...

    def get_by_invocation(self, invocation_id: UUID) -> LiveProviderStagingResult: ...

    def load(self) -> list[LiveProviderStagingResult]: ...

    def close(self) -> None: ...


class InMemoryLiveProviderStagingResultStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[UUID, LiveProviderStagingResult] = {}
        self._by_invocation: dict[UUID, UUID] = {}
        self._closed = False

    def claim(self, record: LiveProviderStagingResult) -> LiveProviderStagingClaim:
        validated = _validated_fresh_result(record)
        with self._lock:
            self._require_open_locked()
            existing = self._records.get(validated.staging_run_id)
            existing_run_id = self._by_invocation.get(validated.invocation_id)
            if existing is None and existing_run_id is not None:
                existing = self._records[existing_run_id]
            if existing is not None:
                _require_same_record(existing, validated)
                return LiveProviderStagingClaim(
                    kind=LiveProviderStagingClaimKind.REPLAY,
                    record=existing,
                )
            self._records[validated.staging_run_id] = validated
            self._by_invocation[validated.invocation_id] = validated.staging_run_id
            return LiveProviderStagingClaim(
                kind=LiveProviderStagingClaimKind.NEW,
                record=validated,
            )

    def get(self, staging_run_id: UUID) -> LiveProviderStagingResult:
        with self._lock:
            self._require_open_locked()
            record = self._records.get(staging_run_id)
            if record is None:
                raise LiveProviderStagingStoreNotFoundError(
                    "live-provider staging result does not exist"
                )
            return record

    def get_by_invocation(self, invocation_id: UUID) -> LiveProviderStagingResult:
        with self._lock:
            self._require_open_locked()
            staging_run_id = self._by_invocation.get(invocation_id)
            if staging_run_id is None:
                raise LiveProviderStagingStoreNotFoundError(
                    "staging invocation has no durable result"
                )
            return self._records[staging_run_id]

    def load(self) -> list[LiveProviderStagingResult]:
        with self._lock:
            self._require_open_locked()
            return sorted(
                self._records.values(),
                key=lambda record: (
                    record.completed_at_ms,
                    str(record.staging_run_id),
                ),
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _require_open_locked(self) -> None:
        if self._closed:
            raise LiveProviderStagingStoreClosedError(
                "live-provider staging result store is closed"
            )


def _validated_fresh_result(
    record: LiveProviderStagingResult,
) -> LiveProviderStagingResult:
    payload = record.model_dump(mode="json")
    payload["replayed"] = False
    return LiveProviderStagingResult.model_validate(payload)


def _require_same_record(
    existing: LiveProviderStagingResult,
    candidate: LiveProviderStagingResult,
) -> None:
    if existing.canonical_sha256 != candidate.canonical_sha256:
        raise LiveProviderStagingStoreConflictError(
            "changed staging content conflicts with immutable run identity"
        )
    if (
        existing.request_id != candidate.request_id
        or existing.invocation_id != candidate.invocation_id
    ):
        raise LiveProviderStagingStoreConflictError(
            "staging run identity was transferred across durable authority"
        )


__all__ = [
    "InMemoryLiveProviderStagingResultStore",
    "LiveProviderStagingClaim",
    "LiveProviderStagingClaimKind",
    "LiveProviderStagingResultStore",
    "LiveProviderStagingStoreClosedError",
    "LiveProviderStagingStoreConflictError",
    "LiveProviderStagingStoreError",
    "LiveProviderStagingStoreNotFoundError",
]
