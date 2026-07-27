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

from simorgh_core.agents.context_contracts import (
    ContextReplayDisposition,
    SpecialistContextBundle,
)
from simorgh_core.agents.invocations import canonical_json
from simorgh_core.agents.store_lock import (
    ExclusiveStoreLock,
    ExclusiveStoreLockError,
    ExclusiveStoreLockInUseError,
)

CONTEXT_STORE_SCHEMA_VERSION: Literal[1] = 1


class ContextStoreError(RuntimeError):
    """Base class for deterministic context-store failures."""


class ContextConflictError(ContextStoreError):
    pass


class ContextNotFoundError(ContextStoreError):
    pass


class ContextStoreClosedError(ContextStoreError):
    pass


class ContextStoreCorruptionError(ContextStoreError):
    pass


class ContextStoreSchemaError(ContextStoreError):
    pass


class ContextStoreUnhealthyError(ContextStoreError):
    pass


class ContextStoreInUseError(ContextStoreError):
    pass


class ContextClaimKind(StrEnum):
    NEW = "new"
    REPLAY = "replay"


class ContextClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: ContextClaimKind
    record: SpecialistContextBundle


class ContextStore(Protocol):
    def claim(self, record: SpecialistContextBundle) -> ContextClaim: ...

    def get(self, context_bundle_id: UUID) -> SpecialistContextBundle: ...

    def get_by_invocation(self, invocation_id: UUID) -> SpecialistContextBundle: ...

    def load(self) -> list[SpecialistContextBundle]: ...

    def close(self) -> None: ...


