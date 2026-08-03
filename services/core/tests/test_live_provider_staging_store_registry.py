from __future__ import annotations

import pytest

from simorgh_core.agents.live_provider_staging_contracts import (
    LiveProviderStagingResult,
)
from simorgh_core.agents.live_provider_staging_store import (
    InMemoryLiveProviderStagingResultStore,
    LiveProviderStagingStoreClosedError,
)
from simorgh_core.agents.live_provider_staging_store_registry import (
    LiveProviderStagingResultStoreRegistry,
)


class RecordingStore(InMemoryLiveProviderStagingResultStore):
    def __init__(self, *, fail_load: bool = False) -> None:
        super().__init__()
        self.fail_load = fail_load
        self.load_calls = 0
        self.closed = False

    def load(self) -> list[LiveProviderStagingResult]:
        self.load_calls += 1
        if self.fail_load:
            raise RuntimeError("candidate validation failed")
        return super().load()

    def close(self) -> None:
        self.closed = True
        super().close()


def test_registry_validates_before_replacing_healthy_authority() -> None:
    registry = LiveProviderStagingResultStoreRegistry()
    healthy = registry.current()
    candidate = RecordingStore(fail_load=True)

    with pytest.raises(RuntimeError, match="candidate validation failed"):
        registry.configure(candidate)

    assert registry.current() is healthy
    assert healthy.load() == []
    assert candidate.load_calls == 1
    assert not candidate.closed


def test_registry_closes_replaced_authority_after_successful_validation() -> None:
    registry = LiveProviderStagingResultStoreRegistry()
    previous = registry.current()
    candidate = RecordingStore()

    registry.configure(candidate)

    assert registry.current() is candidate
    assert candidate.load_calls == 1
    with pytest.raises(LiveProviderStagingStoreClosedError):
        previous.load()


def test_registry_reset_closes_current_and_installs_fresh_memory_store() -> None:
    registry = LiveProviderStagingResultStoreRegistry()
    candidate = RecordingStore()
    registry.configure(candidate)

    registry.reset_to_memory()

    assert candidate.closed
    assert isinstance(
        registry.current(),
        InMemoryLiveProviderStagingResultStore,
    )
    assert registry.current().load() == []
