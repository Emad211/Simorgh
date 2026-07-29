from __future__ import annotations

from typing import Any
from uuid import UUID

from simorgh_core.agents.cancellation_contracts import (
    InvocationCancellationFence,
    TaskCancellationRequest,
)
from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    InvocationRecord,
    InvocationStart,
    InvocationStore,
    InvocationStoreError,
)
from simorgh_core.agents.trace_projection import (
    request_trace_projector_registry,
)

_ZERO_USAGE = UsageVector()


class InvocationTraceProjectionError(InvocationStoreError):
    """Invocation authority committed, but its trace projection failed."""


class TraceProjectingInvocationStore:
    """Delegate invocation authority and project only safe durable transitions."""

    def __init__(self, store: InvocationStore) -> None:
        self._store = store

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
        cancellation_owner_id: UUID | None = None,
        attempt: int = 1,
    ) -> InvocationStart:
        started = self._store.begin(
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
            cancellation_owner_id=cancellation_owner_id,
            attempt=attempt,
        )
        self._project(started.record.request_id)
        return started

    def reserve(
        self,
        *,
        invocation_id: UUID,
        usage: UsageVector,
    ) -> InvocationRecord:
        return self._store.reserve(invocation_id=invocation_id, usage=usage)

    def complete(
        self,
        *,
        invocation_id: UUID,
        result_payload: dict[str, Any],
        committed_usage: UsageVector = _ZERO_USAGE,
    ) -> InvocationRecord:
        record = self._store.complete(
            invocation_id=invocation_id,
            result_payload=result_payload,
            committed_usage=committed_usage,
        )
        self._project(record.request_id)
        return record

    def fail(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
        committed_usage: UsageVector | None = None,
    ) -> InvocationRecord:
        record = self._store.fail(
            invocation_id=invocation_id,
            failure_code=failure_code,
            failure_detail=failure_detail,
            committed_usage=committed_usage,
        )
        self._project(record.request_id)
        return record

    def mark_unknown(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> InvocationRecord:
        record = self._store.mark_unknown(
            invocation_id=invocation_id,
            failure_code=failure_code,
            failure_detail=failure_detail,
        )
        self._project(record.request_id)
        return record

    def cancel(self, invocation_id: UUID) -> InvocationRecord:
        record = self._store.cancel(invocation_id)
        self._project(record.request_id)
        return record

    def expire(self, invocation_id: UUID) -> InvocationRecord:
        record = self._store.expire(invocation_id)
        self._project(record.request_id)
        return record

    def get(self, invocation_id: UUID) -> InvocationRecord:
        record = self._store.get(invocation_id)
        self._project(record.request_id)
        return record

    def load(self) -> list[InvocationRecord]:
        return self._store.load()

    def list_owned(
        self,
        *,
        request_id: UUID,
        terminal: bool | None = None,
    ) -> tuple[InvocationRecord, ...]:
        return self._store.list_owned(request_id=request_id, terminal=terminal)

    def accept_cancellation(
        self,
        request: TaskCancellationRequest,
    ) -> InvocationCancellationFence:
        return self._store.accept_cancellation(request)

    def get_cancellation_fence(
        self,
        request_id: UUID,
    ) -> InvocationCancellationFence | None:
        return self._store.get_cancellation_fence(request_id)

    def settle_pending_cancellation(
        self,
        request_id: UUID,
    ) -> tuple[InvocationRecord, ...]:
        return self._store.settle_pending_cancellation(request_id)

    def settle_reserved_cancellation(
        self,
        request_id: UUID,
        *,
        proven_not_entered: frozenset[UUID] = frozenset(),
    ) -> tuple[InvocationRecord, ...]:
        return self._store.settle_reserved_cancellation(
            request_id,
            proven_not_entered=proven_not_entered,
        )

    def settle_cancellation(
        self,
        request_id: UUID,
    ) -> tuple[InvocationRecord, ...]:
        return self._store.settle_cancellation(request_id)

    def clear(self) -> None:
        self._store.clear()

    def close(self) -> None:
        self._store.close()

    @staticmethod
    def _project(request_id: UUID) -> None:
        try:
            request_trace_projector_registry.current().project_request(request_id)
        except Exception as exc:
            raise InvocationTraceProjectionError(
                "invocation authority committed but trace projection failed"
            ) from exc


__all__ = [
    "InvocationTraceProjectionError",
    "TraceProjectingInvocationStore",
]