class InMemoryContextStore:
    """Strict process-local immutable context authority."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[UUID, SpecialistContextBundle] = {}
        self._by_invocation: dict[UUID, UUID] = {}
        self._closed = False

    def claim(self, record: SpecialistContextBundle) -> ContextClaim:
        candidate = _validated_fresh_record(record)
        with self._lock:
            self._require_open_locked()
            existing = self._records.get(candidate.context_bundle_id)
            existing_id = self._by_invocation.get(candidate.specialist_invocation_id)
            if existing is None and existing_id is not None:
                existing = self._records[existing_id]
            if existing is not None:
                _require_same_context(existing, candidate)
                return ContextClaim(
                    kind=ContextClaimKind.REPLAY,
                    record=existing.model_copy(
                        update={"replay": ContextReplayDisposition.REPLAYED}
                    ),
                )
            self._records[candidate.context_bundle_id] = candidate
            self._by_invocation[candidate.specialist_invocation_id] = (
                candidate.context_bundle_id
            )
            return ContextClaim(kind=ContextClaimKind.NEW, record=candidate)

    def get(self, context_bundle_id: UUID) -> SpecialistContextBundle:
        with self._lock:
            self._require_open_locked()
            record = self._records.get(context_bundle_id)
            if record is None:
                raise ContextNotFoundError(
                    f"context bundle {context_bundle_id} does not exist"
                )
            return record

    def get_by_invocation(self, invocation_id: UUID) -> SpecialistContextBundle:
        with self._lock:
            self._require_open_locked()
            context_id = self._by_invocation.get(invocation_id)
            if context_id is None:
                raise ContextNotFoundError(
                    f"specialist invocation {invocation_id} has no context bundle"
                )
            return self._records[context_id]

    def load(self) -> list[SpecialistContextBundle]:
        with self._lock:
            self._require_open_locked()
            return sorted(
                self._records.values(),
                key=lambda record: (record.compiled_at_ms, str(record.context_bundle_id)),
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _require_open_locked(self) -> None:
        if self._closed:
            raise ContextStoreClosedError("context store is closed")


class SQLiteContextStore:
    """SQLite WAL authority for immutable context bundles."""

    def __init__(self, path: str | Path) -> None:
        raw_path = str(path)
        self._path = (
            ":memory:"
            if raw_path == ":memory:"
            else str(Path(raw_path).expanduser().resolve())
        )
        self._lock = threading.RLock()
        self._closed = False
        self._failure: ContextStoreError | None = None
        self._path_lock: ExclusiveStoreLock | None = None
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        connection: sqlite3.Connection | None = None
        try:
            if self._path != ":memory:":
                try:
                    self._path_lock = ExclusiveStoreLock(self._path)
                except ExclusiveStoreLockInUseError:
                    raise ContextStoreInUseError(
                        "another Simorgh Core process owns the context store"
                    ) from None
                except ExclusiveStoreLockError:
                    raise ContextStoreUnhealthyError(
                        "context store process lock is unavailable"
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
        except ContextStoreError:
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
            raise ContextStoreCorruptionError(
                "could not initialize context store"
            ) from None

    @property
    def path(self) -> str:
        return self._path

    def claim(self, record: SpecialistContextBundle) -> ContextClaim:
        candidate = _validated_fresh_record(record)
        with self._lock:
            self._require_healthy_locked()
            existing = self._get_optional_locked(
                context_bundle_id=candidate.context_bundle_id
            )
            if existing is None:
                existing = self._get_optional_locked(
                    invocation_id=candidate.specialist_invocation_id
                )
            if existing is not None:
                _require_same_context(existing, candidate)
                return ContextClaim(
                    kind=ContextClaimKind.REPLAY,
                    record=existing.model_copy(
                        update={"replay": ContextReplayDisposition.REPLAYED}
                    ),
                )

            payload_json, payload_hash = _encoded_record(candidate)
            try:
                with self._transaction():
                    self._connection.execute(
                        """
                        INSERT INTO context_records (
                            context_bundle_id,
                            request_id,
                            specialist_invocation_id,
                            agent_id,
                            agent_version,
                            canonical_sha256,
                            compiled_at_ms,
                            privacy,
                            retention,
                            total_bytes,
                            estimated_tokens,
                            payload_json,
                            payload_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(candidate.context_bundle_id),
                            str(candidate.request_id),
                            str(candidate.specialist_invocation_id),
                            candidate.agent_id,
                            candidate.agent_version,
                            candidate.canonical_sha256,
                            candidate.compiled_at_ms,
                            candidate.privacy.value,
                            candidate.retention.value,
                            candidate.total_bytes,
                            candidate.estimated_tokens,
                            payload_json,
                            payload_hash,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                current = self._get_optional_locked(
                    context_bundle_id=candidate.context_bundle_id
                )
                if current is None:
                    current = self._get_optional_locked(
                        invocation_id=candidate.specialist_invocation_id
                    )
                if current is not None:
                    _require_same_context(current, candidate)
                    return ContextClaim(
                        kind=ContextClaimKind.REPLAY,
                        record=current.model_copy(
                            update={"replay": ContextReplayDisposition.REPLAYED}
                        ),
                    )
                raise ContextConflictError(
                    "durable context identity conflicts with an existing row"
                ) from exc
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not persist context", exc)
            return ContextClaim(kind=ContextClaimKind.NEW, record=candidate)

    def get(self, context_bundle_id: UUID) -> SpecialistContextBundle:
        with self._lock:
            record = self._get_optional_locked(context_bundle_id=context_bundle_id)
            if record is None:
                raise ContextNotFoundError(
                    f"context bundle {context_bundle_id} does not exist"
                )
            return record

    def get_by_invocation(self, invocation_id: UUID) -> SpecialistContextBundle:
        with self._lock:
            record = self._get_optional_locked(invocation_id=invocation_id)
            if record is None:
                raise ContextNotFoundError(
                    f"specialist invocation {invocation_id} has no context bundle"
                )
            return record

    def load(self) -> list[SpecialistContextBundle]:
        with self._lock:
            self._require_healthy_locked()
            self._verify_database_integrity()
            try:
                rows = self._connection.execute(self._select_sql()).fetchall()
            except sqlite3.DatabaseError as exc:
                self._raise_database_failure_locked("could not read context records", exc)
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
                CREATE TABLE IF NOT EXISTS context_store_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            row = self._connection.execute(
                """
                SELECT value
                FROM context_store_metadata
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO context_store_metadata(key, value)
                    VALUES('schema_version', ?)
                    """,
                    (str(CONTEXT_STORE_SCHEMA_VERSION),),
                )
            elif row["value"] != str(CONTEXT_STORE_SCHEMA_VERSION):
                raise ContextStoreSchemaError(
                    "unsupported context store schema version " + str(row["value"])
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS context_records (
                    context_bundle_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    specialist_invocation_id TEXT NOT NULL UNIQUE,
                    agent_id TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
                    compiled_at_ms INTEGER NOT NULL CHECK(compiled_at_ms >= 0),
                    privacy TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    total_bytes INTEGER NOT NULL CHECK(total_bytes > 0),
                    estimated_tokens INTEGER NOT NULL CHECK(estimated_tokens > 0),
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS context_records_request_order
                ON context_records(request_id, compiled_at_ms, context_bundle_id)
                """
            )

    def _get_optional_locked(
        self,
        *,
        context_bundle_id: UUID | None = None,
        invocation_id: UUID | None = None,
    ) -> SpecialistContextBundle | None:
        self._require_healthy_locked()
        if (context_bundle_id is None) == (invocation_id is None):
            raise ValueError("exactly one context lookup identity is required")
        if context_bundle_id is not None:
            where_clause = "WHERE context_bundle_id = ?"
            value = str(context_bundle_id)
        else:
            where_clause = "WHERE specialist_invocation_id = ?"
            value = str(invocation_id)
        try:
            row = self._connection.execute(
                self._select_sql(where_clause=where_clause),
                (value,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked("could not read context record", exc)
        return self._decode_row(row) if row is not None else None

    def _decode_row(self, row: sqlite3.Row) -> SpecialistContextBundle:
        payload_json = str(row["payload_json"])
        expected_hash = str(row["payload_sha256"])
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            self._latch_failure_locked(
                ContextStoreCorruptionError("context payload hash mismatch")
            )
        try:
            payload = json.loads(payload_json)
            record = SpecialistContextBundle.model_validate(payload)
        except (json.JSONDecodeError, ValueError):
            self._latch_failure_locked(
                ContextStoreCorruptionError("context payload is invalid")
            )
        if record.replay != ContextReplayDisposition.FRESH:
            self._latch_failure_locked(
                ContextStoreCorruptionError("stored context cannot be marked replayed")
            )
        indexed = (
            str(record.context_bundle_id),
            str(record.request_id),
            str(record.specialist_invocation_id),
            record.agent_id,
            record.agent_version,
            record.canonical_sha256,
            record.compiled_at_ms,
            record.privacy.value,
            record.retention.value,
            record.total_bytes,
            record.estimated_tokens,
        )
        actual = (
            str(row["context_bundle_id"]),
            str(row["request_id"]),
            str(row["specialist_invocation_id"]),
            str(row["agent_id"]),
            str(row["agent_version"]),
            str(row["canonical_sha256"]),
            int(row["compiled_at_ms"]),
            str(row["privacy"]),
            str(row["retention"]),
            int(row["total_bytes"]),
            int(row["estimated_tokens"]),
        )
        if indexed != actual:
            self._latch_failure_locked(
                ContextStoreCorruptionError("context index metadata mismatch")
            )
        return record

    def _select_sql(self, *, where_clause: str = "") -> str:
        return f"""
            SELECT
                context_bundle_id,
                request_id,
                specialist_invocation_id,
                agent_id,
                agent_version,
                canonical_sha256,
                compiled_at_ms,
                privacy,
                retention,
                total_bytes,
                estimated_tokens,
                payload_json,
                payload_sha256
            FROM context_records
            {where_clause}
            ORDER BY compiled_at_ms, context_bundle_id
        """

    def _verify_database_integrity(self) -> None:
        self._require_healthy_locked()
        try:
            row = self._connection.execute("PRAGMA quick_check").fetchone()
            if row is None or row[0] != "ok":
                self._latch_failure_locked(
                    ContextStoreCorruptionError("context database integrity check failed")
                )
            rows = self._connection.execute(self._select_sql()).fetchall()
            for item in rows:
                self._decode_row(item)
        except sqlite3.DatabaseError as exc:
            self._raise_database_failure_locked(
                "context database integrity check failed", exc
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
            raise ContextStoreClosedError("context store is closed")
        if self._failure is not None:
            raise ContextStoreUnhealthyError("context store is unhealthy") from self._failure

    def _raise_database_failure_locked(
        self,
        message: str,
        exc: sqlite3.DatabaseError,
    ) -> NoReturn:
        failure = ContextStoreCorruptionError(message)
        self._failure = failure
        raise failure from exc

    def _latch_failure_locked(self, failure: ContextStoreError) -> NoReturn:
        self._failure = failure
        raise failure


def _validated_fresh_record(record: SpecialistContextBundle) -> SpecialistContextBundle:
    candidate = SpecialistContextBundle.model_validate(record.model_dump(mode="json"))
    if candidate.replay != ContextReplayDisposition.FRESH:
        raise ContextConflictError("new context claim cannot already be marked replayed")
    return candidate


def _require_same_context(
    existing: SpecialistContextBundle,
    candidate: SpecialistContextBundle,
) -> None:
    identity = (
        existing.context_bundle_id,
        existing.request_id,
        existing.specialist_invocation_id,
        existing.agent_id,
        existing.agent_version,
        existing.canonical_sha256,
    )
    candidate_identity = (
        candidate.context_bundle_id,
        candidate.request_id,
        candidate.specialist_invocation_id,
        candidate.agent_id,
        candidate.agent_version,
        candidate.canonical_sha256,
    )
    if identity != candidate_identity:
        raise ContextConflictError(
            "context bundle identity conflicts with an existing immutable record"
        )


def _encoded_record(record: SpecialistContextBundle) -> tuple[str, str]:
    payload_json = canonical_json(record)
    return payload_json, hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


__all__ = [
    "CONTEXT_STORE_SCHEMA_VERSION",
    "ContextClaim",
    "ContextClaimKind",
    "ContextConflictError",
    "ContextNotFoundError",
    "ContextStore",
    "ContextStoreClosedError",
    "ContextStoreCorruptionError",
    "ContextStoreError",
    "ContextStoreInUseError",
    "ContextStoreSchemaError",
    "ContextStoreUnhealthyError",
    "InMemoryContextStore",
    "SQLiteContextStore",
]
