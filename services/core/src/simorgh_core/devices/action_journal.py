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

from simorgh_core.devices.actions import AndroidActionCommand, AndroidActionResult
from simorgh_core.devices.protocol import (
    ActionResultAckStatus,
    DeviceActionCancelAckPayload,
    DeviceActionCommandAckPayload,
    ProtocolEnvelope,
)

ACTION_JOURNAL_SCHEMA_VERSION: Literal[1] = 1
DEFAULT_MAX_TERMINAL_RECORDS = 256

ActionJournalPhase = Literal[
    "queued",
    "delivered",
    "accepted",
    "cancelling",
    "completed",
    "rejected",
    "expired",
    "cancelled",
]
_TERMINAL_PHASES = frozenset({"completed", "rejected", "expired", "cancelled"})


class ActionJournalError(RuntimeError):
    """Base class for durable action-journal failures."""


class ActionJournalClosedError(ActionJournalError):
    """Raised when a closed journal is used."""


class ActionJournalCorruptionError(ActionJournalError):
    """Raised when durable bytes cannot be trusted as one valid journal state."""


class ActionJournalSchemaError(ActionJournalError):
    """Raised when the on-disk schema cannot be opened by this Core version."""


class ActionJournalConflictError(ActionJournalError):
    """Raised when durable command/action ownership conflicts with an existing row."""


