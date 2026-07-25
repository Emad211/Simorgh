from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simorgh_core.agents.api import agent_task_control_plane
from simorgh_core.agents.task_store import (
    AgentTaskStoreSchemaError,
    SQLiteAgentTaskStore,
)
from simorgh_core.app import app
from simorgh_core.config import get_settings


def _configure_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path]:
    action_path = tmp_path / "action-journal.sqlite3"
    task_path = tmp_path / "agent-tasks.sqlite3"
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    monkeypatch.setenv("SIMORGH_ACTION_JOURNAL_PATH", str(action_path))
    monkeypatch.setenv("SIMORGH_AGENT_TASK_STORE_PATH", str(task_path))
    get_settings.cache_clear()
    return action_path, task_path


def test_task_store_schema_failure_unwinds_action_storage_and_allows_clean_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    action_path, task_path = _configure_environment(monkeypatch, tmp_path)
    asyncio.run(agent_task_control_plane.reset_to_memory_store())

    store = SQLiteAgentTaskStore(task_path)
    store.close()
    connection = sqlite3.connect(task_path)
    connection.execute(
        """
        UPDATE agent_task_store_metadata
        SET value = '999'
        WHERE key = 'schema_version'
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(AgentTaskStoreSchemaError, match="unsupported"):
        with TestClient(app):
            pass

    task_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{task_path}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    get_settings.cache_clear()

    with TestClient(app) as restarted:
        response = restarted.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    assert action_path.exists()
    asyncio.run(agent_task_control_plane.reset_to_memory_store())
    get_settings.cache_clear()
