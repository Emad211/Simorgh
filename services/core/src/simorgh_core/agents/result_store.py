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

from simorgh_core.agents.invocations import canonical_fingerprint, canonical_json
from simorgh_core.agents.result_authority import (
    AuthoritativeSpecialistResult,
    ResultReplayDisposition,
)
from simorgh_core.agents.store_lock import (
    ExclusiveStoreLock,
    ExclusiveStoreLockError,
    ExclusiveStoreLockInUseError,
)

RESULT_STORE_SCHEMA_VERSION: Literal[1] = 1


class ResultStoreError(RuntimeError):
    """Base class for deterministic result-store failures."""


class ResultConflictError(ResultStoreError):
    pass


class ResultNotFoundError(ResultStoreError):
    pass


class ResultStoreClosedError(ResultStoreError):
    pass


class ResultStoreCorruptionError(ResultStoreError):
    pass


class ResultStoreSchemaError(ResultStoreError):
    pass


class ResultStoreUnhealthyError(ResultStoreError):
    pass


class ResultStoreInUseError(ResultStoreError):
    pass


class ResultClaimKind(StrEnum):
    NEW = "new"
    REPLAY = "replay"


class ResultClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: ResultClaimKind
    record: AuthoritativeSpecialistResult


class ResultStore(Protocol):
    def claim(self, record: AuthoritativeSpecialistResult) -> ResultClaim: ...

    def get(self, result_id: UUID) -> AuthoritativeSpecialistResult: ...

    def get_by_invocation(self, invocation_id: UUID) -> AuthoritativeSpecialistResult: ...

    def load(self) -> list[AuthoritativeSpecialistResult]: ...

    def close(self) -> None: ...


