from __future__ import annotations

from pathlib import Path

import pytest

import simorgh_core.app as app_module
from simorgh_core.agents.trace_projection import (
    NullRequestTraceProjector,
    StoreBackedRequestTraceProjector,
    request_trace_projector_registry,
)
from simorgh_core.agents.trace_retention import RetentionAwareTraceStore
from simorgh_core.agents.trace_store import (
    InMemoryTraceStore,
    TraceStoreClosedError,
)
from simorgh_core.agents.trace_store_registry import trace_store_registry
from simorgh_core.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        simorgh_action_journal_path=str(tmp_path / "actions.sqlite3"),
        simorgh_agent_task_store_path=str(tmp_path / "tasks.sqlite3"),
        simorgh_invocation_store_path=str(tmp_path / "invocations.sqlite3"),
        simorgh_result_store_path=str(tmp_path / "results.sqlite3"),
        simorgh_context_store_path=str(tmp_path / "contexts.sqlite3"),
        simorgh_trace_store_path=str(tmp_path / "traces.sqlite3"),
    )


@pytest.mark.asyncio
async def test_lifespan_configures_and_resets_trace_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)

    async with app_module.lifespan(app_module.app):
        configured = trace_store_registry.current()
        assert isinstance(configured, RetentionAwareTraceStore)
        assert configured.load() == []
        assert Path(settings.simorgh_trace_store_path).exists()
        assert isinstance(
            request_trace_projector_registry.current(),
            StoreBackedRequestTraceProjector,
        )

    assert isinstance(trace_store_registry.current(), InMemoryTraceStore)
    assert isinstance(
        request_trace_projector_registry.current(),
        NullRequestTraceProjector,
    )
    with pytest.raises(TraceStoreClosedError, match="closed"):
        configured.load()
