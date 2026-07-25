from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
from simorgh_core.devices.action_journal import ActionJournalSchemaError


def test_unknown_action_journal_schema_prevents_core_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "unsupported-action-journal.sqlite3"
    connection = sqlite3.connect(journal_path)
    try:
        connection.execute(
            "CREATE TABLE action_journal_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO action_journal_metadata(key, value) VALUES('schema_version', '999')"
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setenv("SIMORGH_ACTION_JOURNAL_PATH", str(journal_path))
    get_settings.cache_clear()
    try:
        with pytest.raises(ActionJournalSchemaError, match="unsupported"):
            with TestClient(app):
                pass
    finally:
        get_settings.cache_clear()
