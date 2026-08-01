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


class InMemoryLiveProviderStagingResultStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[UUID, LiveProviderStagingResult] = {}

    def claim(self, record: LiveProviderStagingResult) -> LiveProviderStagingClaim:
        validated = LiveProviderStagingResult.model_validate(
            record.model_dump(mode="json")
        )
        with self._lock:
            existing = self._records.get(validated.staging_run_id)
            if existing is not None:
                _require_same_record(existing, validated)
                return LiveProviderStagingClaim(
                    kind=LiveProviderStagingClaimKind.REPLAY,
                    record=existing,
                )
            self._records[validated.staging_run_id] = validated
            return LiveProviderStagingClaim(
                kind=LiveProviderStagingClaimKind.NEW,
                record=validated,
            )

    def get(self, staging_run_id: UUID) -> LiveProviderStagingResult:
        with self._lock:
            record = self._records.get(staging_run_id)
            if record is None:
                raise LiveProviderStagingStoreNotFoundError(
                    "live-provider staging result does not exist"
                )
            return record


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
    "LiveProviderStagingStoreConflictError",
    "LiveProviderStagingStoreError",
    "LiveProviderStagingStoreNotFoundError",
]
