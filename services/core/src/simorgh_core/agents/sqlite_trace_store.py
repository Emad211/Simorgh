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
from simorgh_core.agents.store_lock import (
    ExclusiveStoreLock,
    ExclusiveStoreLockError,
    ExclusiveStoreLockInUseError,
)
from simorgh_core.agents.trace_contracts import (
    TraceEventCandidate,
    TraceEventRecord,
    TraceView,
)
from simorgh_core.agents.trace_store import (
    InMemoryTraceStore,
    TraceClaim,
    TraceClaimKind,
    TraceConflictError,
    TraceNotFoundError,
    TraceStoreClosedError,
    TraceStoreError,
)

TRACE_STORE_SCHEMA_VERSION: Literal[1] = 1


class TraceStoreCorruptionError(TraceStoreError):
    pass


class TraceStoreSchemaError(TraceStoreError):
    pass


class TraceStoreUnhealthyError(TraceStoreError):
    pass


class TraceStoreInUseError(TraceStoreError):
    pass


class SQLiteTraceStore:
    """SQLite WAL authority for immutable source-linked trace events."""

    def __init__(self, path: str | Path) -> None:
        raw_path = str(path)
        self._path = (
            ":memory:"
            if raw_path == ":memory:"
            else str(Path(raw_path).expanduser().resolve())
        )
        self._lock = threading.RLock()
        self._closed = False
        self._failure: TraceStoreError | None = None
        self._path_lock: ExclusiveStoreLock | None = None
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        connection: sqlite3.Connection | None = None
        try:
            if self._path != ":memory:":
                try:
                    self._path_lock = ExclusiveStoreLock(self._path)
                except ExclusiveStoreLockInUseError:
                    raise TraceStoreInUseError(
                        "another Simorgh Core process owns the trace store"
                    ) from None
                except ExclusiveStoreLockError:
                    raise TraceStoreUnhealthyError(
                        "trace store process lock is unavailable"
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
        except TraceStoreError:
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
            raise TraceStoreCorruptionError("could not initialize trace store") from None

    @property
    def path(self) -> str:
        return self._path

    def append(
        self,
        candidate: TraceEventCandidate,
        *,
        ingested_at_ms: int,
    ) -> TraceClaim:
        validated = TraceEventCandidate.model_validate(
            candidate.model_dump(mode="json")
        )
        if ingested_at_ms < 0:
            raise ValueError("trace ingestion time cannot be negative")
        with self._lock:
            self._require_healthy_locked()
            try:
                with self._transaction():
                    existing_records = self._load_trace_locked(validated.trace_id)
                    validator = _validator_for(existing_records)
                    claim = validator.append(
                        validated,
                        ingested_at_ms=ingested_at_ms,
                    )
                    if claim.kind == TraceClaimKind.REPLAY:
                        return claim
                    payload_json, payload_hash = _encoded_record(claim.record)
                    self._connection.execute(
                        """
                        INSERT INTO trace_events (
                            event_id,
                            trace_id,
                            request_id,
                            sequence,
                            event_kind,
                            stage,
                            source_authority_kind,
                            source_authority_id,
                            canonical_sha256,
                            occurred_at_ms,
                            ingested_at_ms,
                            privacy,
                            retention,
                            payload_json,
                            payload_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(claim.record.event_id),
                            str(claim.record.trace_id),
                            str(claim.record.request_id),
                            claim.record.sequence,
                            claim.record.event_kind.value,
                            claim.record.stage.value,
                            claim.record.source_authority_kind.value,
                            str(claim.record.source_authority_id),
                            claim.record.canonical_sha256,
                            claim.record.occurred_at_ms,
                            claim.record.ingested_at_ms,
                            claim.record.privacy.value,
                            claim.record.retention.value,
                            payload_json,
                            payload_hash,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise TraceConflictError(
                    "durable trace event or sequence conflicts with an existing row"
                ) from exc
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not persist trace event", exc)
            return claim

    def get_event(self, event_id: UUID) -> TraceEventRecord:
        with self._lock:
            self._require_healthy_locked()
            try:
                row = self._connection.execute(
                    self._select_sql(where_clause="WHERE event_id = ?"),
                    (str(event_id),),
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not read trace event", exc)
            if row is None:
                raise TraceNotFoundError(f"trace event {event_id} does not exist")
            return self._decode_row_locked(row)

    def view(self, request_id: UUID) -> TraceView:
        with self._lock:
            self._require_healthy_locked()
            try:
                rows = self._connection.execute(
                    self._select_sql(where_clause="WHERE request_id = ?"),
                    (str(request_id),),
                ).fetchall()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not read trace view", exc)
            if not rows:
                raise TraceNotFoundError(f"request {request_id} has no durable trace")
            records = tuple(self._decode_row_locked(row) for row in rows)
            return _validator_for(records).view(request_id)

    def load(self) -> list[TraceEventRecord]:
        with self._lock:
            self._require_healthy_locked()
            self._verify_database_integrity_locked()
            try:
                rows = self._connection.execute(self._select_sql()).fetchall()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not read trace records", exc)
            records = [self._decode_row_locked(row) for row in rows]
            _validate_record_groups(records)
            return records

    def delete_trace(self, request_id: UUID) -> int:
        """Delete one complete trace under the retention transaction boundary."""

        with self._lock:
            self._require_healthy_locked()
            try:
                row = self._connection.execute(
                    "SELECT COUNT(*) AS count FROM trace_events WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
                count = int(row["count"]) if row is not None else 0
                if count:
                    with self._transaction():
                        self._connection.execute(
                            "DELETE FROM trace_events WHERE request_id = ?",
                            (str(request_id),),
                        )
                return count
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not prune terminal trace",
                    exc,
                )

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
                CREATE TABLE IF NOT EXISTS trace_store_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            row = self._connection.execute(
                """
                SELECT value
                FROM trace_store_metadata
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO trace_store_metadata(key, value)
                    VALUES('schema_version', ?)
                    """,
                    (str(TRACE_STORE_SCHEMA_VERSION),),
                )
            elif row["value"] != str(TRACE_STORE_SCHEMA_VERSION):
                raise TraceStoreSchemaError(
                    "unsupported trace store schema version " + str(row["value"])
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    event_kind TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    source_authority_kind TEXT NOT NULL,
                    source_authority_id TEXT NOT NULL,
                    canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
                    occurred_at_ms INTEGER NOT NULL CHECK(occurred_at_ms >= 0),
                    ingested_at_ms INTEGER NOT NULL CHECK(ingested_at_ms >= 0),
                    privacy TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
                    UNIQUE(trace_id, sequence)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS trace_events_request_order
                ON trace_events(request_id, sequence)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS trace_events_source_identity
                ON trace_events(
                    source_authority_kind,
                    source_authority_id,
                    event_kind
                )
                """
            )

    def _load_trace_locked(self, trace_id: UUID) -> tuple[TraceEventRecord, ...]:
        try:
            rows = self._connection.execute(
                self._select_sql(where_clause="WHERE trace_id = ?"),
                (str(trace_id),),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked("could not read trace records", exc)
        return tuple(self._decode_row_locked(row) for row in rows)

    def _validate_all_records_locked(self) -> None:
        try:
            rows = self._connection.execute(self._select_sql()).fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked("could not validate trace records", exc)
        records = [self._decode_row_locked(row) for row in rows]
        try:
            _validate_record_groups(records)
        except (TraceStoreError, ValueError):
            self._latch_corruption_locked("trace event causality is invalid")

    def _decode_row_locked(self, row: sqlite3.Row) -> TraceEventRecord:
        payload_json = row["payload_json"]
        expected_hash = row["payload_sha256"]
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            self._latch_corruption_locked("trace payload hash mismatch")
        try:
            decoded = json.loads(payload_json)
            record = TraceEventRecord.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValueError):
            self._latch_corruption_locked("trace payload contract is invalid")
        indexed_identity = (
            str(record.event_id),
            str(record.trace_id),
            str(record.request_id),
            record.sequence,
            record.event_kind.value,
            record.stage.value,
            record.source_authority_kind.value,
            str(record.source_authority_id),
            record.canonical_sha256,
            record.occurred_at_ms,
            record.ingested_at_ms,
            record.privacy.value,
            record.retention.value,
        )
        row_identity = tuple(row[key] for key in _INDEXED_COLUMNS)
        if indexed_identity != row_identity:
            self._latch_corruption_locked(
                "trace indexed columns do not match authoritative payload"
            )
        return record

    @staticmethod
    def _select_sql(*, where_clause: str = "") -> str:
        return f"""
            SELECT
                event_id,
                trace_id,
                request_id,
                sequence,
                event_kind,
                stage,
                source_authority_kind,
                source_authority_id,
                canonical_sha256,
                occurred_at_ms,
                ingested_at_ms,
                privacy,
                retention,
                payload_json,
                payload_sha256
            FROM trace_events
            {where_clause}
            ORDER BY trace_id, sequence
        """

    def _verify_database_integrity_locked(self) -> None:
        self._require_not_closed_locked()
        try:
            rows = self._connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not verify trace database integrity",
                exc,
            )
        if [str(row[0]) for row in rows] != ["ok"]:
            self._latch_corruption_locked("trace database integrity check failed")

    def _require_healthy_locked(self) -> None:
        self._require_not_closed_locked()
        if self._failure is not None:
            raise TraceStoreUnhealthyError(
                "trace store is unhealthy after a durable operation failure"
            ) from self._failure

    def _require_not_closed_locked(self) -> None:
        if self._closed:
            raise TraceStoreClosedError("trace store is closed")

    def _raise_database_failure_locked(
        self,
        message: str,
        exc: sqlite3.DatabaseError,
    ) -> NoReturn:
        failure = TraceStoreCorruptionError(message)
        if self._failure is None:
            self._failure = failure
        raise failure from exc

    def _latch_corruption_locked(self, message: str) -> NoReturn:
        failure = TraceStoreCorruptionError(message)
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
    "event_id",
    "trace_id",
    "request_id",
    "sequence",
    "event_kind",
    "stage",
    "source_authority_kind",
    "source_authority_id",
    "canonical_sha256",
    "occurred_at_ms",
    "ingested_at_ms",
    "privacy",
    "retention",
)


