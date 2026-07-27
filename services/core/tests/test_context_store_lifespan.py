from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simorgh_core.agents.context_store import (
    ContextStoreSchemaError,
    InMemoryContextStore,
    SQLiteContextStore,
    context_store_registry,
)
from simorgh_core.app import app, lifespan
from simorgh_core.config import get_settings


def test_application_lifespan_loads_and_resets_context_authority() -> None:
    path = Path(get_settings().simorgh_context_store_path)
    store = SQLiteContextStore(path)
    store.close()

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        current = context_store_registry.current()
        assert isinstance(current, SQLiteContextStore)
        assert Path(current.path) == path.expanduser().resolve()

    current = context_store_registry.current()
    assert isinstance(current, InMemoryContextStore)
    assert current.load() == []


def test_context_schema_failure_aborts_startup() -> None:
    path = Path(get_settings().simorgh_context_store_path)
    store = SQLiteContextStore(path)
    store.close()
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE context_store_metadata SET value = '999' WHERE key = 'schema_version'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        ContextStoreSchemaError,
        match="unsupported context store schema",
    ), TestClient(app):
        pass


def test_core_rejects_context_and_result_path_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared.sqlite3"
    monkeypatch.setenv("SIMORGH_RESULT_STORE_PATH", str(shared))
    monkeypatch.setenv("SIMORGH_CONTEXT_STORE_PATH", str(shared))
    get_settings.cache_clear()

    async def enter() -> None:
        async with lifespan(None):  # type: ignore[arg-type]
            raise AssertionError("lifespan must not start")

    with pytest.raises(RuntimeError, match="must be distinct"):
        asyncio.run(enter())
