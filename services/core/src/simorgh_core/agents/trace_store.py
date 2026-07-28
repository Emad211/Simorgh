from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Literal, NoReturn, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from simorgh_core.agents.invocations import canonical_json
from simorgh_core.agents.store_lock import (
    ExclusiveStoreLock,
    ExclusiveStoreLockError,
    ExclusiveStoreLockInUseError,
)
from simorgh_core.agents.trace_authority import (
    CorrelatedTraceEvent,
    TraceEventCandidate,
    event_id_for_candidate,
    materialize_trace_event,
    trace_id_for_request,
)

TRACE_STORE_SCHEMA_VERSION: Literal[1] = 1


class TraceStoreError(RuntimeError):
    """Base class for deterministic trace-store failures."""


class TraceConflictError(TraceStoreError):
    pass


class TraceNotFoundError(TraceStoreError):
    pass


class TraceStoreClosedError(TraceStoreError):
    pass


class TraceStoreCorruptionError(TraceStoreError):
    pass


class TraceStoreSchemaError(TraceStoreError):
    pass


class TraceStoreUnhealthyError(TraceStoreError):
    pass


class TraceStoreInUseError(TraceStoreError):
    pass


class TraceAppendKind(StrEnum):
    NEW = "new"
    REPLAY = "replay"


