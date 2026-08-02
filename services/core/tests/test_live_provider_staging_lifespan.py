from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest
from fastapi.testclient import TestClient

import simorgh_core.app as app_module
from simorgh_core.agents.invocation_store import invocation_store_registry
from simorgh_core.agents.live_provider_staging_sqlite_store import (
    SQLiteLiveProviderStagingResultStore,
)
from simorgh_core.agents.live_provider_staging_store import (
    InMemoryLiveProviderStagingResultStore,
    LiveProviderStagingStoreClosedError,
)
from simorgh_core.agents.live_provider_staging_store_registry import (
    live_provider_staging_result_store_registry,
)
from simorgh_core.config import get_settings


def _configure_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    paths = {
        "SIMORGH_ACTION_JOURNAL_PATH": tmp_path / "actions.sqlite3",
        "SIMORGH_AGENT_TASK_STORE_PATH": tmp_path / "tasks.sqlite3",
        "SIMORGH_INVOCATION_STORE_PATH": tmp_path / "invocations.sqlite3",
        "SIMORGH_RESULT_STORE_PATH": tmp_path / "results.sqlite3",
        "SIMORGH_CONTEXT_STORE_PATH": tmp_path / "contexts.sqlite3",
        "SIMORGH_TRACE_STORE_PATH": tmp_path / "traces.sqlite3",
        "SIMORGH_LIVE_PROVIDER_STAGING_RESULT_STORE_PATH": (
            tmp_path / "live-provider-staging-results.sqlite3"
        ),
    }
    for name, path in paths.items():
        monkeypatch.setenv(name, str(path))
    get_settings.cache_clear()
    return paths["SIMORGH_LIVE_PROVIDER_STAGING_RESULT_STORE_PATH"]


def test_lifespan_publishes_and_closes_sqlite_staging_result_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    staging_path = _configure_environment(monkeypatch, tmp_path)

    with TestClient(app_module.app):
        started = live_provider_staging_result_store_registry.current()
        assert isinstance(started, SQLiteLiveProviderStagingResultStore)
        assert started.path == str(staging_path.resolve())
        assert started.load() == []

    assert isinstance(
        live_provider_staging_result_store_registry.current(),
        InMemoryLiveProviderStagingResultStore,
    )
    with pytest.raises(LiveProviderStagingStoreClosedError):
        started.load()

    reopened = SQLiteLiveProviderStagingResultStore(staging_path)
    reopened.close()
    get_settings.cache_clear()


def test_staging_registry_publication_failure_releases_process_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    staging_path = _configure_environment(monkeypatch, tmp_path)

    def reject_staging_authority(_store: object) -> NoReturn:
        raise RuntimeError("forced staging registry publication failure")

    monkeypatch.setattr(
        live_provider_staging_result_store_registry,
        "configure",
        reject_staging_authority,
    )

    with pytest.raises(
        RuntimeError,
        match="forced staging registry publication failure",
    ), TestClient(app_module.app):
        pass

    assert isinstance(
        live_provider_staging_result_store_registry.current(),
        InMemoryLiveProviderStagingResultStore,
    )
    reopened = SQLiteLiveProviderStagingResultStore(staging_path)
    reopened.close()
    get_settings.cache_clear()


def test_late_startup_failure_releases_staging_result_process_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    staging_path = _configure_environment(monkeypatch, tmp_path)

    def fail_projector_configuration(_projector: object) -> NoReturn:
        raise RuntimeError("forced projector configuration failure")

    monkeypatch.setattr(
        app_module.request_trace_projector_registry,
        "configure",
        fail_projector_configuration,
    )

    with pytest.raises(
        RuntimeError,
        match="forced projector configuration failure",
    ), TestClient(app_module.app):
        pass

    assert isinstance(
        live_provider_staging_result_store_registry.current(),
        InMemoryLiveProviderStagingResultStore,
    )
    reopened = SQLiteLiveProviderStagingResultStore(staging_path)
    reopened.close()
    get_settings.cache_clear()


def test_shutdown_resets_staging_authority_before_invocation_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    order: list[str] = []
    original_staging_reset = (
        live_provider_staging_result_store_registry.reset_to_memory
    )
    original_invocation_reset = invocation_store_registry.reset_to_memory

    def reset_staging() -> None:
        order.append("staging")
        original_staging_reset()

    def reset_invocations() -> None:
        order.append("invocations")
        original_invocation_reset()

    monkeypatch.setattr(
        live_provider_staging_result_store_registry,
        "reset_to_memory",
        reset_staging,
    )
    monkeypatch.setattr(
        invocation_store_registry,
        "reset_to_memory",
        reset_invocations,
    )

    with TestClient(app_module.app):
        assert isinstance(
            live_provider_staging_result_store_registry.current(),
            SQLiteLiveProviderStagingResultStore,
        )

    assert order == ["staging", "invocations"]
    get_settings.cache_clear()
