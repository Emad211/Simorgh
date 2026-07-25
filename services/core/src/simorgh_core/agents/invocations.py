from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.contracts import InvocationState


class InvocationStoreError(RuntimeError):
    """Base class for deterministic invocation-store failures."""


class InvocationConflictError(InvocationStoreError):
    pass


class InvocationNotFoundError(InvocationStoreError):
    pass


class InvocationStateError(InvocationStoreError):
    pass


class InvocationStartKind(StrEnum):
    NEW = "new"
    REPLAY = "replay"
    IN_PROGRESS = "in_progress"
    TERMINAL = "terminal"


class InvocationRecord(BaseModel):
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
    state: InvocationState
    attempt: int = Field(default=1, ge=1, le=1_000)
    result_payload: dict[str, Any] | None = None
    failure_code: str | None = Field(default=None, max_length=128)
    failure_detail: str | None = Field(default=None, max_length=2_000)


class InvocationStart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: InvocationStartKind
    record: InvocationRecord


class InMemoryInvocationStore:
    """Strict process-local idempotency foundation for routing, models, and tools."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[UUID, InvocationRecord] = {}

    def begin(
        self,
        *,
        invocation_id: UUID,
        request_id: UUID,
        agent_id: str,
        agent_version: str,
        operation: str,
        input_fingerprint: str,
    ) -> InvocationStart:
        with self._lock:
            existing = self._records.get(invocation_id)
            if existing is None:
                record = InvocationRecord(
                    invocation_id=invocation_id,
                    request_id=request_id,
                    agent_id=agent_id,
                    agent_version=agent_version,
                    operation=operation,
                    input_fingerprint=input_fingerprint,
                    state=InvocationState.PENDING,
                )
                self._records[invocation_id] = record
                return InvocationStart(kind=InvocationStartKind.NEW, record=record)

            self._require_same_identity(
                existing=existing,
                request_id=request_id,
                agent_id=agent_id,
                agent_version=agent_version,
                operation=operation,
                input_fingerprint=input_fingerprint,
            )
            kind = {
                InvocationState.PENDING: InvocationStartKind.IN_PROGRESS,
                InvocationState.COMPLETED: InvocationStartKind.REPLAY,
                InvocationState.FAILED: InvocationStartKind.TERMINAL,
                InvocationState.CANCELLED: InvocationStartKind.TERMINAL,
                InvocationState.EXPIRED: InvocationStartKind.TERMINAL,
            }[existing.state]
            return InvocationStart(kind=kind, record=existing)

    def complete(
        self,
        *,
        invocation_id: UUID,
        result_payload: dict[str, Any],
    ) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationState.COMPLETED:
                if existing.result_payload != result_payload:
                    raise InvocationConflictError(
                        "completed invocation was replayed with different result content"
                    )
                return existing
            if existing.state != InvocationState.PENDING:
                raise InvocationStateError(
                    f"cannot complete invocation in state {existing.state.value}"
                )
            completed = existing.model_copy(
                update={
                    "state": InvocationState.COMPLETED,
                    "result_payload": result_payload,
                    "failure_code": None,
                    "failure_detail": None,
                }
            )
            validated = InvocationRecord.model_validate(completed.model_dump(mode="json"))
            self._records[invocation_id] = validated
            return validated

    def fail(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state != InvocationState.PENDING:
                raise InvocationStateError(
                    f"cannot fail invocation in state {existing.state.value}"
                )
            failed = existing.model_copy(
                update={
                    "state": InvocationState.FAILED,
                    "failure_code": failure_code[:128],
                    "failure_detail": failure_detail[:2_000],
                }
            )
            validated = InvocationRecord.model_validate(failed.model_dump(mode="json"))
            self._records[invocation_id] = validated
            return validated

    def cancel(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationState.CANCELLED:
                return existing
            if existing.state != InvocationState.PENDING:
                raise InvocationStateError(
                    f"cannot cancel invocation in state {existing.state.value}"
                )
            cancelled = existing.model_copy(update={"state": InvocationState.CANCELLED})
            validated = InvocationRecord.model_validate(cancelled.model_dump(mode="json"))
            self._records[invocation_id] = validated
            return validated

    def expire(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationState.EXPIRED:
                return existing
            if existing.state != InvocationState.PENDING:
                raise InvocationStateError(
                    f"cannot expire invocation in state {existing.state.value}"
                )
            expired = existing.model_copy(update={"state": InvocationState.EXPIRED})
            validated = InvocationRecord.model_validate(expired.model_dump(mode="json"))
            self._records[invocation_id] = validated
            return validated

    def get(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            return self._require_record_locked(invocation_id)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def _require_record_locked(self, invocation_id: UUID) -> InvocationRecord:
        record = self._records.get(invocation_id)
        if record is None:
            raise InvocationNotFoundError(f"invocation {invocation_id} does not exist")
        return record

    @staticmethod
    def _require_same_identity(
        *,
        existing: InvocationRecord,
        request_id: UUID,
        agent_id: str,
        agent_version: str,
        operation: str,
        input_fingerprint: str,
    ) -> None:
        identity = (
            existing.request_id,
            existing.agent_id,
            existing.agent_version,
            existing.operation,
            existing.input_fingerprint,
        )
        incoming = (
            request_id,
            agent_id,
            agent_version,
            operation,
            input_fingerprint,
        )
        if identity != incoming:
            raise InvocationConflictError(
                "invocation_id was reused with different request, agent, operation, or input"
            )


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


def canonical_fingerprint(value: BaseModel | dict[str, Any]) -> str:
    payload: Any = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
