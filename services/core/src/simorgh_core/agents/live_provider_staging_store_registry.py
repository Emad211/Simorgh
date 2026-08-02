from __future__ import annotations

import threading

from simorgh_core.agents.live_provider_staging_store import (
    InMemoryLiveProviderStagingResultStore,
    LiveProviderStagingResultStore,
)


class LiveProviderStagingResultStoreRegistry:
    """Process-local owner of the sanitized Phase 1.9 staging result authority."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: LiveProviderStagingResultStore = (
            InMemoryLiveProviderStagingResultStore()
        )

    def current(self) -> LiveProviderStagingResultStore:
        with self._lock:
            return self._store

    def configure(self, store: LiveProviderStagingResultStore) -> None:
        # Validate the complete candidate before replacing healthy authority.
        store.load()
        with self._lock:
            previous = self._store
            if previous is store:
                return
            self._store = store
        previous.close()

    def reset_to_memory(self) -> None:
        self.configure(InMemoryLiveProviderStagingResultStore())


live_provider_staging_result_store_registry = (
    LiveProviderStagingResultStoreRegistry()
)


__all__ = [
    "LiveProviderStagingResultStoreRegistry",
    "live_provider_staging_result_store_registry",
]
