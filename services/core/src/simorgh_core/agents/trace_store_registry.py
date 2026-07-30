from __future__ import annotations

import threading

from simorgh_core.agents.trace_store import InMemoryTraceStore, TraceStore


class TraceStoreRegistry:
    """Process-local owner of the active durable trace-store authority."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: TraceStore = InMemoryTraceStore()

    def current(self) -> TraceStore:
        with self._lock:
            return self._store

    def configure(self, store: TraceStore) -> None:
        # Validate the complete candidate before replacing healthy authority.
        store.load()
        with self._lock:
            previous = self._store
            if previous is store:
                return
            self._store = store
        previous.close()

    def reset_to_memory(self) -> None:
        self.configure(InMemoryTraceStore())


trace_store_registry = TraceStoreRegistry()


__all__ = ["TraceStoreRegistry", "trace_store_registry"]
