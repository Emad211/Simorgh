from __future__ import annotations

from uuid import UUID

import pytest

from simorgh_core.agents.trace_contracts import (
    TraceEventCandidate,
    TraceEventRecord,
    TraceView,
)
from simorgh_core.agents.trace_store import (
    InMemoryTraceStore,
    TraceClaim,
    TraceStoreError,
)
from simorgh_core.agents.trace_store_registry import TraceStoreRegistry


class _FailingLoadStore:
    def append(
        self,
        candidate: TraceEventCandidate,
        *,
        ingested_at_ms: int,
    ) -> TraceClaim:
        del candidate, ingested_at_ms
        raise AssertionError("append must not run")

    def get_event(self, event_id: UUID) -> TraceEventRecord:
        del event_id
        raise AssertionError("get_event must not run")

    def view(self, request_id: UUID) -> TraceView:
        del request_id
        raise AssertionError("view must not run")

    def load(self) -> list[TraceEventRecord]:
        raise TraceStoreError("PRIVATE_TRACE_DATABASE_FAILURE")

    def close(self) -> None:
        pass


def test_registry_validates_candidate_before_replacing_current_authority() -> None:
    registry = TraceStoreRegistry()
    current = registry.current()

    with pytest.raises(TraceStoreError, match="PRIVATE_TRACE_DATABASE_FAILURE"):
        registry.configure(_FailingLoadStore())

    assert registry.current() is current
    assert isinstance(current, InMemoryTraceStore)
    assert current.load() == []
