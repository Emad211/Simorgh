from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, NoReturn
from uuid import UUID

from simorgh_core.agents.invocations import canonical_json
from simorgh_core.agents.live_provider_staging_contracts import (
    LiveProviderStagingResult,
)
from simorgh_core.agents.live_provider_staging_store import (
    LiveProviderStagingClaim,
    LiveProviderStagingClaimKind,
    LiveProviderStagingStoreClosedError,
    LiveProviderStagingStoreConflictError,
    LiveProviderStagingStoreError,
    LiveProviderStagingStoreNotFoundError,
    _require_same_record,
    _validated_fresh_result,
)
from simorgh_core.agents.store_lock import (
    ExclusiveStoreLock,
    ExclusiveStoreLockError,
    ExclusiveStoreLockInUseError,
)

LIVE_PROVIDER_STAGING_STORE_SCHEMA_VERSION: Literal[1] = 1


class LiveProviderStagingStoreCorruptionError(LiveProviderStagingStoreError):
    pass


class LiveProviderStagingStoreSchemaError(LiveProviderStagingStoreError):
    pass


class LiveProviderStagingStoreUnhealthyError(LiveProviderStagingStoreError):
    pass


class LiveProviderStagingStoreInUseError(LiveProviderStagingStoreError):
    pass


class SQLiteLiveProviderStagingResultStore:
    """SQLite WAL authority for immutable sanitized live-canary results."""

    def __init__(self, path: str | Path) -> None:
        raw_path = str(path)
        self._path = (
            ":memory:"
            if raw_path == ":memory:"
            else str(Path(raw_path).expanduser().resolve())
        )
        self._lock = threading.RLock()
        self._closed = False
        self._failure: LiveProviderStagingStoreError | None = None
        self._path_lock: ExclusiveStoreLock | None = None
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        connection: sqlite3.Connection | None = None
        try:
            if self._path != ":memory:":
                try:
                    self._path_lock = ExclusiveStoreLock(self._path)
                except ExclusiveStoreLockInUseError:
                    raise LiveProviderStagingStoreInUseError(
                        "another Simorgh Core process owns the staging result store"
                    ) from None
                except ExclusiveStoreLockError:
                    raise LiveProviderStagingStoreUnhealthyError(
                        "staging result store process lock is unavailable"
                    ) from None
            connection = sqlite3.connect(
                self._path,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            if self._path != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._initialize_schema()
            self._verify_database_integrity_locked()
            self._validate_all_records_locked()
        except LiveProviderStagingStoreError:
            if connection is not None:
                connection.close()
            if self._path_lock is not None:
                self._path_lock.close()
                self._path_lock = None
            raise
        except sqlite3.DatabaseError:
            if connection is not None:
                connection.close()
            if self._path_lock is not None:
                self._path_lock.close()
                self._path_lock = None
            raise LiveProviderStagingStoreCorruptionError(
                "could not initialize staging result store"
            ) from None

    @property
    def path(self) -> str:
        return self._path

    def claim(self, record: LiveProviderStagingResult) -> LiveProviderStagingClaim:
        candidate = _validated_fresh_result(record)
        with self._lock:
            self._require_healthy_locked()
            existing = self._get_optional_locked(staging_run_id=candidate.staging_run_id)
            if existing is None:
                existing = self._get_optional_locked(
                    invocation_id=candidate.invocation_id
                )
            if existing is not None:
                _require_same_record(existing, candidate)
                return LiveProviderStagingClaim(
                    kind=LiveProviderStagingClaimKind.REPLAY,
                    record=existing,
                )

            payload_json, payload_sha256 = _encoded_record(candidate)
            try:
                with self._transaction():
                    self._connection.execute(
                        """
                        INSERT INTO live_provider_staging_results (
                            staging_run_id,
                            staging_result_id,
                            request_id,
                            invocation_id,
                            provider_id,
                            model_id,
                            transaction_provider_id,
                            invocation_state,
                            disposition,
                            completed_at_ms,
                            canonical_sha256,
                            payload_json,
                            payload_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(candidate.staging_run_id),
                            str(candidate.staging_result_id),
                            str(candidate.request_id),
                            str(candidate.invocation_id),
                            candidate.provider_id,
                            candidate.model_id,
                            candidate.transaction_provider_id,
                            candidate.invocation_state.value,
                            candidate.disposition.value,
                            candidate.completed_at_ms,
                            candidate.canonical_sha256,
                            payload_json,
                            payload_sha256,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                current = self._get_optional_locked(
                    staging_run_id=candidate.staging_run_id
                )
                if current is None:
                    current = self._get_optional_locked(
                        invocation_id=candidate.invocation_id
                    )
                if current is not None:
                    _require_same_record(current, candidate)
                    return LiveProviderStagingClaim(
                        kind=LiveProviderStagingClaimKind.REPLAY,
                        record=current,
                    )
                raise LiveProviderStagingStoreConflictError(
                    "durable staging result identity conflicts with existing row"
                ) from exc
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not persist staging result",
                    exc,
                )
            return LiveProviderStagingClaim(
                kind=LiveProviderStagingClaimKind.NEW,
                record=candidate,
            )

    def get(self, staging_run_id: UUID) -> LiveProviderStagingResult:
        with self._lock:
            self._require_healthy_locked()
            record = self._get_optional_locked(staging_run_id=staging_run_id)
            if record is None:
                raise LiveProviderStagingStoreNotFoundError(
                    "live-provider staging result does not exist"
                )
            return record

    def get_by_invocation(self, invocation_id: UUID) -> LiveProviderStagingResult:
        with self._lock:
            self._require_healthy_locked()
            record = self._get_optional_locked(invocation_id=invocation_id)
            if record is None:
                raise LiveProviderStagingStoreNotFoundError(
                    "staging invocation has no durable result"
                )
            return record

    def load(self) -> list[LiveProviderStagingResult]:
        with self._lock:
            self._require_healthy_locked()
            self._verify_database_integrity_locked()
            try:
                rows = self._connection.execute(self._select_sql()).fetchall()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not read staging result records",
                    exc,
                )
            return [self._decode_row_locked(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._connection.close()
            finally:
                if self._path_lock is not None:
                    self._path_lock.close()
                    self._path_lock = None

    def _initialize_schema(self) -> None:
        with self._transaction():
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS live_provider_staging_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            row = self._connection.execute(
                """
                SELECT value
                FROM live_provider_staging_metadata
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO live_provider_staging_metadata(key, value)
                    VALUES('schema_version', ?)
                    """,
                    (str(LIVE_PROVIDER_STAGING_STORE_SCHEMA_VERSION),),
                )
            elif row["value"] != str(LIVE_PROVIDER_STAGING_STORE_SCHEMA_VERSION):
                raise LiveProviderStagingStoreSchemaError(
                    "unsupported staging result store schema version"
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS live_provider_staging_results (
                    staging_run_id TEXT PRIMARY KEY,
                    staging_result_id TEXT NOT NULL UNIQUE,
                    request_id TEXT NOT NULL,
                    invocation_id TEXT NOT NULL UNIQUE,
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    transaction_provider_id TEXT NOT NULL,
                    invocation_state TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    completed_at_ms INTEGER NOT NULL CHECK(completed_at_ms >= 0),
                    canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS staging_results_request_order
                ON live_provider_staging_results(
                    request_id,
                    completed_at_ms,
                    staging_run_id
                )
                """
            )

    def _get_optional_locked(
        self,
        *,
        staging_run_id: UUID | None = None,
        invocation_id: UUID | None = None,
    ) -> LiveProviderStagingResult | None:
        if (staging_run_id is None) == (invocation_id is None):
            raise ValueError("exactly one staging result lookup identity is required")
        if staging_run_id is not None:
            where_clause = "WHERE staging_run_id = ?"
            value = str(staging_run_id)
        else:
            where_clause = "WHERE invocation_id = ?"
            value = str(invocation_id)
        try:
            row = self._connection.execute(
                self._select_sql(where_clause=where_clause),
                (value,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not read staging result record",
                exc,
            )
        return self._decode_row_locked(row) if row is not None else None

    def _validate_all_records_locked(self) -> None:
        try:
            rows = self._connection.execute(self._select_sql()).fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not validate staging result records",
                exc,
            )
        for row in rows:
            self._decode_row_locked(row)

    def _decode_row_locked(self, row: sqlite3.Row) -> LiveProviderStagingResult:
        payload_json = row["payload_json"]
        expected_hash = row["payload_sha256"]
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            self._latch_corruption_locked("staging result payload hash mismatch")
        try:
            decoded = json.loads(payload_json)
            record = LiveProviderStagingResult.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValueError):
            self._latch_corruption_locked("staging result payload contract is invalid")
        indexed_identity = (
            str(record.staging_run_id),
            str(record.staging_result_id),
            str(record.request_id),
            str(record.invocation_id),
            record.provider_id,
            record.model_id,
            record.transaction_provider_id,
            record.invocation_state.value,
            record.disposition.value,
            record.completed_at_ms,
            record.canonical_sha256,
        )
        row_identity = tuple(row[key] for key in _INDEXED_COLUMNS)
        if indexed_identity != row_identity:
            self._latch_corruption_locked(
                "staging result indexed columns do not match payload"
            )
        return record

    @staticmethod
    def _select_sql(*, where_clause: str = "") -> str:
        return f"""
            SELECT
                staging_run_id,
                staging_result_id,
                request_id,
                invocation_id,
                provider_id,
                model_id,
                transaction_provider_id,
                invocation_state,
                disposition,
                completed_at_ms,
                canonical_sha256,
                payload_json,
                payload_sha256
            FROM live_provider_staging_results
            {where_clause}
            ORDER BY completed_at_ms, staging_run_id
        """

    def _verify_database_integrity_locked(self) -> None:
        self._require_not_closed_locked()
        try:
            rows = self._connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not verify staging result database integrity",
                exc,
            )
        if [str(row[0]) for row in rows] != ["ok"]:
            self._latch_corruption_locked(
                "staging result database integrity check failed"
            )

    def _require_healthy_locked(self) -> None:
        self._require_not_closed_locked()
        if self._failure is not None:
            raise LiveProviderStagingStoreUnhealthyError(
                "staging result store is unhealthy after durable failure"
            ) from self._failure

    def _require_not_closed_locked(self) -> None:
        if self._closed:
            raise LiveProviderStagingStoreClosedError(
                "live-provider staging result store is closed"
            )

    def _raise_database_failure_locked(
        self,
        message: str,
        exc: sqlite3.DatabaseError,
    ) -> NoReturn:
        failure = LiveProviderStagingStoreCorruptionError(message)
        if self._failure is None:
            self._failure = failure
        raise failure from exc

    def _latch_corruption_locked(self, message: str) -> NoReturn:
        failure = LiveProviderStagingStoreCorruptionError(message)
        if self._failure is None:
            self._failure = failure
        raise failure from None

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")


_INDEXED_COLUMNS = (
    "staging_run_id",
    "staging_result_id",
    "request_id",
    "invocation_id",
    "provider_id",
    "model_id",
    "transaction_provider_id",
    "invocation_state",
    "disposition",
    "completed_at_ms",
    "canonical_sha256",
)


def _encoded_record(record: LiveProviderStagingResult) -> tuple[str, str]:
    payload_json = canonical_json(record)
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return payload_json, payload_sha256


__all__ = [
    "LIVE_PROVIDER_STAGING_STORE_SCHEMA_VERSION",
    "LiveProviderStagingStoreCorruptionError",
    "LiveProviderStagingStoreInUseError",
    "LiveProviderStagingStoreSchemaError",
    "LiveProviderStagingStoreUnhealthyError",
    "SQLiteLiveProviderStagingResultStore",
]