class TraceAppend(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: TraceAppendKind
    record: CorrelatedTraceEvent


class TraceStore(Protocol):
    def append(self, candidate: TraceEventCandidate) -> TraceAppend: ...

    def get_event(self, event_id: UUID) -> CorrelatedTraceEvent: ...

    def for_request(self, request_id: UUID) -> tuple[CorrelatedTraceEvent, ...]: ...

    def for_trace(self, trace_id: UUID) -> tuple[CorrelatedTraceEvent, ...]: ...

    def load(self) -> list[CorrelatedTraceEvent]: ...

    def close(self) -> None: ...


class InMemoryTraceStore:
    """Strict process-local append-only trace authority."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: dict[UUID, CorrelatedTraceEvent] = {}
        self._by_trace: dict[UUID, list[UUID]] = {}
        self._by_request: dict[UUID, UUID] = {}
        self._closed = False

    def append(self, candidate: TraceEventCandidate) -> TraceAppend:
        validated = _validated_candidate(candidate)
        event_id = event_id_for_candidate(validated)
        trace_id = trace_id_for_request(validated.request_id)
        with self._lock:
            self._require_open_locked()
            existing = self._events.get(event_id)
            if existing is not None:
                _require_same_event(
                    existing,
                    materialize_trace_event(
                        validated,
                        causal_sequence=existing.causal_sequence,
                    ),
                )
                return TraceAppend(kind=TraceAppendKind.REPLAY, record=existing)
            known_trace = self._by_request.get(validated.request_id)
            if known_trace is not None and known_trace != trace_id:
                raise TraceConflictError("request identity maps to another trace")
            event_ids = self._by_trace.setdefault(trace_id, [])
            record = materialize_trace_event(
                validated,
                causal_sequence=len(event_ids) + 1,
            )
            self._events[record.event_id] = record
            event_ids.append(record.event_id)
            self._by_request[record.request_id] = record.trace_id
            return TraceAppend(kind=TraceAppendKind.NEW, record=record)

    def get_event(self, event_id: UUID) -> CorrelatedTraceEvent:
        with self._lock:
            self._require_open_locked()
            record = self._events.get(event_id)
            if record is None:
                raise TraceNotFoundError(f"trace event {event_id} does not exist")
            return record

    def for_request(self, request_id: UUID) -> tuple[CorrelatedTraceEvent, ...]:
        with self._lock:
            self._require_open_locked()
            trace_id = self._by_request.get(request_id)
            if trace_id is None:
                return ()
            return self._for_trace_locked(trace_id)

    def for_trace(self, trace_id: UUID) -> tuple[CorrelatedTraceEvent, ...]:
        with self._lock:
            self._require_open_locked()
            return self._for_trace_locked(trace_id)

    def load(self) -> list[CorrelatedTraceEvent]:
        with self._lock:
            self._require_open_locked()
            return sorted(
                self._events.values(),
                key=lambda event: (str(event.trace_id), event.causal_sequence),
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _for_trace_locked(self, trace_id: UUID) -> tuple[CorrelatedTraceEvent, ...]:
        return tuple(
            self._events[event_id] for event_id in self._by_trace.get(trace_id, [])
        )

    def _require_open_locked(self) -> None:
        if self._closed:
            raise TraceStoreClosedError("trace store is closed")


class SQLiteTraceStore:
    """SQLite WAL authority for immutable correlated trace events."""

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
            self._verify_database_integrity()
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

    def append(self, candidate: TraceEventCandidate) -> TraceAppend:
        validated = _validated_candidate(candidate)
        event_id = event_id_for_candidate(validated)
        trace_id = trace_id_for_request(validated.request_id)
        with self._lock:
            self._require_healthy_locked()
            existing = self._get_optional_event_locked(event_id)
            if existing is not None:
                _require_same_event(
                    existing,
                    materialize_trace_event(
                        validated,
                        causal_sequence=existing.causal_sequence,
                    ),
                )
                return TraceAppend(kind=TraceAppendKind.REPLAY, record=existing)
            try:
                with self._transaction():
                    row = self._connection.execute(
                        """
                        SELECT COALESCE(MAX(causal_sequence), 0) AS latest
                        FROM trace_events
                        WHERE trace_id = ?
                        """,
                        (str(trace_id),),
                    ).fetchone()
                    latest = int(row["latest"]) if row is not None else 0
                    record = materialize_trace_event(
                        validated,
                        causal_sequence=latest + 1,
                    )
                    payload_json, payload_hash = _encoded_record(record)
                    self._connection.execute(
                        """
                        INSERT INTO trace_events (
                            event_id,
                            trace_id,
                            request_id,
                            causal_sequence,
                            occurred_at_ms,
                            kind,
                            phase,
                            invocation_id,
                            context_bundle_id,
                            result_id,
                            cancellation_id,
                            canonical_sha256,
                            privacy,
                            retention,
                            tainted,
                            uncertainty,
                            payload_json,
                            payload_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(record.event_id),
                            str(record.trace_id),
                            str(record.request_id),
                            record.causal_sequence,
                            record.occurred_at_ms,
                            record.kind.value,
                            record.phase.value,
                            _uuid_text(record.invocation_id),
                            _uuid_text(record.context_bundle_id),
                            _uuid_text(record.result_id),
                            _uuid_text(record.cancellation_id),
                            record.canonical_sha256,
                            record.privacy.value,
                            record.retention.value,
                            int(record.tainted),
                            record.uncertainty.value,
                            payload_json,
                            payload_hash,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                current = self._get_optional_event_locked(event_id)
                if current is not None:
                    _require_same_event(
                        current,
                        materialize_trace_event(
                            validated,
                            causal_sequence=current.causal_sequence,
                        ),
                    )
                    return TraceAppend(kind=TraceAppendKind.REPLAY, record=current)
                raise TraceConflictError(
                    "durable trace identity or causal sequence conflicts"
                ) from exc
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not persist trace event", exc)
            return TraceAppend(kind=TraceAppendKind.NEW, record=record)

    def get_event(self, event_id: UUID) -> CorrelatedTraceEvent:
        with self._lock:
            record = self._get_optional_event_locked(event_id)
            if record is None:
                raise TraceNotFoundError(f"trace event {event_id} does not exist")
            return record

    def for_request(self, request_id: UUID) -> tuple[CorrelatedTraceEvent, ...]:
        with self._lock:
            return tuple(
                self._query_locked(
                    where_clause="WHERE request_id = ?",
                    values=(str(request_id),),
                )
            )

    def for_trace(self, trace_id: UUID) -> tuple[CorrelatedTraceEvent, ...]:
        with self._lock:
            return tuple(
                self._query_locked(
                    where_clause="WHERE trace_id = ?",
                    values=(str(trace_id),),
                )
            )

    def load(self) -> list[CorrelatedTraceEvent]:
        with self._lock:
            self._require_healthy_locked()
            self._verify_database_integrity()
            return self._query_locked()

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
                    causal_sequence INTEGER NOT NULL CHECK(causal_sequence > 0),
                    occurred_at_ms INTEGER NOT NULL CHECK(occurred_at_ms >= 0),
                    kind TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    invocation_id TEXT,
                    context_bundle_id TEXT,
                    result_id TEXT,
                    cancellation_id TEXT,
                    canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
                    privacy TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    tainted INTEGER NOT NULL CHECK(tainted IN (0, 1)),
                    uncertainty TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
                    UNIQUE(trace_id, causal_sequence)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS trace_events_request_order
                ON trace_events(request_id, causal_sequence, event_id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS trace_events_invocation
                ON trace_events(invocation_id, event_id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS trace_events_context
                ON trace_events(context_bundle_id, event_id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS trace_events_result
                ON trace_events(result_id, event_id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS trace_events_cancellation
                ON trace_events(cancellation_id, event_id)
                """
            )

    def _get_optional_event_locked(
        self,
        event_id: UUID,
    ) -> CorrelatedTraceEvent | None:
        rows = self._query_locked(
            where_clause="WHERE event_id = ?",
            values=(str(event_id),),
        )
        return rows[0] if rows else None

    def _query_locked(
        self,
        *,
        where_clause: str = "",
        values: tuple[object, ...] = (),
    ) -> list[CorrelatedTraceEvent]:
        self._require_healthy_locked()
        try:
            rows = self._connection.execute(
                self._select_sql(where_clause=where_clause),
                values,
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked("could not read trace events", exc)
        return [self._decode_row(row) for row in rows]

    def _decode_row(self, row: sqlite3.Row) -> CorrelatedTraceEvent:
        payload_json = str(row["payload_json"])
        expected_hash = str(row["payload_sha256"])
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            self._latch_failure_locked(
                TraceStoreCorruptionError("trace payload hash mismatch")
            )
        try:
            payload = json.loads(payload_json)
            record = CorrelatedTraceEvent.model_validate(payload)
        except (json.JSONDecodeError, ValueError):
            self._latch_failure_locked(
                TraceStoreCorruptionError("trace payload is invalid")
            )
        indexed = (
            str(record.event_id),
            str(record.trace_id),
            str(record.request_id),
            record.causal_sequence,
            record.occurred_at_ms,
            record.kind.value,
            record.phase.value,
            _uuid_text(record.invocation_id),
            _uuid_text(record.context_bundle_id),
            _uuid_text(record.result_id),
            _uuid_text(record.cancellation_id),
            record.canonical_sha256,
            record.privacy.value,
            record.retention.value,
            int(record.tainted),
            record.uncertainty.value,
        )
        actual = (
            str(row["event_id"]),
            str(row["trace_id"]),
            str(row["request_id"]),
            int(row["causal_sequence"]),
            int(row["occurred_at_ms"]),
            str(row["kind"]),
            str(row["phase"]),
            row["invocation_id"],
            row["context_bundle_id"],
            row["result_id"],
            row["cancellation_id"],
            str(row["canonical_sha256"]),
            str(row["privacy"]),
            str(row["retention"]),
            int(row["tainted"]),
            str(row["uncertainty"]),
        )
        if indexed != actual:
            self._latch_failure_locked(
                TraceStoreCorruptionError("trace index metadata mismatch")
            )
        return record

    def _select_sql(self, *, where_clause: str = "") -> str:
        return f"""
            SELECT
                event_id,
                trace_id,
                request_id,
                causal_sequence,
                occurred_at_ms,
                kind,
                phase,
                invocation_id,
                context_bundle_id,
                result_id,
                cancellation_id,
                canonical_sha256,
                privacy,
                retention,
                tainted,
                uncertainty,
                payload_json,
                payload_sha256
            FROM trace_events
            {where_clause}
            ORDER BY trace_id, causal_sequence, event_id
        """

    def _verify_database_integrity(self) -> None:
        self._require_healthy_locked()
        try:
            row = self._connection.execute("PRAGMA quick_check").fetchone()
            if row is None or row[0] != "ok":
                self._latch_failure_locked(
                    TraceStoreCorruptionError("trace database integrity check failed")
                )
            rows = self._connection.execute(self._select_sql()).fetchall()
            for item in rows:
                self._decode_row(item)
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "trace database integrity check failed",
                exc,
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _require_healthy_locked(self) -> None:
        if self._closed:
            raise TraceStoreClosedError("trace store is closed")
        if self._failure is not None:
            raise TraceStoreUnhealthyError("trace store is unhealthy") from self._failure

    def _raise_database_failure_locked(
        self,
        message: str,
        exc: sqlite3.DatabaseError,
    ) -> NoReturn:
        failure = TraceStoreCorruptionError(message)
        self._failure = failure
        raise failure from exc

    def _latch_failure_locked(self, failure: TraceStoreError) -> NoReturn:
        self._failure = failure
        raise failure


class TraceStoreRegistry:
    """Process-wide trace authority configured once per Core lifespan."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: TraceStore = InMemoryTraceStore()

    def current(self) -> TraceStore:
        with self._lock:
            return self._store

    def configure(self, store: TraceStore) -> None:
        store.load()
        with self._lock:
            previous = self._store
            self._store = store
        if previous is not store:
            previous.close()

    def reset_to_memory(self) -> None:
        replacement = InMemoryTraceStore()
        with self._lock:
            previous = self._store
            self._store = replacement
        previous.close()


trace_store_registry = TraceStoreRegistry()


def _validated_candidate(candidate: TraceEventCandidate) -> TraceEventCandidate:
    return TraceEventCandidate.model_validate(candidate.model_dump(mode="json"))


def _require_same_event(
    existing: CorrelatedTraceEvent,
    candidate: CorrelatedTraceEvent,
) -> None:
    if existing.model_dump(mode="json") != candidate.model_dump(mode="json"):
        raise TraceConflictError(
            "trace event slot conflicts with an existing immutable event"
        )


def _encoded_record(record: CorrelatedTraceEvent) -> tuple[str, str]:
    payload_json = canonical_json(record)
    return payload_json, hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _uuid_text(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "TRACE_STORE_SCHEMA_VERSION",
    "InMemoryTraceStore",
    "SQLiteTraceStore",
    "TraceAppend",
    "TraceAppendKind",
    "TraceConflictError",
    "TraceNotFoundError",
    "TraceStore",
    "TraceStoreClosedError",
    "TraceStoreCorruptionError",
    "TraceStoreError",
    "TraceStoreInUseError",
    "TraceStoreRegistry",
    "TraceStoreSchemaError",
    "TraceStoreUnhealthyError",
    "trace_store_registry",
]
