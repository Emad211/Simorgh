from __future__ import annotations

from pathlib import Path

import pytest

from simorgh_core.app import _require_distinct_store_paths
from simorgh_core.config import Settings


def _settings(tmp_path: Path, **updates: object) -> Settings:
    values: dict[str, object] = {
        "simorgh_action_journal_path": str(tmp_path / "actions.sqlite3"),
        "simorgh_agent_task_store_path": str(tmp_path / "tasks.sqlite3"),
        "simorgh_invocation_store_path": str(tmp_path / "invocations.sqlite3"),
        "simorgh_result_store_path": str(tmp_path / "results.sqlite3"),
        "simorgh_context_store_path": str(tmp_path / "contexts.sqlite3"),
        "simorgh_trace_store_path": str(tmp_path / "traces.sqlite3"),
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def test_trace_store_has_independent_bounded_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert settings.simorgh_trace_store_path.endswith("traces.sqlite3")
    assert settings.simorgh_trace_store_max_terminal_records == 10_000
    _require_distinct_store_paths(settings)


def test_trace_store_path_alias_is_rejected(tmp_path: Path) -> None:
    shared = str(tmp_path / "shared.sqlite3")
    settings = _settings(
        tmp_path,
        simorgh_context_store_path=shared,
        simorgh_trace_store_path=shared,
    )

    with pytest.raises(RuntimeError, match="must be distinct"):
        _require_distinct_store_paths(settings)
