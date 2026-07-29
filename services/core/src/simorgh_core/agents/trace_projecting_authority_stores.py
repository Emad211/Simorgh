from __future__ import annotations

from uuid import UUID

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.context_store import (
    ContextClaim,
    ContextStore,
    ContextStoreError,
)
from simorgh_core.agents.result_authority import AuthoritativeSpecialistResult
from simorgh_core.agents.result_store import (
    ResultClaim,
    ResultStore,
    ResultStoreError,
)
from simorgh_core.agents.trace_projection import (
    request_trace_projector_registry,
)


class ContextTraceProjectionError(ContextStoreError):
    """Context authority committed, but its trace projection failed."""


class ResultTraceProjectionError(ResultStoreError):
    """Result authority committed, but its trace projection failed."""


class TraceProjectingContextStore:
    """Delegate immutable Context authority and project claim/replay outcomes."""

    def __init__(self, store: ContextStore) -> None:
        self._store = store

    def claim(self, record: SpecialistContextBundle) -> ContextClaim:
        claim = self._store.claim(record)
        self._project(claim.record.request_id)
        return claim

    def get(self, context_bundle_id: UUID) -> SpecialistContextBundle:
        record = self._store.get(context_bundle_id)
        self._project(record.request_id)
        return record

    def get_by_invocation(self, invocation_id: UUID) -> SpecialistContextBundle:
        record = self._store.get_by_invocation(invocation_id)
        self._project(record.request_id)
        return record

    def load(self) -> list[SpecialistContextBundle]:
        return self._store.load()

    def close(self) -> None:
        self._store.close()

    @staticmethod
    def _project(request_id: UUID) -> None:
        try:
            request_trace_projector_registry.current().project_request(request_id)
        except Exception as exc:
            raise ContextTraceProjectionError(
                "context authority committed but trace projection failed"
            ) from exc


class TraceProjectingResultStore:
    """Delegate immutable Result authority and project claim/replay outcomes."""

    def __init__(self, store: ResultStore) -> None:
        self._store = store

    def claim(self, record: AuthoritativeSpecialistResult) -> ResultClaim:
        claim = self._store.claim(record)
        self._project(claim.record.request_id)
        return claim

    def get(self, result_id: UUID) -> AuthoritativeSpecialistResult:
        record = self._store.get(result_id)
        self._project(record.request_id)
        return record

    def get_by_invocation(self, invocation_id: UUID) -> AuthoritativeSpecialistResult:
        record = self._store.get_by_invocation(invocation_id)
        self._project(record.request_id)
        return record

    def load(self) -> list[AuthoritativeSpecialistResult]:
        return self._store.load()

    def close(self) -> None:
        self._store.close()

    @staticmethod
    def _project(request_id: UUID) -> None:
        try:
            request_trace_projector_registry.current().project_request(request_id)
        except Exception as exc:
            raise ResultTraceProjectionError(
                "result authority committed but trace projection failed"
            ) from exc


__all__ = [
    "ContextTraceProjectionError",
    "ResultTraceProjectionError",
    "TraceProjectingContextStore",
    "TraceProjectingResultStore",
]
