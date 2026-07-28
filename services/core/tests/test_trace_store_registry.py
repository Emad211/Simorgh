from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.trace_store import (
    InMemoryTraceStore,
    TraceStoreClosedError,
)
from simorgh_core.agents.trace_store_registry import TraceStoreRegistry


def test_registry_closes_replaced_store_and_exposes_new_authority() -> None:
    registry = TraceStoreRegistry()
    previous = registry.current()
    replacement = InMemoryTraceStore()

    registry.configure(replacement)

    assert registry.current() is replacement
    with pytest.raises(TraceStoreClosedError, match="closed"):
        previous.view(uuid4())


def test_registry_reset_closes_durable_authority_and_returns_memory_store() -> None:
    registry = TraceStoreRegistry()
    configured = InMemoryTraceStore()
    registry.configure(configured)

    registry.reset_to_memory()

    assert isinstance(registry.current(), InMemoryTraceStore)
    assert registry.current() is not configured
    with pytest.raises(TraceStoreClosedError, match="closed"):
        configured.load()


def test_configuring_same_store_is_idempotent() -> None:
    registry = TraceStoreRegistry()
    store = InMemoryTraceStore()
    registry.configure(store)

    registry.configure(store)

    assert registry.current() is store
    assert store.load() == []
