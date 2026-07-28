from __future__ import annotations

from pathlib import Path

import pytest

from simorgh_core.agents.context_store import (
    ContextStoreInUseError,
    SQLiteContextStore,
)


def test_sqlite_context_store_requires_exclusive_process_ownership(
    tmp_path: Path,
) -> None:
    path = tmp_path / "contexts.sqlite3"
    first = SQLiteContextStore(path)
    try:
        with pytest.raises(ContextStoreInUseError, match="owns the context store"):
            SQLiteContextStore(path)
    finally:
        first.close()

    reopened = SQLiteContextStore(path)
    reopened.close()
