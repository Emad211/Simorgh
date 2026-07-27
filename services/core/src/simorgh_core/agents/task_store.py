from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord

AGENT_TASK_STORE_SCHEMA_VERSION: Literal[1] = 1
DEFAULT_MAX_TERMINAL_TASK_RECORDS = 10_000
_ZERO_USAGE = UsageVector()

_ALLOWED_PHASE_TRANSITIONS: dict[AgentTaskPhase, frozenset[AgentTaskPhase]] = {
    AgentTaskPhase.ROUTING: frozenset(AgentTaskPhase),
    AgentTaskPhase.ROUTED: frozenset(
        {AgentTaskPhase.ROUTED, AgentTaskPhase.CANCELLED}
    ),
    AgentTaskPhase.NEEDS_CLARIFICATION: frozenset(
        {AgentTaskPhase.NEEDS_CLARIFICATION, AgentTaskPhase.CANCELLED}
    ),
    AgentTaskPhase.NEEDS_ESCALATION: frozenset(
        {AgentTaskPhase.NEEDS_ESCALATION, AgentTaskPhase.CANCELLED}
    ),
    AgentTaskPhase.BUDGET_EXHAUSTED: frozenset(
        {AgentTaskPhase.BUDGET_EXHAUSTED, AgentTaskPhase.CANCELLED}
    ),
    AgentTaskPhase.POLICY_BLOCKED: frozenset(
        {AgentTaskPhase.POLICY_BLOCKED, AgentTaskPhase.CANCELLED}
    ),
    AgentTaskPhase.CONTRACT_INVALID: frozenset(
        {AgentTaskPhase.CONTRACT_INVALID, AgentTaskPhase.CANCELLED}
    ),
    AgentTaskPhase.CANCELLED: frozenset({AgentTaskPhase.CANCELLED}),
    AgentTaskPhase.EXPIRED: frozenset({AgentTaskPhase.EXPIRED}),
    AgentTaskPhase.UNKNOWN: frozenset(
        {AgentTaskPhase.UNKNOWN, AgentTaskPhase.CANCELLED}
    ),
}


class AgentTaskStoreError(RuntimeError):
    """Base class for durable agent-task storage failures."""


class AgentTaskStoreClosedError(AgentTaskStoreError):
    pass


class AgentTaskStoreCorruptionError(AgentTaskStoreError):
    pass


class AgentTaskStoreSchemaError(AgentTaskStoreError):
    pass


class AgentTaskStoreConflictError(AgentTaskStoreError):
    pass


