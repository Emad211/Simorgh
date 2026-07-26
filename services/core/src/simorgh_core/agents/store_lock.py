from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Self


class ExclusiveStoreLockError(RuntimeError):
    pass


class ExclusiveStoreLockInUseError(ExclusiveStoreLockError):
    pass


class ExclusiveStoreLock:
    """Cross-platform non-blocking process lock for one SQLite authority path."""

    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path).expanduser().resolve()
        self._lock_path = Path(f"{path}.lock")
        self._handle: BinaryIO | None = None
        self._closed = False
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._acquire()
        except OSError:
            raise ExclusiveStoreLockError(
                "the durable store process lock could not be opened"
            ) from None

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            self._unlock(handle)
        finally:
            handle.close()

    def _acquire(self) -> None:
        handle = self._open_regular_lock_file()
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            self._lock(handle)
        except BaseException:
            handle.close()
            raise
        self._handle = handle

    def _open_regular_lock_file(self) -> BinaryIO:
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        if os.name != "nt":
            flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self._lock_path, flags, 0o600)
        except OSError as exc:
            if exc.errno == getattr(errno, "ELOOP", -1):
                raise ExclusiveStoreLockError(
                    "the durable store lock path cannot be a symlink"
                ) from None
            raise
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ExclusiveStoreLockError(
                    "the durable store lock path is not a regular file"
                )
            if opened.st_nlink != 1:
                raise ExclusiveStoreLockError(
                    "the durable store lock path cannot be hard-linked"
                )
            indexed = os.stat(self._lock_path, follow_symlinks=False)
            if stat.S_ISLNK(indexed.st_mode):
                raise ExclusiveStoreLockError(
                    "the durable store lock path cannot be a symlink"
                )
            if (opened.st_dev, opened.st_ino) != (indexed.st_dev, indexed.st_ino):
                raise ExclusiveStoreLockError(
                    "the durable store lock path changed while it was opened"
                )
            return os.fdopen(descriptor, "r+b", buffering=0)
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _lock(handle: BinaryIO) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                windows_lock: Any = msvcrt
                windows_lock.locking(
                    handle.fileno(),
                    windows_lock.LK_NBLCK,
                    1,
                )
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ExclusiveStoreLockInUseError(
                "another Simorgh Core process already owns this store path"
            ) from None
        except OSError as exc:
            contention_errors = {errno.EACCES, errno.EAGAIN}
            if hasattr(errno, "EDEADLK"):
                contention_errors.add(errno.EDEADLK)
            if exc.errno in contention_errors:
                raise ExclusiveStoreLockInUseError(
                    "another Simorgh Core process already owns this store path"
                ) from None
            raise ExclusiveStoreLockError(
                "the durable store process lock could not be acquired"
            ) from None

    @staticmethod
    def _unlock(handle: BinaryIO) -> None:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                windows_lock: Any = msvcrt
                windows_lock.locking(
                    handle.fileno(),
                    windows_lock.LK_UNLCK,
                    1,
                )
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
