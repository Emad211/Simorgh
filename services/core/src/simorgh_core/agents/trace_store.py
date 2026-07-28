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
    StoredTraceEvent,
    TraceEventDraft,
    TraceGap,
    TraceProjection,
    build_trace_projection,
    stored_trace_event,
    trace_draft_fingerprint,
    trace_id_for,
)

TRACE_STORE_SCHEMA_VERSION: Literal[1] = 1


class TraceStoreError(RuntimeError):
    """Base class for deterministic durable trace-store failures."""


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
    event: StoredTraceEvent


class TraceStore(Protocol):
    def append(self, draft: TraceEventDraft) -> TraceAppend: ...

    def for_request(self, request_id: UUID) -> tuple[StoredTraceEvent, ...]: ...

    def project(
        self,
        request_id: UUID,
        *,
        gaps: tuple[TraceGap, ...] = (),
    ) -> TraceProjection: ...

    def load(self) -> list[StoredTraceEvent]: ...

    def close(self) -> None: ...


class InMemoryTraceStore:
    """Strict process-local implementation of the correlated trace authority."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: dict[UUID, StoredTraceEvent] = {}
        self._by_trace: dict[UUID, list[StoredTraceEvent]] = {}
        self._closed = False

    def append(self, draft: TraceEventDraft) -> TraceAppend:
        candidate = _validated_draft(draft)
        with self._lock:
            self._require_open_locked()
            existing = self._events.get(candidate.event_id)
            if existing is not None:
                _require_same_logical_event(existing, candidate)
                return TraceAppend(kind=TraceAppendKind.REPLAY, event=existing)
            trace_events = self._by_trace.setdefault(candidate.trace_id, [])
            event = stored_trace_event(candidate, sequence=len(trace_events) + 1)
            trace_events.append(event)
            self._events[event.event_id] = event
            return TraceAppend(kind=TraceAppendKind.NEW, event=event)

    def for_request(self, request_id: UUID) -> tuple[StoredTraceEvent, ...]:
        trace_id = trace_id_for(request_id)
        with self._lock:
            self._require_open_locked()
            events = self._by_trace.get(trace_id)
            if not events:
                raise TraceNotFoundError(f"request {request_id} has no trace")
            return tuple(events)

    def project(
        self,
        request_id: UUID,
        *,
        gaps: tuple[TraceGap, ...] = (),
    ) -> TraceProjection:
        return build_trace_projection(self.for_request(request_id), gaps=gaps)

    def load(self) -> list[StoredTraceEvent]:
        with self._lock:
            self._require_open_locked()
            return sorted(
                self._events.values(),
                key=lambda event: (str(event.trace_id), event.sequence),
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _require_open_locked(self) -> None:
        if self._closed:
            raise TraceStoreClosedError("trace store is closed")


class SQLiteTraceStore:
    """SQLite WAL authority for privacy-safe correlated trace events."""

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

    def append(self, draft: TraceEventDraft) -> TraceAppend:
        candidate = _validated_draft(draft)
        with self._lock:
            self._require_healthy_locked()
            existing = self._get_event_optional_locked(candidate.event_id)
            if existing is not None:
                _require_same_logical_event(existing, candidate)
                return TraceAppend(kind=TraceAppendKind.REPLAY, event=existing)

            try:
                with self._transaction():
                    row = self._connection.execute(
                        """
                        SELECT COALESCE(MAX(sequence), 0) AS last_sequence
                        FROM trace_events
                        WHERE trace_id = ?
                        """,
                        (str(candidate.trace_id),),
                    ).fetchone()
                    sequence = int(row["last_sequence"]) + 1
                    event = stored_trace_event(candidate, sequence=sequence)
                    payload_json, payload_hash = _encoded_event(event)
                    self._connection.execute(
                        """
                        INSERT INTO trace_events (
                            event_id,
                            trace_id,
                            request_id,
                            sequence,
                            kind,
                            occurred_at_ms,
                            canonical_sha256,
                            payload_json,
                            payload_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(event.event_id),
                            str(event.trace_id),
                            str(event.request_id),
                            event.sequence,
                            event.kind.value,
                            event.occurred_at_ms,
                            event.canonical_sha256,
                            payload_json,
                            payload_hash,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                current = self._get_event_optional_locked(candidate.event_id)
                if current is not None:
                    _require_same_logical_event(current, candidate)
                    return TraceAppend(kind=TraceAppendKind.REPLAY, event=current)
                raise TraceConflictError(
                    "durable trace event identity or sequence conflicts with an existing row"
                ) from exc
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not append trace event", exc)
            return TraceAppend(kind=TraceAppendKind.NEW, event=event)

    def for_request(self, request_id: UUID) -> tuple[StoredTraceEvent, ...]:
        with self._lock:
            self._require_healthy_locked()
            try:
                rows = self._connection.execute(
                    self._select_sql(where_clause="WHERE request_id = ?"),
                    (str(request_id),),
                ).fetchall()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not read request trace", exc)
            if not rows:
                raise TraceNotFoundError(f"request {request_id} has no trace")
            return tuple(self._decode_row(row) for row in rows)

    def project(
        self,
        request_id: UUID,
        *,
        gaps: tuple[TraceGap, ...] = (),
    ) -> TraceProjection:
        return build_trace_projection(self.for_request(request_id), gaps=gaps)

    def load(self) -> list[StoredTraceEvent]:
        with self._lock:
            self._require_healthy_locked()
            self._verify_database_integrity()
            try:
                rows = self._connection.execute(self._select_sql()).fetchall()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not read trace events", exc)
            return [self._decode_row(row) for row in rows]

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
                    kind TEXT NOT NULL,
                    occurred_at_ms INTEGER NOT NULL CHECK(occurred_at_ms >= 0),
                    canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
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

    def _get_event_optional_locked(self, event_id: UUID) -> StoredTraceEvent | None:
        self._require_healthy_locked()
        try:
            row = self._connection.execute(
                self._select_sql(where_clause="WHERE event_id = ?"),
                (str(event_id),),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked("could not read trace event", exc)
        return self._decode_row(row) if row is not None else None

    def _decode_row(self, row: sqlite3.Row) -> StoredTraceEvent:
        payload_json = str(row["payload_json"])
        expected_hash = str(row["payload_sha256"])
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            self._latch_corruption_locked("trace payload hash mismatch")
        try:
            decoded = json.loads(payload_json)
            event = StoredTraceEvent.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValueError):
            self._latch_corruption_locked("trace payload contract is invalid")
        indexed_identity = (
            str(event.event_id),
            str(event.trace_id),
            str(event.request_id),
            event.sequence,
            event.kind.value,
            event.occurred_at_ms,
            event.canonical_sha256,
        )
        row_identity = tuple(row[key] for key in _INDEXED_COLUMNS)
        if indexed_identity != row_identity:
            self._latch_corruption_locked("trace indexed columns do not match payload")
        return event

    @staticmethod
    def _select_sql(*, where_clause: str = "") -> str:
        return f"""
            SELECT
                event_id,
                trace_id,
                request_id,
                sequence,
                kind,
                occurred_at_ms,
                canonical_sha256,
                payload_json,
                payload_sha256
            FROM trace_events
            {where_clause}
            ORDER BY trace_id, sequence
        """

    def _verify_database_integrity(self) -> None:
        self._require_not_closed_locked()
        try:
            result = self._connection.execute("PRAGMA quick_check").fetchall()
            rows = self._connection.execute(self._select_sql()).fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not verify trace database integrity",
                exc,
            )
        if [str(row[0]) for row in result] != ["ok"]:
            self._latch_corruption_locked("trace database integrity check failed")
        previous_by_trace: dict[str, int] = {}
        for row in rows:
            event = self._decode_row(row)
            previous = previous_by_trace.get(str(event.trace_id), 0)
            if event.sequence != previous + 1:
                self._latch_corruption_locked("trace sequence is not contiguous")
            previous_by_trace[str(event.trace_id)] = event.sequence

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

_INDEXED_COLUMNS = (
    "event_id",
    "trace_id",
    "request_id",
    "sequence",
    "kind",
    "occurred_at_ms",
    "canonical_sha256",
)


def _validated_draft(draft: TraceEventDraft) -> TraceEventDraft:
    try:
        return TraceEventDraft.model_validate(draft.model_dump(mode="json"))
    except ValueError:
        raise TraceConflictError("trace draft failed authoritative contract validation") from None


def _require_same_logical_event(
    existing: StoredTraceEvent,
    candidate: TraceEventDraft,
) -> None:
    if trace_draft_fingerprint(existing) != trace_draft_fingerprint(candidate):
        raise TraceConflictError(
            "trace event identity was reused with different authoritative metadata"
        )


def _encoded_event(event: StoredTraceEvent) -> tuple[str, str]:
    payload_json = canonical_json(event)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return payload_json, payload_hash


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