class AgentTaskStoreEntryV1(BaseModel):
    """Versioned self-validating durable representation of one agent task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = AGENT_TASK_STORE_SCHEMA_VERSION
    request_id: UUID
    task_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    record: AgentTaskRecord

    @property
    def terminal(self) -> bool:
        return self.record.terminal

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.record.request_id != self.request_id:
            raise ValueError("task store entry request_id does not match record")
        if task_fingerprint(self.record) != self.task_fingerprint:
            raise ValueError("task_fingerprint does not match task content")
        if self.record.terminal and self.record.budget.reserved != _ZERO_USAGE:
            raise ValueError("terminal agent task cannot retain unresolved reservations")
        return self


class AgentTaskStore(Protocol):
    def load(self) -> list[AgentTaskStoreEntryV1]: ...

    def get(self, request_id: UUID) -> AgentTaskStoreEntryV1 | None: ...

    def upsert(self, entry: AgentTaskStoreEntryV1) -> None: ...

    def delete(self, request_id: UUID) -> None: ...

    def clear(self) -> None: ...

    def close(self) -> None: ...


def task_fingerprint(record: AgentTaskRecord) -> str:
    payload = record.task.model_dump(mode="json")
    payload["allowed_data_sources"] = sorted(record.task.allowed_data_sources)
    return canonical_fingerprint(payload)


def new_task_store_entry(record: AgentTaskRecord) -> AgentTaskStoreEntryV1:
    return AgentTaskStoreEntryV1(
        request_id=record.request_id,
        task_fingerprint=task_fingerprint(record),
        record=record,
    )


def canonical_json(value: BaseModel | Mapping[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_task_store_transition(
    existing: AgentTaskStoreEntryV1,
    candidate: AgentTaskStoreEntryV1,
) -> None:
    if existing.request_id != candidate.request_id:
        raise AgentTaskStoreConflictError("task transition changed request ownership")
    if existing.task_fingerprint != candidate.task_fingerprint:
        raise AgentTaskStoreConflictError("durable task fingerprint is immutable")
    if existing.record.task != candidate.record.task:
        raise AgentTaskStoreConflictError("durable TaskEnvelope content is immutable")
    if existing.record.created_at_ms != candidate.record.created_at_ms:
        raise AgentTaskStoreConflictError("durable task created_at_ms is immutable")
    if candidate.record.updated_at_ms < existing.record.updated_at_ms:
        raise AgentTaskStoreConflictError("durable task updated_at_ms cannot move backwards")
    if candidate.record.phase not in _ALLOWED_PHASE_TRANSITIONS[existing.record.phase]:
        raise AgentTaskStoreConflictError(
            "invalid durable agent-task phase transition "
            f"{existing.record.phase.value} -> {candidate.record.phase.value}"
        )
    if (
        existing.record.routing_decision is not None
        and candidate.record.routing_decision != existing.record.routing_decision
    ):
        raise AgentTaskStoreConflictError("durable routing decision is immutable")
    if (
        existing.record.cancel_reason is not None
        and candidate.record.cancel_reason != existing.record.cancel_reason
    ):
        raise AgentTaskStoreConflictError("durable cancellation reason is immutable")
    if (
        existing.record.cancellation_request is not None
        and candidate.record.cancellation_request
        != existing.record.cancellation_request
    ):
        raise AgentTaskStoreConflictError(
            "durable cancellation request is immutable"
        )
    if (
        existing.record.cancellation_result is not None
        and candidate.record.cancellation_result
        != existing.record.cancellation_result
    ):
        raise AgentTaskStoreConflictError(
            "durable cancellation result is immutable"
        )

    existing_budget = existing.record.budget
    candidate_budget = candidate.record.budget
    if existing_budget.request_id != candidate_budget.request_id:
        raise AgentTaskStoreConflictError("durable budget request identity is immutable")
    if existing_budget.limits != candidate_budget.limits:
        raise AgentTaskStoreConflictError("durable task budget limits are immutable")
    if candidate_budget.elapsed_ms < existing_budget.elapsed_ms:
        raise AgentTaskStoreConflictError("durable task elapsed budget cannot move backwards")
    if existing_budget.cancelled and not candidate_budget.cancelled:
        raise AgentTaskStoreConflictError("durable task cancellation cannot be reversed")
    if (
        existing_budget.exhausted_dimension is not None
        and candidate_budget.exhausted_dimension != existing_budget.exhausted_dimension
    ):
        raise AgentTaskStoreConflictError("durable exhausted budget dimension is immutable")
    _require_usage_not_decreased(
        existing=existing_budget.committed,
        candidate=candidate_budget.committed,
    )


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
            raise AgentTaskStoreConflictError(
                f"durable committed usage dimension {dimension} cannot decrease"
            )


class InMemoryAgentTaskStore:
    """Strict in-memory store used by pure control-plane tests."""

    def __init__(
        self,
        *,
        max_terminal_records: int = DEFAULT_MAX_TERMINAL_TASK_RECORDS,
    ) -> None:
        if max_terminal_records < 0:
            raise ValueError("max_terminal_records cannot be negative")
        self._max_terminal_records = max_terminal_records
        self._entries: OrderedDict[UUID, AgentTaskStoreEntryV1] = OrderedDict()
        self._closed = False

    def load(self) -> list[AgentTaskStoreEntryV1]:
        self._require_open()
        return list(self._entries.values())

    def get(self, request_id: UUID) -> AgentTaskStoreEntryV1 | None:
        self._require_open()
        return self._entries.get(request_id)

    def upsert(self, entry: AgentTaskStoreEntryV1) -> None:
        self._require_open()
        validated = AgentTaskStoreEntryV1.model_validate(entry.model_dump(mode="json"))
        existing = self._entries.get(validated.request_id)
        if existing is not None:
            validate_task_store_transition(existing, validated)
        self._entries[validated.request_id] = validated
        self._entries.move_to_end(validated.request_id)
        self._prune_terminal()

    def delete(self, request_id: UUID) -> None:
        self._require_open()
        self._entries.pop(request_id, None)

    def clear(self) -> None:
        self._require_open()
        self._entries.clear()

    def close(self) -> None:
        self._closed = True

    def _prune_terminal(self) -> None:
        terminal_keys = sorted(
            (
                entry.record.updated_at_ms,
                str(entry.request_id),
                request_id,
            )
            for request_id, entry in self._entries.items()
            if entry.terminal
        )
        overflow = len(terminal_keys) - self._max_terminal_records
        for _, _, request_id in terminal_keys[: max(overflow, 0)]:
            self._entries.pop(request_id, None)

    def _require_open(self) -> None:
        if self._closed:
            raise AgentTaskStoreClosedError("agent task store is closed")


class SQLiteAgentTaskStore:
    """SQLite WAL store with atomic transitions and integrity-checked payloads."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_terminal_records: int = DEFAULT_MAX_TERMINAL_TASK_RECORDS,
    ) -> None:
        if max_terminal_records < 0:
            raise ValueError("max_terminal_records cannot be negative")
        raw_path = str(path)
        self._path = (
            ":memory:"
            if raw_path == ":memory:"
            else str(Path(raw_path).expanduser().resolve())
        )
        self._max_terminal_records = max_terminal_records
        self._lock = threading.RLock()
        self._closed = False

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
        except AgentTaskStoreError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise AgentTaskStoreCorruptionError(
                f"could not initialize agent task store at {self._path}: {exc}"
            ) from exc

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> list[AgentTaskStoreEntryV1]:
        with self._lock:
            self._require_open()
            self._verify_database_integrity()
            try:
                rows = self._connection.execute(self._select_rows_sql()).fetchall()
            except sqlite3.DatabaseError as exc:
                raise AgentTaskStoreCorruptionError(
                    f"could not read agent task rows: {exc}"
                ) from exc
            return [self._decode_row(row) for row in rows]

    def get(self, request_id: UUID) -> AgentTaskStoreEntryV1 | None:
        with self._lock:
            self._require_open()
            try:
                row = self._connection.execute(
                    self._select_rows_sql(where_clause="WHERE request_id = ?"),
                    (str(request_id),),
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                raise AgentTaskStoreCorruptionError(
                    f"could not read agent task {request_id}: {exc}"
                ) from exc
            return self._decode_row(row) if row is not None else None

    def upsert(self, entry: AgentTaskStoreEntryV1) -> None:
        with self._lock:
            self._require_open()
            validated = AgentTaskStoreEntryV1.model_validate(entry.model_dump(mode="json"))
            payload_json = canonical_json(validated)
            payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            try:
                with self._transaction():
                    existing_row = self._connection.execute(
                        self._select_rows_sql(where_clause="WHERE request_id = ?"),
                        (str(validated.request_id),),
                    ).fetchone()
                    if existing_row is not None:
                        validate_task_store_transition(
                            self._decode_row(existing_row),
                            validated,
                        )

                    self._connection.execute(
                        """
                        INSERT INTO agent_task_records (
                            request_id,
                            task_fingerprint,
                            phase,
                            terminal,
                            created_at_ms,
                            updated_at_ms,
                            payload_json,
                            payload_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(request_id) DO UPDATE SET
                            phase = excluded.phase,
                            terminal = excluded.terminal,
                            updated_at_ms = excluded.updated_at_ms,
                            payload_json = excluded.payload_json,
                            payload_sha256 = excluded.payload_sha256
                        """,
                        (
                            str(validated.request_id),
                            validated.task_fingerprint,
                            validated.record.phase.value,
                            int(validated.terminal),
                            validated.record.created_at_ms,
                            validated.record.updated_at_ms,
                            payload_json,
                            payload_sha256,
                        ),
                    )
                    self._prune_terminal_locked()
            except AgentTaskStoreConflictError:
                raise
            except sqlite3.IntegrityError as exc:
                raise AgentTaskStoreConflictError(
                    "durable agent-task identity conflicts with an existing row"
                ) from exc
            except sqlite3.DatabaseError as exc:
                raise AgentTaskStoreCorruptionError(
                    f"could not persist agent task row: {exc}"
                ) from exc

    def delete(self, request_id: UUID) -> None:
        with self._lock:
            self._require_open()
            try:
                with self._transaction():
                    self._connection.execute(
                        "DELETE FROM agent_task_records WHERE request_id = ?",
                        (str(request_id),),
                    )
            except sqlite3.DatabaseError as exc:
                raise AgentTaskStoreCorruptionError(
                    f"could not delete agent task {request_id}: {exc}"
                ) from exc

    def clear(self) -> None:
        with self._lock:
            self._require_open()
            try:
                with self._transaction():
                    self._connection.execute("DELETE FROM agent_task_records")
            except sqlite3.DatabaseError as exc:
                raise AgentTaskStoreCorruptionError(
                    f"could not clear agent task store: {exc}"
                ) from exc

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._connection.close()

    def _initialize_schema(self) -> None:
        with self._transaction():
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_task_store_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            row = self._connection.execute(
                """
                SELECT value
                FROM agent_task_store_metadata
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO agent_task_store_metadata(key, value)
                    VALUES('schema_version', ?)
                    """,
                    (str(AGENT_TASK_STORE_SCHEMA_VERSION),),
                )
            elif row["value"] != str(AGENT_TASK_STORE_SCHEMA_VERSION):
                raise AgentTaskStoreSchemaError(
                    "unsupported agent task store schema version " + str(row["value"])
                )

            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_task_records (
                    request_id TEXT PRIMARY KEY,
                    task_fingerprint TEXT NOT NULL
                        CHECK (length(task_fingerprint) = 64),
                    phase TEXT NOT NULL,
                    terminal INTEGER NOT NULL CHECK (terminal IN (0, 1)),
                    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
                    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS agent_task_records_terminal_order
                ON agent_task_records(terminal, updated_at_ms, request_id)
                """
            )

    @staticmethod
    def _select_rows_sql(*, where_clause: str = "") -> str:
        return f"""
            SELECT
                request_id,
                task_fingerprint,
                phase,
                terminal,
                created_at_ms,
                updated_at_ms,
                payload_json,
                payload_sha256
            FROM agent_task_records
            {where_clause}
            ORDER BY created_at_ms, request_id
        """

    def _decode_row(self, row: sqlite3.Row) -> AgentTaskStoreEntryV1:
        payload_json = row["payload_json"]
        expected_hash = row["payload_sha256"]
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            raise AgentTaskStoreCorruptionError(
                f"agent task {row['request_id']} payload hash mismatch"
            )
        try:
            decoded = json.loads(payload_json)
            entry = AgentTaskStoreEntryV1.model_validate(decoded)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise AgentTaskStoreCorruptionError(
                f"agent task {row['request_id']} payload is invalid: {exc}"
            ) from exc

        column_identity = (
            str(entry.request_id),
            entry.task_fingerprint,
            entry.record.phase.value,
            int(entry.terminal),
            entry.record.created_at_ms,
            entry.record.updated_at_ms,
        )
        row_identity = (
            row["request_id"],
            row["task_fingerprint"],
            row["phase"],
            row["terminal"],
            row["created_at_ms"],
            row["updated_at_ms"],
        )
        if column_identity != row_identity:
            raise AgentTaskStoreCorruptionError(
                f"agent task {row['request_id']} indexed columns do not match payload"
            )
        return entry

    def _prune_terminal_locked(self) -> None:
        rows = self._connection.execute(
            """
            SELECT request_id
            FROM agent_task_records
            WHERE terminal = 1
            ORDER BY updated_at_ms DESC, request_id DESC
            LIMIT -1 OFFSET ?
            """,
            (self._max_terminal_records,),
        ).fetchall()
        for row in rows:
            self._connection.execute(
                "DELETE FROM agent_task_records WHERE request_id = ?",
                (row["request_id"],),
            )

    def _verify_database_integrity(self) -> None:
        try:
            rows = self._connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            raise AgentTaskStoreCorruptionError(
                f"could not verify agent task database integrity: {exc}"
            ) from exc
        messages = [str(row[0]) for row in rows]
        if messages != ["ok"]:
            raise AgentTaskStoreCorruptionError(
                "agent task database integrity check failed: " + "; ".join(messages)
            )

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

    def _require_open(self) -> None:
        if self._closed:
            raise AgentTaskStoreClosedError("agent task store is closed")
