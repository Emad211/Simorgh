from __future__ import annotations

import os
from pathlib import Path

import pytest

from simorgh_core.app import _require_distinct_store_paths
from simorgh_core.config import Settings


def _settings(
    tmp_path: Path,
    *,
    staging_path: Path,
    trace_path: Path | None = None,
) -> Settings:
    return Settings(
        _env_file=None,
        simorgh_action_journal_path=str(tmp_path / "actions.sqlite3"),
        simorgh_agent_task_store_path=str(tmp_path / "tasks.sqlite3"),
        simorgh_invocation_store_path=str(tmp_path / "invocations.sqlite3"),
        simorgh_result_store_path=str(tmp_path / "results.sqlite3"),
        simorgh_context_store_path=str(tmp_path / "contexts.sqlite3"),
        simorgh_trace_store_path=str(trace_path or tmp_path / "traces.sqlite3"),
        simorgh_live_provider_staging_result_store_path=str(staging_path),
    )


def test_settings_expose_independent_staging_result_store_path() -> None:
    settings = Settings(_env_file=None)

    assert settings.simorgh_live_provider_staging_result_store_path == (
        ".simorgh/live-provider-staging-results.sqlite3"
    )


def test_core_rejects_exact_staging_result_path_alias(tmp_path: Path) -> None:
    shared = tmp_path / "shared.sqlite3"
    settings = _settings(
        tmp_path,
        staging_path=shared,
        trace_path=shared,
    )

    with pytest.raises(RuntimeError, match="must be distinct"):
        _require_distinct_store_paths(settings)


def test_core_rejects_hard_link_staging_result_path_alias(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.sqlite3"
    staging_path = tmp_path / "staging.sqlite3"
    trace_path.touch()
    try:
        os.link(trace_path, staging_path)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")

    settings = _settings(
        tmp_path,
        staging_path=staging_path,
        trace_path=trace_path,
    )

    with pytest.raises(RuntimeError, match="must be distinct"):
        _require_distinct_store_paths(settings)
