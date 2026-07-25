from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from simorgh_core.config import get_settings


@pytest.fixture(autouse=True)
def isolated_action_journal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Give every Core test one private SQLite journal and settings cache."""

    monkeypatch.setenv(
        "SIMORGH_ACTION_JOURNAL_PATH",
        str(tmp_path / "simorgh-action-journal.sqlite3"),
    )
    monkeypatch.setenv("SIMORGH_ACTION_JOURNAL_MAX_TERMINAL_RECORDS", "256")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
