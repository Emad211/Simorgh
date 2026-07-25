from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import (
    InvocationConflictError,
    InvocationEffect,
    InvocationKind,
    InvocationNotFoundError,
    InvocationPhase,
    InvocationRecord,
    InvocationStart,
    InvocationStartKind,
    InvocationStateError,
    InvocationStore,
    InvocationStoreClosedError,
    InvocationStoreCorruptionError,
    InvocationStoreError,
    InvocationStoreSchemaError,
    InvocationStoreUnhealthyError,
    InMemoryInvocationStore,
    canonical_fingerprint,
    canonical_json,
    require_same_invocation_identity,
    start_kind_for_record,
    unknown_record,
    validated_record_copy,
)

INVOCATION_STORE_SCHEMA_VERSION: Literal[1] = 1
_ZERO_USAGE = UsageVector()

_ALLOWED_TRANSITIONS: dict[InvocationPhase, frozenset[InvocationPhase]] = {
    InvocationPhase.PENDING: frozenset(
        {
            InvocationPhase.PENDING,
            InvocationPhase.RESERVED,
            InvocationPhase.COMPLETED,
            InvocationPhase.FAILED,
            InvocationPhase.CANCELLED,
            InvocationPhase.EXPIRED,
            InvocationPhase.UNKNOWN,
            InvocationPhase.UNKNOWN_SIDE_EFFECT,
        }
    ),
    InvocationPhase.RESERVED: frozenset(
        {
            InvocationPhase.RESERVED,
            InvocationPhase.COMPLETED,
            InvocationPhase.FAILED,
            InvocationPhase.UNKNOWN,
            InvocationPhase.UNKNOWN_SIDE_EFFECT,
        }
    ),
    InvocationPhase.COMPLETED: frozenset({InvocationPhase.COMPLETED}),
    InvocationPhase.FAILED: frozenset({InvocationPhase.FAILED}),
    InvocationPhase.CANCELLED: frozenset({InvocationPhase.CANCELLED}),
    InvocationPhase.EXPIRED: frozenset({InvocationPhase.EXPIRED}),
    InvocationPhase.UNKNOWN: frozenset({InvocationPhase.UNKNOWN}),
    InvocationPhase.UNKNOWN_SIDE_EFFECT: frozenset(
        {InvocationPhase.UNKNOWN_SIDE_EFFECT}
    ),
}


