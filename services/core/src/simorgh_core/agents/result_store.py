from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal
from uuid import UUID

from simorgh_core.agents.invocations import canonical_fingerprint, canonical_json
from simorgh_core.agents.result_authority import (
    ArtifactStorageDisposition,
    InMemoryResultStore,
    ResultAuthorityError,
    ResultConflictError,
    ResultNotFoundError,
    ResultReplayDisposition,
    ResultStoreClosedError,
    ResultWrite,
    SpecialistResultRecord,
)
from simorgh_core.agents.store_lock import (
    ExclusiveStoreLock,
    ExclusiveStoreLockError,
    ExclusiveStoreLockInUseError,
)

RESULT_STORE_SCHEMA_VERSION: Literal[1] = 1


class ResultStoreCorruptionError(ResultAuthorityError):
    pass


class ResultStoreSchemaError(ResultAuthorityError):
    pass


class ResultStoreInUseError(ResultAuthorityError):
    pass


class ResultStoreUnhealthyError(ResultAuthorityError):
    pass


class ArtifactIntegrityError(ResultAuthorityError):
    pass


class ArtifactBytesNotFoundError(ResultAuthorityError):
    pass


class SQLiteResultStore:
    """SQLite WAL authority for immutable result metadata and bounded local bytes."""

    def __init__(
        self,
        path: str | Path,
        *,
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        del wall_clock_millis
        raw_path = str(path)
        self._path = (
            ":memory:"
            if raw_path == ":memory:"
            else str(Path(raw_path).expanduser().resolve())
        )
        self._lock = threading.RLock()
        self._closed = False
        self._failure: ResultAuthorityError | None = None
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
            self._verify_all_records_locked()
        except ResultAuthorityError:
            if connection is not None:
                connection.close()
            self._close_path_lock()
            raise
        except sqlite3.DatabaseError:
            if connection is not None:
                connection.close()
            self._close_path_lock()
            raise ResultStoreCorruptionError(
                "could not initialize result store"
            ) from None

    @property
    def path(self) -> str:
        return self._path

    def put(self, record: SpecialistResultRecord) -> ResultWrite:
        return self.put_with_artifacts(record, artifact_bytes={})

    def put_with_artifacts(
        self,
        record: SpecialistResultRecord,
        *,
        artifact_bytes: Mapping[UUID, bytes],
    ) -> ResultWrite:
        validated = SpecialistResultRecord.model_validate(record.model_dump(mode="json"))
        validated_bytes = _validate_artifact_bytes(validated, artifact_bytes)
        with self._lock:
            self._require_healthy_locked()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._get_optional_locked(validated.result_id)
                if existing is not None:
                    if existing != validated:
                        raise ResultConflictError(
                            "result ID was reused with different immutable content"
                        )
                    self._require_same_artifact_bytes_locked(
                        result_id=validated.result_id,
                        artifact_bytes=validated_bytes,
                    )
                    self._connection.execute("COMMIT")
                    return ResultWrite(
                        disposition=ResultReplayDisposition.REPLAYED,
                        record=existing,
                    )
                invocation_row = self._connection.execute(
                    "SELECT result_id FROM result_records WHERE invocation_id = ?",
                    (str(validated.producer.invocation_id),),
                ).fetchone()
                if invocation_row is not None:
                    raise ResultConflictError(
                        "specialist invocation already owns a different result"
                    )
                payload_json = canonical_json(validated)
                self._connection.execute(
                    """
                    INSERT INTO result_records(
                        result_id,
                        invocation_id,
                        payload_json,
                        payload_sha256,
                        created_at_ms
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(validated.result_id),
                        str(validated.producer.invocation_id),
                        payload_json,
                        canonical_fingerprint(validated),
                        validated.created_at_ms,
                    ),
                )
                for artifact in validated.artifacts:
                    blob = validated_bytes.get(artifact.artifact_id)
                    self._connection.execute(
                        """
                        INSERT INTO result_artifacts(
                            artifact_id,
                            result_id,
                            metadata_json,
                            metadata_sha256,
                            payload_bytes
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            str(artifact.artifact_id),
                            str(validated.result_id),
                            canonical_json(artifact),
                            canonical_fingerprint(artifact),
                            blob,
                        ),
                    )
                self._connection.execute("COMMIT")
                return ResultWrite(
                    disposition=ResultReplayDisposition.CREATED,
                    record=validated,
                )
            except ResultAuthorityError:
                self._connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError:
                self._connection.execute("ROLLBACK")
                raise ResultConflictError(
                    "result identity conflicts with durable state"
                ) from None
            except sqlite3.DatabaseError:
                self._connection.execute("ROLLBACK")
                self._latch_failure_locked(
                    ResultStoreCorruptionError("result store write failed")
                )

    def get(self, result_id: UUID) -> SpecialistResultRecord:
        with self._lock:
            self._require_healthy_locked()
            record = self._get_optional_locked(result_id)
            if record is None:
                raise ResultNotFoundError(f"result {result_id} does not exist")
            return record

    def get_for_invocation(self, invocation_id: UUID) -> SpecialistResultRecord:
        with self._lock:
            self._require_healthy_locked()
            row = self._connection.execute(
                "SELECT result_id FROM result_records WHERE invocation_id = ?",
                (str(invocation_id),),
            ).fetchone()
            if row is None:
                raise ResultNotFoundError(
                    f"invocation {invocation_id} has no authoritative result"
                )
            record = self._get_optional_locked(UUID(row["result_id"]))
            if record is None:
                self._latch_failure_locked(
                    ResultStoreCorruptionError("result invocation index is corrupt")
                )
            return record

    def get_artifact_bytes(self, artifact_id: UUID) -> bytes:
        with self._lock:
            self._require_healthy_locked()
            row = self._connection.execute(
                "SELECT payload_bytes, metadata_json, metadata_sha256 FROM result_artifacts "
                "WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
            if row is None or row["payload_bytes"] is None:
                raise ArtifactBytesNotFoundError(
                    f"artifact {artifact_id} has no local payload bytes"
                )
            _validate_metadata_row(row["metadata_json"], row["metadata_sha256"])
            return bytes(row["payload_bytes"])

    def load(self) -> tuple[SpecialistResultRecord, ...]:
        with self._lock:
            self._require_healthy_locked()
            rows = self._connection.execute(
                "SELECT result_id FROM result_records ORDER BY created_at_ms, result_id"
            ).fetchall()
            return tuple(
                self._require_result_locked(UUID(row["result_id"])) for row in rows
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._connection.close()
            self._close_path_lock()

    def _initialize_schema(self) -> None:
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS result_store_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = self._connection.execute(
            "SELECT value FROM result_store_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            self._connection.execute(
                "INSERT INTO result_store_meta(key, value) VALUES ('schema_version', ?)",
                (str(RESULT_STORE_SCHEMA_VERSION),),
            )
        elif row["value"] != str(RESULT_STORE_SCHEMA_VERSION):
            raise ResultStoreSchemaError("unsupported result store schema version")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS result_records(
                result_id TEXT PRIMARY KEY,
                invocation_id TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS result_artifacts(
                artifact_id TEXT PRIMARY KEY,
                result_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                metadata_sha256 TEXT NOT NULL,
                payload_bytes BLOB,
                FOREIGN KEY(result_id) REFERENCES result_records(result_id)
            )
            """
        )

    def _verify_database_integrity(self) -> None:
        row = self._connection.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise ResultStoreCorruptionError("result store integrity check failed")

    def _verify_all_records_locked(self) -> None:
        for row in self._connection.execute(
            "SELECT result_id FROM result_records ORDER BY result_id"
        ).fetchall():
            self._require_result_locked(UUID(row["result_id"]))

    def _get_optional_locked(self, result_id: UUID) -> SpecialistResultRecord | None:
        row = self._connection.execute(
            "SELECT payload_json, payload_sha256 FROM result_records WHERE result_id = ?",
            (str(result_id),),
        ).fetchone()
        if row is None:
            return None
        return _decode_record(row["payload_json"], row["payload_sha256"])

    def _require_result_locked(self, result_id: UUID) -> SpecialistResultRecord:
        record = self._get_optional_locked(result_id)
        if record is None:
            self._latch_failure_locked(
                ResultStoreCorruptionError("result record disappeared during read")
            )
        return record

    def _require_same_artifact_bytes_locked(
        self,
        *,
        result_id: UUID,
        artifact_bytes: dict[UUID, bytes],
    ) -> None:
        rows = self._connection.execute(
            "SELECT artifact_id, payload_bytes FROM result_artifacts WHERE result_id = ?",
            (str(result_id),),
        ).fetchall()
        existing = {
            UUID(row["artifact_id"]): (
                None if row["payload_bytes"] is None else bytes(row["payload_bytes"])
            )
            for row in rows
        }
        for artifact_id, payload in artifact_bytes.items():
            if existing.get(artifact_id) != payload:
                raise ResultConflictError(
                    "artifact bytes changed during exact result replay"
                )

    def _require_healthy_locked(self) -> None:
        if self._closed:
            raise ResultStoreClosedError("result store is closed")
        if self._failure is not None:
            raise ResultStoreUnhealthyError("result store is unhealthy") from self._failure

    def _latch_failure_locked(self, failure: ResultAuthorityError) -> None:
        self._failure = failure
        raise failure

    def _close_path_lock(self) -> None:
        if self._path_lock is not None:
            self._path_lock.close()
            self._path_lock = None


def _validate_artifact_bytes(
    record: SpecialistResultRecord,
    artifact_bytes: Mapping[UUID, bytes],
) -> dict[UUID, bytes]:
    references = {artifact.artifact_id: artifact for artifact in record.artifacts}
    unknown = set(artifact_bytes).difference(references)
    if unknown:
        raise ArtifactIntegrityError("artifact bytes contain an unregistered artifact ID")
    validated: dict[UUID, bytes] = {}
    for artifact_id, payload in artifact_bytes.items():
        reference = references[artifact_id]
        if reference.storage_disposition != ArtifactStorageDisposition.CORE_LOCAL:
            raise ArtifactIntegrityError(
                "local artifact bytes require core-local storage disposition"
            )
        data = bytes(payload)
        if len(data) != reference.size_bytes:
            raise ArtifactIntegrityError("artifact byte size does not match metadata")
        if hashlib.sha256(data).hexdigest() != reference.sha256:
            raise ArtifactIntegrityError("artifact bytes do not match metadata hash")
        validated[artifact_id] = data
    return validated


def _decode_record(payload_json: str, payload_sha256: str) -> SpecialistResultRecord:
    _validate_metadata_row(payload_json, payload_sha256)
    try:
        return SpecialistResultRecord.model_validate_json(payload_json)
    except ValueError:
        raise ResultStoreCorruptionError(
            "durable result payload failed typed validation"
        ) from None


def _validate_metadata_row(payload_json: str, payload_sha256: str) -> None:
    try:
        import json

        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        raise ResultStoreCorruptionError("durable result JSON is invalid") from None
    if canonical_fingerprint(payload) != payload_sha256:
        raise ResultStoreCorruptionError("durable result hash does not match payload")


__all__ = [
    "ArtifactBytesNotFoundError",
    "ArtifactIntegrityError",
    "InMemoryResultStore",
    "SQLiteResultStore",
]
