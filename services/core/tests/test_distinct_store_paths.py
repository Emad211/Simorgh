from __future__ import annotations

import asyncio
import os

import pytest

from simorgh_core.app import lifespan
from simorgh_core.config import get_settings


def test_core_rejects_shared_file_path_for_distinct_durable_authorities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    shared = tmp_path / "shared.sqlite3"
    monkeypatch.setenv("SIMORGH_ACTION_JOURNAL_PATH", str(shared))
    monkeypatch.setenv("SIMORGH_AGENT_TASK_STORE_PATH", str(shared))
    monkeypatch.setenv("SIMORGH_INVOCATION_STORE_PATH", str(tmp_path / "inv.sqlite3"))
    get_settings.cache_clear()

    async def enter() -> None:
        async with lifespan(None):  # type: ignore[arg-type]
            raise AssertionError("lifespan must not start")

    with pytest.raises(RuntimeError, match="must be distinct"):
        asyncio.run(enter())


def test_core_rejects_hard_link_aliases_for_durable_authorities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    original = tmp_path / "authority-a.sqlite3"
    alias = tmp_path / "authority-b.sqlite3"
    original.touch()
    try:
        os.link(original, alias)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")
    monkeypatch.setenv("SIMORGH_ACTION_JOURNAL_PATH", str(original))
    monkeypatch.setenv("SIMORGH_AGENT_TASK_STORE_PATH", str(alias))
    monkeypatch.setenv(
        "SIMORGH_INVOCATION_STORE_PATH",
        str(tmp_path / "invocations.sqlite3"),
    )
    get_settings.cache_clear()

    async def enter() -> None:
        async with lifespan(None):  # type: ignore[arg-type]
            raise AssertionError("lifespan must not start")

    with pytest.raises(RuntimeError, match="must be distinct"):
        asyncio.run(enter())
