from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from simorgh_core.config import get_settings


@pytest.fixture(autouse=True)
def isolated_core_stores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Give every Core test private SQLite authorities and a fresh settings cache."""

    monkeypatch.setenv(
        "SIMORGH_ACTION_JOURNAL_PATH",
        str(tmp_path / "simorgh-action-journal.sqlite3"),
    )
    monkeypatch.setenv("SIMORGH_ACTION_JOURNAL_MAX_TERMINAL_RECORDS", "256")
    monkeypatch.setenv(
        "SIMORGH_AGENT_TASK_STORE_PATH",
        str(tmp_path / "simorgh-agent-tasks.sqlite3"),
    )
    monkeypatch.setenv(
        "SIMORGH_AGENT_TASK_STORE_MAX_TERMINAL_RECORDS",
        "10000",
    )
    monkeypatch.setenv(
        "SIMORGH_INVOCATION_STORE_PATH",
        str(tmp_path / "simorgh-invocations.sqlite3"),
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