class SQLiteInvocationStore:
    """SQLite WAL authority for model, tool and specialist invocation identity."""

    def __init__(
        self,
        path: str | Path,
        *,
        wall_clock_millis: Callable[[], int] | None = None,
        recover_interrupted: bool = True,
    ) -> None:
        raw_path = str(path)
        self._path = (
            ":memory:"
            if raw_path == ":memory:"
            else str(Path(raw_path).expanduser().resolve())
        )
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )
        self._lock = threading.RLock()
        self._closed = False
        self._failure: InvocationStoreError | None = None

        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        connection: sqlite3.Connection | None = None
        try:
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
            if recover_interrupted:
                self._recover_interrupted_locked()
        except InvocationStoreError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise InvocationStoreCorruptionError(
                f"could not initialize invocation store at {self._path}"
            ) from exc

    @property
    def path(self) -> str:
        return self._path

    def begin(
        self,
        *,
        invocation_id: UUID,
        request_id: UUID,
        agent_id: str,
        agent_version: str,
        operation: str,
        input_fingerprint: str,
        kind: InvocationKind = InvocationKind.SPECIALIST,
        effect: InvocationEffect = InvocationEffect.READ_ONLY,
        provider_id: str | None = None,
        model_id: str | None = None,
        tool_id: str | None = None,
        connector_id: str | None = None,
        parent_invocation_id: UUID | None = None,
        attempt: int = 1,
    ) -> InvocationStart:
        with self._lock:
            self._require_healthy_locked()
            existing = self._get_optional_locked(invocation_id)
            if existing is not None:
                require_same_invocation_identity(
                    existing=existing,
                    request_id=request_id,
                    agent_id=agent_id,
                    agent_version=agent_version,
                    operation=operation,
                    input_fingerprint=input_fingerprint,
                    kind=kind,
                    effect=effect,
                    provider_id=provider_id,
                    model_id=model_id,
                    tool_id=tool_id,
                    connector_id=connector_id,
                    parent_invocation_id=parent_invocation_id,
                    attempt=attempt,
                )
                return InvocationStart(
                    kind=start_kind_for_record(existing),
                    record=existing,
                )

            now = self._now_ms()
            record = InvocationRecord(
                invocation_id=invocation_id,
                request_id=request_id,
                agent_id=agent_id,
                agent_version=agent_version,
                operation=operation,
                input_fingerprint=input_fingerprint,
                kind=kind,
                effect=effect,
                provider_id=provider_id,
                model_id=model_id,
                tool_id=tool_id,
                connector_id=connector_id,
                parent_invocation_id=parent_invocation_id,
                state=InvocationPhase.PENDING,
                attempt=attempt,
                created_at_ms=now,
                updated_at_ms=now,
            )
            self._insert_locked(record)
            return InvocationStart(kind=InvocationStartKind.NEW, record=record)

    def reserve(
        self,
        *,
        invocation_id: UUID,
        usage: UsageVector,
    ) -> InvocationRecord:
        if usage == _ZERO_USAGE:
            raise ValueError("invocation reservation usage cannot be zero")
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationPhase.RESERVED:
                if existing.reserved_usage != usage:
                    raise InvocationConflictError(
                        "invocation reservation was replayed with different usage"
                    )
                return existing
            if existing.state != InvocationPhase.PENDING:
                raise InvocationStateError(
                    f"cannot reserve invocation in state {existing.state.value}"
                )
            candidate = validated_record_copy(
                existing,
                state=InvocationPhase.RESERVED,
                reserved_usage=usage,
                updated_at_ms=self._next_time(existing.updated_at_ms),
            )
            self._update_locked(existing, candidate)
            return candidate

    def complete(
        self,
        *,
        invocation_id: UUID,
        result_payload: dict[str, object],
        committed_usage: UsageVector = _ZERO_USAGE,
    ) -> InvocationRecord:
        result_dict = dict(result_payload)
        result_hash = canonical_fingerprint(result_dict)
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationPhase.COMPLETED:
                if (
                    existing.result_payload != result_dict
                    or existing.committed_usage != committed_usage
                ):
                    raise InvocationConflictError(
                        "completed invocation was replayed with different result or usage"
                    )
                return existing
            if existing.state not in {
                InvocationPhase.PENDING,
                InvocationPhase.RESERVED,
            }:
                raise InvocationStateError(
                    f"cannot complete invocation in state {existing.state.value}"
                )
            candidate = validated_record_copy(
                existing,
                state=InvocationPhase.COMPLETED,
                reserved_usage=_ZERO_USAGE,
                committed_usage=committed_usage,
                result_payload=result_dict,
                result_payload_sha256=result_hash,
                failure_code=None,
                failure_detail=None,
                updated_at_ms=self._next_time(existing.updated_at_ms),
            )
            self._update_locked(existing, candidate)
            return candidate

    def fail(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
        committed_usage: UsageVector | None = None,
    ) -> InvocationRecord:
        normalized_code = failure_code.strip()[:128]
        if not normalized_code:
            raise ValueError("failure_code cannot be empty")
        normalized_detail = failure_detail.strip()[:2_000]
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            usage = _terminal_usage(existing, committed_usage)
            if existing.state == InvocationPhase.FAILED:
                if (
                    existing.failure_code != normalized_code
                    or existing.failure_detail != normalized_detail
                    or existing.committed_usage != usage
                ):
                    raise InvocationConflictError(
                        "failed invocation was replayed with different terminal content"
                    )
                return existing
            if existing.state not in {
                InvocationPhase.PENDING,
                InvocationPhase.RESERVED,
            }:
                raise InvocationStateError(
                    f"cannot fail invocation in state {existing.state.value}"
                )
            candidate = validated_record_copy(
                existing,
                state=InvocationPhase.FAILED,
                reserved_usage=_ZERO_USAGE,
                committed_usage=usage,
                failure_code=normalized_code,
                failure_detail=normalized_detail or None,
                updated_at_ms=self._next_time(existing.updated_at_ms),
            )
            self._update_locked(existing, candidate)
            return candidate

    def mark_unknown(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state in {
                InvocationPhase.UNKNOWN,
                InvocationPhase.UNKNOWN_SIDE_EFFECT,
            }:
                return existing
            if existing.state not in {
                InvocationPhase.PENDING,
                InvocationPhase.RESERVED,
            }:
                raise InvocationStateError(
                    f"cannot mark invocation unknown in state {existing.state.value}"
                )
            candidate = unknown_record(
                existing,
                failure_code=failure_code,
                failure_detail=failure_detail,
                updated_at_ms=self._next_time(existing.updated_at_ms),
            )
            self._update_locked(existing, candidate)
            return candidate

    def cancel(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationPhase.CANCELLED:
                return existing
            if existing.state == InvocationPhase.PENDING:
                candidate = validated_record_copy(
                    existing,
                    state=InvocationPhase.CANCELLED,
                    failure_code="cancelled",
                    failure_detail="invocation cancelled before external reservation",
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            elif existing.state == InvocationPhase.RESERVED:
                candidate = unknown_record(
                    existing,
                    failure_code="cancelled_after_reservation",
                    failure_detail=(
                        "invocation cancelled after external-call budget reservation; "
                        "completion is uncertain"
                    ),
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            else:
                raise InvocationStateError(
                    f"cannot cancel invocation in state {existing.state.value}"
                )
            self._update_locked(existing, candidate)
            return candidate

    def expire(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            existing = self._require_record_locked(invocation_id)
            if existing.state == InvocationPhase.EXPIRED:
                return existing
            if existing.state == InvocationPhase.PENDING:
                candidate = validated_record_copy(
                    existing,
                    state=InvocationPhase.EXPIRED,
                    failure_code="expired",
                    failure_detail="invocation expired before external reservation",
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            elif existing.state == InvocationPhase.RESERVED:
                candidate = unknown_record(
                    existing,
                    failure_code="expired_after_reservation",
                    failure_detail=(
                        "invocation expired after external-call budget reservation; "
                        "completion is uncertain"
                    ),
                    updated_at_ms=self._next_time(existing.updated_at_ms),
                )
            else:
                raise InvocationStateError(
                    f"cannot expire invocation in state {existing.state.value}"
                )
            self._update_locked(existing, candidate)
            return candidate

    def get(self, invocation_id: UUID) -> InvocationRecord:
        with self._lock:
            return self._require_record_locked(invocation_id)

    def load(self) -> list[InvocationRecord]:
        with self._lock:
            self._require_healthy_locked()
            self._verify_database_integrity()
            try:
                rows = self._connection.execute(self._select_sql()).fetchall()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not read invocation records",
                    exc,
                )
            return [self._decode_row(row) for row in rows]

    def clear(self) -> None:
        with self._lock:
            self._require_healthy_locked()
            try:
                with self._transaction():
                    self._connection.execute("DELETE FROM invocation_records")
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked(
                    "could not clear invocation store",
                    exc,
                )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._connection.close()

    def _recover_interrupted_locked(self) -> None:
        try:
            with self._transaction():
                rows = self._connection.execute(
                    self._select_sql(
                        where_clause="WHERE state IN ('pending', 'reserved')"
                    )
                ).fetchall()
                now = self._now_ms()
                for row in rows:
                    existing = self._decode_row(row)
                    candidate = unknown_record(
                        existing,
                        failure_code="process_interrupted",
                        failure_detail=(
                            "Core restarted before invocation completion; automatic "
                            "retry is blocked"
                        ),
                        updated_at_ms=max(existing.updated_at_ms, now),
                    )
                    self._update_row_locked(candidate)
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not recover interrupted invocations",
                exc,
            )

    def _initialize_schema(self) -> None:
        with self._transaction():
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS invocation_store_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            row = self._connection.execute(
                """
                SELECT value
                FROM invocation_store_metadata
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO invocation_store_metadata(key, value)
                    VALUES('schema_version', ?)
                    """,
                    (str(INVOCATION_STORE_SCHEMA_VERSION),),
                )
            elif row["value"] != str(INVOCATION_STORE_SCHEMA_VERSION):
                raise InvocationStoreSchemaError(
                    "unsupported invocation store schema version " + str(row["value"])
                )

            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS invocation_records (
                    invocation_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL
                        CHECK(length(input_fingerprint) = 64),
                    kind TEXT NOT NULL,
                    effect TEXT NOT NULL,
                    provider_id TEXT,
                    model_id TEXT,
                    tool_id TEXT,
                    connector_id TEXT,
                    parent_invocation_id TEXT,
                    attempt INTEGER NOT NULL CHECK(attempt >= 1),
                    state TEXT NOT NULL,
                    terminal INTEGER NOT NULL CHECK(terminal IN (0, 1)),
                    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
                    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= created_at_ms),
                    result_payload_sha256 TEXT,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS invocation_records_request_order
                ON invocation_records(request_id, created_at_ms, invocation_id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS invocation_records_state_order
                ON invocation_records(state, updated_at_ms, invocation_id)
                """
            )

    def _insert_locked(self, record: InvocationRecord) -> None:
        payload_json, payload_hash = _encoded_record(record)
        try:
            with self._transaction():
                self._connection.execute(
                    """
                    INSERT INTO invocation_records (
                        invocation_id,
                        request_id,
                        agent_id,
                        agent_version,
                        operation,
                        input_fingerprint,
                        kind,
                        effect,
                        provider_id,
                        model_id,
                        tool_id,
                        connector_id,
                        parent_invocation_id,
                        attempt,
                        state,
                        terminal,
                        created_at_ms,
                        updated_at_ms,
                        result_payload_sha256,
                        payload_json,
                        payload_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _row_values(record, payload_json, payload_hash),
                )
        except sqlite3.IntegrityError as exc:
            raise InvocationConflictError(
                "durable invocation identity conflicts with an existing row"
            ) from exc
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not persist new invocation",
                exc,
            )

    def _update_locked(
        self,
        existing: InvocationRecord,
        candidate: InvocationRecord,
    ) -> None:
        validate_invocation_transition(existing, candidate)
        try:
            with self._transaction():
                current_row = self._connection.execute(
                    self._select_sql(where_clause="WHERE invocation_id = ?"),
                    (str(existing.invocation_id),),
                ).fetchone()
                if current_row is None:
                    raise InvocationStoreCorruptionError(
                        "durable invocation disappeared during transition"
                    )
                current = self._decode_row(current_row)
                if current != existing:
                    raise InvocationConflictError(
                        "durable invocation changed concurrently"
                    )
                self._update_row_locked(candidate)
        except (InvocationConflictError, InvocationStoreCorruptionError):
            raise
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not persist invocation transition",
                exc,
            )

    def _update_row_locked(self, record: InvocationRecord) -> None:
        payload_json, payload_hash = _encoded_record(record)
        self._connection.execute(
            """
            UPDATE invocation_records SET
                state = ?,
                terminal = ?,
                updated_at_ms = ?,
                result_payload_sha256 = ?,
                payload_json = ?,
                payload_sha256 = ?
            WHERE invocation_id = ?
            """,
            (
                record.state.value,
                int(record.terminal),
                record.updated_at_ms,
                record.result_payload_sha256,
                payload_json,
                payload_hash,
                str(record.invocation_id),
            ),
        )

    def _require_record_locked(self, invocation_id: UUID) -> InvocationRecord:
        self._require_healthy_locked()
        record = self._get_optional_locked(invocation_id)
        if record is None:
            raise InvocationNotFoundError(f"invocation {invocation_id} does not exist")
        return record

    def _get_optional_locked(self, invocation_id: UUID) -> InvocationRecord | None:
        self._require_healthy_locked()
        try:
            row = self._connection.execute(
                self._select_sql(where_clause="WHERE invocation_id = ?"),
                (str(invocation_id),),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not read invocation record",
                exc,
            )
        return self._decode_row(row) if row is not None else None

    def _decode_row(self, row: sqlite3.Row) -> InvocationRecord:
        payload_json = row["payload_json"]
        expected_hash = row["payload_sha256"]
        actual_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        if actual_hash != expected_hash:
            self._latch_corruption_locked("invocation payload hash mismatch")
        try:
            decoded = json.loads(payload_json)
            record = InvocationRecord.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._latch_corruption_locked("invocation payload contract is invalid", exc)

        column_identity = (
            str(record.invocation_id),
            str(record.request_id),
            record.agent_id,
            record.agent_version,
            record.operation,
            record.input_fingerprint,
            record.kind.value,
            record.effect.value,
            record.provider_id,
            record.model_id,
            record.tool_id,
            record.connector_id,
            str(record.parent_invocation_id) if record.parent_invocation_id else None,
            record.attempt,
            record.state.value,
            int(record.terminal),
            record.created_at_ms,
            record.updated_at_ms,
            record.result_payload_sha256,
        )
        row_identity = tuple(row[key] for key in _INDEXED_COLUMNS)
        if column_identity != row_identity:
            self._latch_corruption_locked(
                "invocation indexed columns do not match payload"
            )
        return record

    @staticmethod
    def _select_sql(*, where_clause: str = "") -> str:
        return f"""
            SELECT
                invocation_id,
                request_id,
                agent_id,
                agent_version,
                operation,
                input_fingerprint,
                kind,
                effect,
                provider_id,
                model_id,
                tool_id,
                connector_id,
                parent_invocation_id,
                attempt,
                state,
                terminal,
                created_at_ms,
                updated_at_ms,
                result_payload_sha256,
                payload_json,
                payload_sha256
            FROM invocation_records
            {where_clause}
            ORDER BY created_at_ms, invocation_id
        """

    def _verify_database_integrity(self) -> None:
        self._require_not_closed_locked()
        try:
            rows = self._connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not verify invocation database integrity",
                exc,
            )
        messages = [str(row[0]) for row in rows]
        if messages != ["ok"]:
            self._latch_corruption_locked(
                "invocation database integrity check failed"
            )

    def _require_healthy_locked(self) -> None:
        self._require_not_closed_locked()
        if self._failure is not None:
            raise InvocationStoreUnhealthyError(
                "invocation store is unhealthy after a durable operation failure"
            ) from self._failure

    def _require_not_closed_locked(self) -> None:
        if self._closed:
            raise InvocationStoreClosedError("invocation store is closed")

    def _raise_database_failure_locked(
        self,
        message: str,
        exc: sqlite3.DatabaseError,
    ) -> None:
        failure = InvocationStoreCorruptionError(message)
        if self._failure is None:
            self._failure = failure
        raise failure from exc

    def _latch_corruption_locked(
        self,
        message: str,
        exc: BaseException | None = None,
    ) -> None:
        failure = InvocationStoreCorruptionError(message)
        if self._failure is None:
            self._failure = failure
        if exc is None:
            raise failure
        raise failure from exc

    def _next_time(self, previous_updated_at_ms: int) -> int:
        return max(previous_updated_at_ms, self._now_ms())

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))

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