def _candidate_from_record(record: TraceEventRecord) -> TraceEventCandidate:
    return TraceEventCandidate.model_validate(
        record.model_dump(
            mode="json",
            exclude={"sequence", "ingested_at_ms"},
        )
    )


def _validator_for(records: tuple[TraceEventRecord, ...]) -> InMemoryTraceStore:
    validator = InMemoryTraceStore()
    for expected_sequence, record in enumerate(records, start=1):
        if record.sequence != expected_sequence:
            raise TraceStoreCorruptionError("trace event sequence is not contiguous")
        claim = validator.append(
            _candidate_from_record(record),
            ingested_at_ms=record.ingested_at_ms,
        )
        if claim.kind != TraceClaimKind.NEW or claim.record != record:
            raise TraceStoreCorruptionError("trace record replay differs from stored row")
    return validator


def _validate_record_groups(records: list[TraceEventRecord]) -> None:
    by_trace: dict[UUID, list[TraceEventRecord]] = {}
    for record in records:
        by_trace.setdefault(record.trace_id, []).append(record)
    for trace_records in by_trace.values():
        _validator_for(tuple(trace_records))


def _encoded_record(record: TraceEventRecord) -> tuple[str, str]:
    payload_json = canonical_json(record)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return payload_json, payload_hash


__all__ = [
    "TRACE_STORE_SCHEMA_VERSION",
    "SQLiteTraceStore",
    "TraceStoreCorruptionError",
    "TraceStoreInUseError",
    "TraceStoreSchemaError",
    "TraceStoreUnhealthyError",
]