from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import InvocationStoreInUseError
from simorgh_core.agents.store_lock import (
    ExclusiveStoreLock,
    ExclusiveStoreLockError,
    ExclusiveStoreLockInUseError,
)


def test_second_store_owner_is_rejected_until_first_closes(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    first = SQLiteInvocationStore(path)
    with pytest.raises(InvocationStoreInUseError, match="another Simorgh Core"):
        SQLiteInvocationStore(path)
    first.close()
    second = SQLiteInvocationStore(path)
    second.close()


def test_lock_blocks_a_second_python_process(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    first = SQLiteInvocationStore(path)
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(source_root), environment.get("PYTHONPATH", ""))
        if part
    )
    code = f"""
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import InvocationStoreInUseError
try:
    SQLiteInvocationStore({str(path)!r})
except InvocationStoreInUseError:
    raise SystemExit(0)
raise SystemExit(3)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        cwd=source_root.parent,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    first.close()


def test_low_level_lock_contention_has_distinct_in_use_type(tmp_path: Path) -> None:
    path = tmp_path / "low-level.sqlite3"
    first = ExclusiveStoreLock(path)
    with pytest.raises(ExclusiveStoreLockInUseError):
        ExclusiveStoreLock(path)
    first.close()


def test_lock_path_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    database = tmp_path / "invocations.sqlite3"
    target = tmp_path / "unrelated-target"
    target.write_bytes(b"")
    lock_path = Path(f"{database.resolve()}.lock")
    try:
        lock_path.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this filesystem")
    with pytest.raises(ExclusiveStoreLockError, match="cannot be a symlink"):
        ExclusiveStoreLock(database)
    assert target.read_bytes() == b""


def test_lock_path_hard_link_is_rejected_without_touching_target(tmp_path: Path) -> None:
    database = tmp_path / "hardlink.sqlite3"
    target = tmp_path / "hardlink-target"
    target.write_bytes(b"")
    lock_path = Path(f"{database.resolve()}.lock")
    try:
        os.link(target, lock_path)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")
    with pytest.raises(ExclusiveStoreLockError, match="cannot be hard-linked"):
        ExclusiveStoreLock(database)
    assert target.read_bytes() == b""


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock-specific failure fixture")
def test_non_contention_lock_failure_is_not_reported_as_an_active_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import errno
    import fcntl

    lock_file = tmp_path / "failure.lock"
    with lock_file.open("a+b") as handle:
        monkeypatch.setattr(
            fcntl,
            "flock",
            lambda *_args: (_ for _ in ()).throw(OSError(errno.EIO, "fixture")),
        )
        with pytest.raises(ExclusiveStoreLockError, match="could not be acquired"):
            ExclusiveStoreLock._lock(handle)