class InvocationStoreRegistry:
    """Process-wide holder configured once per Core application lifespan."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: InvocationStore = InMemoryInvocationStore()

    def current(self) -> InvocationStore:
        with self._lock:
            return self._store

    def configure(self, store: InvocationStore) -> None:
        store.load()
        with self._lock:
            previous = self._store
            self._store = store
        if previous is not store:
            previous.close()

    def reset_to_memory(self) -> None:
        replacement = InMemoryInvocationStore()
        with self._lock:
            previous = self._store
            self._store = replacement
        previous.close()


invocation_store_registry = InvocationStoreRegistry()


_INDEXED_COLUMNS = (
    "invocation_id",
    "request_id",
    "agent_id",
    "agent_version",
    "operation",
    "input_fingerprint",
    "kind",
    "effect",
    "provider_id",
    "model_id",
    "tool_id",
    "connector_id",
    "parent_invocation_id",
    "attempt",
    "state",
    "terminal",
    "created_at_ms",
    "updated_at_ms",
    "result_payload_sha256",
)


def validate_invocation_transition(
    existing: InvocationRecord,
    candidate: InvocationRecord,
) -> None:
    immutable_existing = (
        existing.invocation_id,
        existing.request_id,
        existing.agent_id,
        existing.agent_version,
        existing.operation,
        existing.input_fingerprint,
        existing.kind,
        existing.effect,
        existing.provider_id,
        existing.model_id,
        existing.tool_id,
        existing.connector_id,
        existing.parent_invocation_id,
        existing.attempt,
        existing.created_at_ms,
    )
    immutable_candidate = (
        candidate.invocation_id,
        candidate.request_id,
        candidate.agent_id,
        candidate.agent_version,
        candidate.operation,
        candidate.input_fingerprint,
        candidate.kind,
        candidate.effect,
        candidate.provider_id,
        candidate.model_id,
        candidate.tool_id,
        candidate.connector_id,
        candidate.parent_invocation_id,
        candidate.attempt,
        candidate.created_at_ms,
    )
    if immutable_existing != immutable_candidate:
        raise InvocationConflictError("durable invocation identity is immutable")
    if candidate.updated_at_ms < existing.updated_at_ms:
        raise InvocationConflictError(
            "durable invocation updated_at_ms cannot move backwards"
        )
    if candidate.state not in _ALLOWED_TRANSITIONS[existing.state]:
        raise InvocationStateError(
            f"invalid durable invocation transition {existing.state.value} "
            f"-> {candidate.state.value}"
        )
    _require_usage_not_decreased(
        existing=existing.committed_usage,
        candidate=candidate.committed_usage,
    )
    if existing.result_payload is not None:
        if (
            candidate.result_payload != existing.result_payload
            or candidate.result_payload_sha256 != existing.result_payload_sha256
        ):
            raise InvocationConflictError(
                "durable invocation result content is immutable"
            )
    if existing.failure_code is not None:
        if (
            candidate.failure_code != existing.failure_code
            or candidate.failure_detail != existing.failure_detail
        ):
            raise InvocationConflictError(
                "durable invocation terminal failure metadata is immutable"
            )


def _terminal_usage(
    record: InvocationRecord,
    committed_usage: UsageVector | None,
) -> UsageVector:
    if committed_usage is not None:
        return committed_usage
    if record.state == InvocationPhase.RESERVED:
        return record.reserved_usage
    return record.committed_usage


def _require_usage_not_decreased(
    *,
    existing: UsageVector,
    candidate: UsageVector,
) -> None:
    for dimension in (
        "model_calls",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "estimated_cost_microusd",
        "retries",
        "parallel_branches",
    ):
        if getattr(candidate, dimension) < getattr(existing, dimension):
            raise InvocationConflictError(
                f"durable committed usage dimension {dimension} cannot decrease"
            )


def _encoded_record(record: InvocationRecord) -> tuple[str, str]:
    payload_json = canonical_json(record)
    return payload_json, hashlib.sha256(payload_json.encode()).hexdigest()


def _row_values(
    record: InvocationRecord,
    payload_json: str,
    payload_hash: str,
) -> tuple[object, ...]:
    return (
        str(record.invocation_id),
        str(record.request_id),
        record.agent_id,
        record.agent_version,
        record.operation,
        record.input_fingerprint,
        record.kind.value,
        record.effect.value,
        record.provider_id,
        record.model_id,
        record.tool_id,
        record.connector_id,
        str(record.parent_invocation_id) if record.parent_invocation_id else None,
        record.attempt,
        record.state.value,
        int(record.terminal),
        record.created_at_ms,
        record.updated_at_ms,
        record.result_payload_sha256,
        payload_json,
        payload_hash,
    )