class InMemoryResultStore:
    """Strict process-local implementation of the immutable result authority."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[UUID, AuthoritativeSpecialistResult] = {}
        self._by_invocation: dict[UUID, UUID] = {}
        self._closed = False

    def claim(self, record: AuthoritativeSpecialistResult) -> ResultClaim:
        candidate = _validated_fresh_record(record)
        with self._lock:
            self._require_open_locked()
            existing = self._records.get(candidate.result_id)
            existing_result_id = self._by_invocation.get(candidate.invocation_id)
            if existing is None and existing_result_id is not None:
                existing = self._records[existing_result_id]
            if existing is not None:
                _require_same_result(existing, candidate)
                return ResultClaim(kind=ResultClaimKind.REPLAY, record=existing)
            self._records[candidate.result_id] = candidate
            self._by_invocation[candidate.invocation_id] = candidate.result_id
            return ResultClaim(kind=ResultClaimKind.NEW, record=candidate)

    def get(self, result_id: UUID) -> AuthoritativeSpecialistResult:
        with self._lock:
            self._require_open_locked()
            record = self._records.get(result_id)
            if record is None:
                raise ResultNotFoundError(f"result {result_id} does not exist")
            return record

    def get_by_invocation(self, invocation_id: UUID) -> AuthoritativeSpecialistResult:
        with self._lock:
            self._require_open_locked()
            result_id = self._by_invocation.get(invocation_id)
            if result_id is None:
                raise ResultNotFoundError(
                    f"invocation {invocation_id} has no authoritative result"
                )
            return self._records[result_id]

    def load(self) -> list[AuthoritativeSpecialistResult]:
        with self._lock:
            self._require_open_locked()
            return sorted(
                self._records.values(),
                key=lambda record: (record.completed_at_ms, str(record.result_id)),
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _require_open_locked(self) -> None:
        if self._closed:
            raise ResultStoreClosedError("result store is closed")


class SQLiteResultStore:
    """SQLite WAL metadata authority for immutable typed results and references."""

    def __init__(self, path: str | Path) -> None:
        raw_path = str(path)
        self._path = (
            ":memory:"
            if raw_path == ":memory:"
            else str(Path(raw_path).expanduser().resolve())
        )
        self._lock = threading.RLock()
        self._closed = False
        self._failure: ResultStoreError | None = None
        self._path_lock: ExclusiveStoreLock | None = None
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        connection: sqlite3.Connection | None = None
        try:
            if self._path != ":memory:":
                try:
                    self._path_lock = ExclusiveStoreLock(self._path)
                except ExclusiveStoreLockInUseError:
                    raise ResultStoreInUseError(
                        "another Simorgh Core process owns the result store"
                    ) from None
                except ExclusiveStoreLockError:
                    raise ResultStoreUnhealthyError(
                        "result store process lock is unavailable"
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
        except ResultStoreError:
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
            raise ResultStoreCorruptionError("could not initialize result store") from None

    @property
    def path(self) -> str:
        return self._path

    def claim(self, record: AuthoritativeSpecialistResult) -> ResultClaim:
        candidate = _validated_fresh_record(record)
        with self._lock:
            self._require_healthy_locked()
            existing = self._get_optional_locked(result_id=candidate.result_id)
            if existing is None:
                existing = self._get_optional_locked(invocation_id=candidate.invocation_id)
            if existing is not None:
                _require_same_result(existing, candidate)
                return ResultClaim(kind=ResultClaimKind.REPLAY, record=existing)

            payload_json, payload_hash = _encoded_record(candidate)
            try:
                with self._transaction():
                    self._connection.execute(
                        """
                        INSERT INTO result_records (
                            result_id,
                            request_id,
                            invocation_id,
                            producer_agent_id,
                            producer_agent_version,
                            output_contract,
                            result_schema_id,
                            result_schema_version,
                            family,
                            privacy,
                            retention,
                            completed_at_ms,
                            canonical_sha256,
                            payload_json,
                            payload_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(candidate.result_id),
                            str(candidate.request_id),
                            str(candidate.invocation_id),
                            candidate.producer_agent_id,
                            candidate.producer_agent_version,
                            candidate.output_contract,
                            candidate.result_schema_id,
                            candidate.result_schema_version,
                            candidate.family,
                            candidate.privacy.value,
                            candidate.retention.value,
                            candidate.completed_at_ms,
                            candidate.canonical_sha256,
                            payload_json,
                            payload_hash,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                current = self._get_optional_locked(result_id=candidate.result_id)
                if current is None:
                    current = self._get_optional_locked(
                        invocation_id=candidate.invocation_id
                    )
                if current is not None:
                    _require_same_result(current, candidate)
                    return ResultClaim(kind=ResultClaimKind.REPLAY, record=current)
                raise ResultConflictError(
                    "durable result identity conflicts with an existing row"
                ) from exc
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not persist result", exc)
            return ResultClaim(kind=ResultClaimKind.NEW, record=candidate)

    def get(self, result_id: UUID) -> AuthoritativeSpecialistResult:
        with self._lock:
            record = self._get_optional_locked(result_id=result_id)
            if record is None:
                raise ResultNotFoundError(f"result {result_id} does not exist")
            return record

    def get_by_invocation(self, invocation_id: UUID) -> AuthoritativeSpecialistResult:
        with self._lock:
            record = self._get_optional_locked(invocation_id=invocation_id)
            if record is None:
                raise ResultNotFoundError(
                    f"invocation {invocation_id} has no authoritative result"
                )
            return record

    def load(self) -> list[AuthoritativeSpecialistResult]:
        with self._lock:
            self._require_healthy_locked()
            self._verify_database_integrity()
            try:
                rows = self._connection.execute(self._select_sql()).fetchall()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not read result records", exc)
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
                CREATE TABLE IF NOT EXISTS result_store_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            row = self._connection.execute(
                """
                SELECT value
                FROM result_store_metadata
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO result_store_metadata(key, value)
                    VALUES('schema_version', ?)
                    """,
                    (str(RESULT_STORE_SCHEMA_VERSION),),
                )
            elif row["value"] != str(RESULT_STORE_SCHEMA_VERSION):
                raise ResultStoreSchemaError(
                    "unsupported result store schema version " + str(row["value"])
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS result_records (
                    result_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    invocation_id TEXT NOT NULL UNIQUE,
                    producer_agent_id TEXT NOT NULL,
                    producer_agent_version TEXT NOT NULL,
                    output_contract TEXT NOT NULL,
                    result_schema_id TEXT NOT NULL,
                    result_schema_version TEXT NOT NULL,
                    family TEXT NOT NULL,
                    privacy TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    completed_at_ms INTEGER NOT NULL CHECK(completed_at_ms >= 0),
                    canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS result_records_request_order
                ON result_records(request_id, completed_at_ms, result_id)
                """
            )

    def _get_optional_locked(
        self,
        *,
        result_id: UUID | None = None,
        invocation_id: UUID | None = None,
    ) -> AuthoritativeSpecialistResult | None:
        self._require_healthy_locked()
        if (result_id is None) == (invocation_id is None):
            raise ValueError("exactly one result lookup identity is required")
        if result_id is not None:
            where_clause = "WHERE result_id = ?"
            value = str(result_id)
        else:
            where_clause = "WHERE invocation_id = ?"
            value = str(invocation_id)
        try:
            row = self._connection.execute(
                self._select_sql(where_clause=where_clause),
                (value,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked("could not read result record", exc)
        return self._decode_row(row) if row is not None else None

    def _decode_row(self, row: sqlite3.Row) -> AuthoritativeSpecialistResult:
        payload_json = row["payload_json"]
        expected_hash = row["payload_sha256"]
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            self._latch_corruption_locked("result payload hash mismatch")
        try:
            decoded = json.loads(payload_json)
            record = AuthoritativeSpecialistResult.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValueError):
            self._latch_corruption_locked("result payload contract is invalid")
        indexed_identity = (
            str(record.result_id),
            str(record.request_id),
            str(record.invocation_id),
            record.producer_agent_id,
            record.producer_agent_version,
            record.output_contract,
            record.result_schema_id,
            record.result_schema_version,
            record.family,
            record.privacy.value,
            record.retention.value,
            record.completed_at_ms,
            record.canonical_sha256,
        )
        row_identity = tuple(row[key] for key in _INDEXED_COLUMNS)
        if indexed_identity != row_identity:
            self._latch_corruption_locked("result indexed columns do not match payload")
        return record

    @staticmethod
    def _select_sql(*, where_clause: str = "") -> str:
        return f"""
            SELECT
                result_id,
                request_id,
                invocation_id,
                producer_agent_id,
                producer_agent_version,
                output_contract,
                result_schema_id,
                result_schema_version,
                family,
                privacy,
                retention,
                completed_at_ms,
                canonical_sha256,
                payload_json,
                payload_sha256
            FROM result_records
            {where_clause}
            ORDER BY completed_at_ms, result_id
        """

    def _verify_database_integrity(self) -> None:
        self._require_not_closed_locked()
        try:
            rows = self._connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "could not verify result database integrity",
                exc,
            )
        if [str(row[0]) for row in rows] != ["ok"]:
            self._latch_corruption_locked("result database integrity check failed")

    def _require_healthy_locked(self) -> None:
        self._require_not_closed_locked()
        if self._failure is not None:
            raise ResultStoreUnhealthyError(
                "result store is unhealthy after a durable operation failure"
            ) from self._failure

    def _require_not_closed_locked(self) -> None:
        if self._closed:
            raise ResultStoreClosedError("result store is closed")

    def _raise_database_failure_locked(
        self,
        message: str,
        exc: sqlite3.DatabaseError,
    ) -> NoReturn:
        failure = ResultStoreCorruptionError(message)
        if self._failure is None:
            self._failure = failure
        raise failure from exc

    def _latch_corruption_locked(self, message: str) -> NoReturn:
        failure = ResultStoreCorruptionError(message)
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


class ResultStoreRegistry:
    """Process-wide result authority configured once per Core lifespan."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: ResultStore = InMemoryResultStore()

    def current(self) -> ResultStore:
        with self._lock:
            return self._store

    def configure(self, store: ResultStore) -> None:
        store.load()
        with self._lock:
            previous = self._store
            self._store = store
        if previous is not store:
            previous.close()

    def reset_to_memory(self) -> None:
        replacement = InMemoryResultStore()
        with self._lock:
            previous = self._store
            self._store = replacement
        previous.close()


result_store_registry = ResultStoreRegistry()


_INDEXED_COLUMNS = (
    "result_id",
    "request_id",
    "invocation_id",
    "producer_agent_id",
    "producer_agent_version",
    "output_contract",
    "result_schema_id",
    "result_schema_version",
    "family",
    "privacy",
    "retention",
    "completed_at_ms",
    "canonical_sha256",
)


def _validated_fresh_record(
    record: AuthoritativeSpecialistResult,
) -> AuthoritativeSpecialistResult:
    if record.replay != ResultReplayDisposition.FRESH:
        raise ResultConflictError("replayed result cannot be claimed as new authority")
    try:
        return AuthoritativeSpecialistResult.model_validate(record.model_dump(mode="json"))
    except ValueError:
        raise ResultConflictError("result failed authoritative contract validation") from None


def _require_same_result(
    existing: AuthoritativeSpecialistResult,
    candidate: AuthoritativeSpecialistResult,
) -> None:
    if existing != candidate:
        raise ResultConflictError(
            "result or invocation identity was reused with different authoritative content"
        )


def _encoded_record(record: AuthoritativeSpecialistResult) -> tuple[str, str]:
    payload_json = canonical_json(record)
    payload_hash = canonical_fingerprint(record)
    return payload_json, payload_hash