class ActionJournalEntryV1(BaseModel):
    """Versioned, self-validating durable representation of one Core action record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = ACTION_JOURNAL_SCHEMA_VERSION
    device_id: UUID
    command: AndroidActionCommand
    command_envelope: ProtocolEnvelope
    command_payload_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    phase: ActionJournalPhase
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    delivery_count: int = Field(default=0, ge=0)
    last_session_id: UUID | None = None
    command_ack: DeviceActionCommandAckPayload | None = None
    cancel_envelope: ProtocolEnvelope | None = None
    cancel_ack: DeviceActionCancelAckPayload | None = None
    result: AndroidActionResult | None = None
    result_envelope_id: UUID | None = None
    result_correlation_id: UUID | None = None
    result_payload_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    result_ack_status: ActionResultAckStatus | None = None
    result_ack_sent_at_ms: int | None = Field(default=None, ge=0)
    detail: str = Field(default="", max_length=2_000)

    @property
    def action_id(self) -> UUID:
        return self.command.action_id

    @property
    def command_id(self) -> UUID:
        return self.command.command_id

    @property
    def terminal(self) -> bool:
        return self.phase in _TERMINAL_PHASES

    @model_validator(mode="after")
    def validate_internal_identity(self) -> Self:
        command_envelope = self.command_envelope
        if command_envelope.type != "device.action_command":
            raise ValueError("command_envelope must be device.action_command")
        if command_envelope.device_id != self.device_id:
            raise ValueError("command_envelope device_id does not match journal device_id")
        if command_envelope.correlation_id is not None:
            raise ValueError("command_envelope cannot have correlation_id")
        decoded_command = AndroidActionCommand.model_validate(command_envelope.payload)
        if decoded_command != self.command:
            raise ValueError("command_envelope payload does not match journal command")
        if canonical_sha256(self.command) != self.command_payload_sha256:
            raise ValueError("command_payload_sha256 does not match command")

        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms cannot precede created_at_ms")
        if self.delivery_count == 0 and self.last_session_id is not None:
            raise ValueError("last_session_id requires at least one delivery")
        if self.command_ack is not None:
            if self.command_ack.command_id != self.command_id:
                raise ValueError("command_ack command_id does not match command")
            if self.command_ack.action_id != self.action_id:
                raise ValueError("command_ack action_id does not match command")

        self._validate_cancellation()
        self._validate_result()
        return self

    def _validate_cancellation(self) -> None:
        envelope = self.cancel_envelope
        acknowledgement = self.cancel_ack
        if envelope is None:
            if acknowledgement is not None:
                raise ValueError("cancel_ack requires cancel_envelope")
            return

        if envelope.type != "device.action_cancel":
            raise ValueError("cancel_envelope must be device.action_cancel")
        if envelope.device_id != self.device_id:
            raise ValueError("cancel_envelope device_id does not match journal device_id")
        if envelope.correlation_id != self.command_envelope.message_id:
            raise ValueError("cancel_envelope must correlate to command_envelope")
        command_id = envelope.payload.get("command_id")
        action_id = envelope.payload.get("action_id")
        if command_id != str(self.command_id) or action_id != str(self.action_id):
            raise ValueError("cancel_envelope payload identity does not match command")

        if acknowledgement is not None:
            if acknowledgement.command_id != self.command_id:
                raise ValueError("cancel_ack command_id does not match command")
            if acknowledgement.action_id != self.action_id:
                raise ValueError("cancel_ack action_id does not match command")

    def _validate_result(self) -> None:
        result_fields = (
            self.result_envelope_id,
            self.result_correlation_id,
            self.result_payload_sha256,
        )
        if self.result is None:
            if any(value is not None for value in result_fields):
                raise ValueError("result envelope identity requires result payload")
            if self.result_ack_status is not None or self.result_ack_sent_at_ms is not None:
                raise ValueError("result ACK state requires result payload")
            return

        if any(value is None for value in result_fields):
            raise ValueError("result requires envelope id, correlation id, and payload hash")
        if self.result.command_id != self.command_id:
            raise ValueError("result command_id does not match command")
        if self.result.action_id != self.action_id:
            raise ValueError("result action_id does not match command")
        if self.result_correlation_id != self.command_envelope.message_id:
            raise ValueError("result correlation id must match command envelope message id")
        if canonical_sha256(self.result) != self.result_payload_sha256:
            raise ValueError("result_payload_sha256 does not match result")
        if self.phase not in {"completed", "cancelled"}:
            raise ValueError("persisted result requires completed or cancelled phase")
        if (self.result_ack_status is None) != (self.result_ack_sent_at_ms is None):
            raise ValueError("result ACK status and timestamp must be present together")


class ActionJournal(Protocol):
    def load(self) -> list[ActionJournalEntryV1]: ...

    def upsert(self, entry: ActionJournalEntryV1) -> None: ...

    def delete(self, *, device_id: UUID, action_id: UUID) -> None: ...

    def clear(self) -> None: ...

    def close(self) -> None: ...


def canonical_json(value: BaseModel | Mapping[str, object]) -> str:
    payload: object
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = dict(value)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: BaseModel | Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def new_journal_entry(
    *,
    device_id: UUID,
    command: AndroidActionCommand,
    command_envelope: ProtocolEnvelope,
    phase: ActionJournalPhase,
    created_at_ms: int,
    updated_at_ms: int,
    delivery_count: int = 0,
    last_session_id: UUID | None = None,
    command_ack: DeviceActionCommandAckPayload | None = None,
    cancel_envelope: ProtocolEnvelope | None = None,
    cancel_ack: DeviceActionCancelAckPayload | None = None,
    result: AndroidActionResult | None = None,
    result_envelope_id: UUID | None = None,
    result_correlation_id: UUID | None = None,
    result_ack_status: ActionResultAckStatus | None = None,
    result_ack_sent_at_ms: int | None = None,
    detail: str = "",
) -> ActionJournalEntryV1:
    return ActionJournalEntryV1(
        device_id=device_id,
        command=command,
        command_envelope=command_envelope,
        command_payload_sha256=canonical_sha256(command),
        phase=phase,
        created_at_ms=created_at_ms,
        updated_at_ms=updated_at_ms,
        delivery_count=delivery_count,
        last_session_id=last_session_id,
        command_ack=command_ack,
        cancel_envelope=cancel_envelope,
        cancel_ack=cancel_ack,
        result=result,
        result_envelope_id=result_envelope_id,
        result_correlation_id=result_correlation_id,
        result_payload_sha256=(canonical_sha256(result) if result is not None else None),
        result_ack_status=result_ack_status,
        result_ack_sent_at_ms=result_ack_sent_at_ms,
        detail=detail,
    )


class InMemoryActionJournal:
    """Strict in-memory implementation used by direct broker and storage tests."""

    def __init__(self, *, max_terminal_records: int = DEFAULT_MAX_TERMINAL_RECORDS) -> None:
        if max_terminal_records < 0:
            raise ValueError("max_terminal_records cannot be negative")
        self._max_terminal_records = max_terminal_records
        self._entries: OrderedDict[tuple[UUID, UUID], ActionJournalEntryV1] = OrderedDict()
        self._closed = False

    def load(self) -> list[ActionJournalEntryV1]:
        self._require_open()
        return list(self._entries.values())

    def upsert(self, entry: ActionJournalEntryV1) -> None:
        self._require_open()
        validated = ActionJournalEntryV1.model_validate(entry.model_dump(mode="json"))
        key = (validated.device_id, validated.action_id)
        command_owner = next(
            (
                candidate
                for candidate in self._entries.values()
                if candidate.device_id == validated.device_id
                and candidate.command_id == validated.command_id
                and candidate.action_id != validated.action_id
            ),
            None,
        )
        if command_owner is not None:
            raise ActionJournalConflictError(
                "command_id already belongs to another action in durable journal"
            )
        self._entries[key] = validated
        self._entries.move_to_end(key)
        self._prune_terminal()

    def delete(self, *, device_id: UUID, action_id: UUID) -> None:
        self._require_open()
        self._entries.pop((device_id, action_id), None)

    def clear(self) -> None:
        self._require_open()
        self._entries.clear()

    def close(self) -> None:
        self._closed = True

    def _prune_terminal(self) -> None:
        terminal_keys = [key for key, entry in self._entries.items() if entry.terminal]
        overflow = len(terminal_keys) - self._max_terminal_records
        for key in terminal_keys[: max(overflow, 0)]:
            self._entries.pop(key, None)

    def _require_open(self) -> None:
        if self._closed:
            raise ActionJournalClosedError("action journal is closed")


class SQLiteActionJournal:
    """SQLite WAL journal with atomic upsert and integrity-checked versioned payloads."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_terminal_records: int = DEFAULT_MAX_TERMINAL_RECORDS,
    ) -> None:
        if max_terminal_records < 0:
            raise ValueError("max_terminal_records cannot be negative")
        self._path = str(path)
        self._max_terminal_records = max_terminal_records
        self._lock = threading.RLock()
        self._closed = False

        if self._path != ":memory:":
            Path(self._path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(
                self._path,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA synchronous = FULL")
            if self._path != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL")
            self._initialize_schema()
        except sqlite3.DatabaseError as exc:
            raise ActionJournalCorruptionError(
                f"could not initialize action journal at {self._path}: {exc}"
            ) from exc

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> list[ActionJournalEntryV1]:
        with self._lock:
            self._require_open()
            self._verify_database_integrity()
            try:
                rows = self._connection.execute(
                    """
                    SELECT
                        device_id,
                        action_id,
                        command_id,
                        phase,
                        terminal,
                        updated_at_ms,
                        payload_json,
                        payload_sha256
                    FROM action_records
                    ORDER BY created_at_ms ASC, device_id ASC, action_id ASC
                    """
                ).fetchall()
            except sqlite3.DatabaseError as exc:
                raise ActionJournalCorruptionError(
                    f"could not read action journal rows: {exc}"
                ) from exc

            entries: list[ActionJournalEntryV1] = []
            for row in rows:
                entries.append(self._decode_row(row))
            return entries

    def upsert(self, entry: ActionJournalEntryV1) -> None:
        with self._lock:
            self._require_open()
            validated = ActionJournalEntryV1.model_validate(entry.model_dump(mode="json"))
            payload_json = canonical_json(validated)
            payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            try:
                with self._transaction():
                    self._connection.execute(
                        """
                        INSERT INTO action_records (
                            device_id,
                            action_id,
                            command_id,
                            phase,
                            terminal,
                            created_at_ms,
                            updated_at_ms,
                            payload_json,
                            payload_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(device_id, action_id) DO UPDATE SET
                            command_id = excluded.command_id,
                            phase = excluded.phase,
                            terminal = excluded.terminal,
                            created_at_ms = excluded.created_at_ms,
                            updated_at_ms = excluded.updated_at_ms,
                            payload_json = excluded.payload_json,
                            payload_sha256 = excluded.payload_sha256
                        """,
                        (
                            str(validated.device_id),
                            str(validated.action_id),
                            str(validated.command_id),
                            validated.phase,
                            int(validated.terminal),
                            validated.created_at_ms,
                            validated.updated_at_ms,
                            payload_json,
                            payload_sha256,
                        ),
                    )
                    self._prune_terminal_locked()
            except sqlite3.IntegrityError as exc:
                raise ActionJournalConflictError(
                    "durable action or command identity conflicts with an existing journal row"
                ) from exc
            except sqlite3.DatabaseError as exc:
                raise ActionJournalCorruptionError(
                    f"could not persist action journal row: {exc}"
                ) from exc

    def delete(self, *, device_id: UUID, action_id: UUID) -> None:
        with self._lock:
            self._require_open()
            try:
                with self._transaction():
                    self._connection.execute(
                        "DELETE FROM action_records WHERE device_id = ? AND action_id = ?",
                        (str(device_id), str(action_id)),
                    )
            except sqlite3.DatabaseError as exc:
                raise ActionJournalCorruptionError(
                    f"could not delete action journal row: {exc}"
                ) from exc

    def clear(self) -> None:
        with self._lock:
            self._require_open()
            try:
                with self._transaction():
                    self._connection.execute("DELETE FROM action_records")
            except sqlite3.DatabaseError as exc:
                raise ActionJournalCorruptionError(
                    f"could not clear action journal: {exc}"
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
                CREATE TABLE IF NOT EXISTS action_journal_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            row = self._connection.execute(
                "SELECT value FROM action_journal_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO action_journal_metadata(key, value) VALUES('schema_version', ?)",
                    (str(ACTION_JOURNAL_SCHEMA_VERSION),),
                )
            elif row["value"] != str(ACTION_JOURNAL_SCHEMA_VERSION):
                raise ActionJournalSchemaError(
                    "unsupported action journal schema version " + str(row["value"])
                )

            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS action_records (
                    device_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    terminal INTEGER NOT NULL CHECK (terminal IN (0, 1)),
                    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
                    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
                    PRIMARY KEY (device_id, action_id),
                    UNIQUE (device_id, command_id)
                ) WITHOUT ROWID
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS action_records_terminal_order
                ON action_records(terminal, updated_at_ms, device_id, action_id)
                """
            )

    def _decode_row(self, row: sqlite3.Row) -> ActionJournalEntryV1:
        payload_json = str(row["payload_json"])
        expected_hash = str(row["payload_sha256"])
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if not hashlib.compare_digest(expected_hash, actual_hash):
            raise ActionJournalCorruptionError(
                "action journal payload hash mismatch for "
                f"{row['device_id']}/{row['action_id']}"
            )
        try:
            decoded = json.loads(payload_json)
            entry = ActionJournalEntryV1.model_validate(decoded)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ActionJournalCorruptionError(
                "action journal payload failed model validation for "
                f"{row['device_id']}/{row['action_id']}: {exc}"
            ) from exc

        row_identity = (
            str(entry.device_id),
            str(entry.action_id),
            str(entry.command_id),
            entry.phase,
            int(entry.terminal),
            entry.updated_at_ms,
        )
        stored_identity = (
            str(row["device_id"]),
            str(row["action_id"]),
            str(row["command_id"]),
            str(row["phase"]),
            int(row["terminal"]),
            int(row["updated_at_ms"]),
        )
        if row_identity != stored_identity:
            raise ActionJournalCorruptionError(
                "action journal indexed columns do not match canonical payload for "
                f"{row['device_id']}/{row['action_id']}"
            )
        return entry

    def _verify_database_integrity(self) -> None:
        try:
            rows = self._connection.execute("PRAGMA quick_check").fetchall()
        except sqlite3.DatabaseError as exc:
            raise ActionJournalCorruptionError(
                f"action journal integrity check failed: {exc}"
            ) from exc
        messages = [str(row[0]) for row in rows]
        if messages != ["ok"]:
            raise ActionJournalCorruptionError(
                "action journal integrity check did not return ok: " + "; ".join(messages)
            )

    def _prune_terminal_locked(self) -> None:
        self._connection.execute(
            """
            DELETE FROM action_records
            WHERE (device_id, action_id) IN (
                SELECT device_id, action_id
                FROM action_records
                WHERE terminal = 1
                ORDER BY updated_at_ms DESC, device_id DESC, action_id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (self._max_terminal_records,),
        )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _require_open(self) -> None:
        if self._closed:
            raise ActionJournalClosedError("action journal is closed")
