from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.devices.action_journal import (
    ACTION_JOURNAL_SCHEMA_VERSION,
    ActionJournalClosedError,
    ActionJournalConflictError,
    ActionJournalCorruptionError,
    ActionJournalEntryV1,
    ActionJournalSchemaError,
    InMemoryActionJournal,
    SQLiteActionJournal,
    canonical_json,
    canonical_sha256,
    new_journal_entry,
)
from simorgh_core.devices.actions import (
    ActionFailureCode,
    ActionOutcome,
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidActionResult,
    AndroidVerificationPolicy,
    ObservationPrecondition,
    OpenAppOperation,
)
from simorgh_core.devices.protocol import (
    ActionResultAckStatus,
    DeviceActionCancelAckPayload,
    DeviceActionCommandAckPayload,
    ProtocolEnvelope,
)

DEVICE_ID = UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = UUID("22222222-2222-2222-2222-222222222222")
COMMAND_ID = UUID("33333333-3333-3333-3333-333333333333")
ACTION_ID = UUID("44444444-4444-4444-4444-444444444444")
TARGET_PACKAGE = "com.example.target"


def _command(
    *,
    command_id: UUID = COMMAND_ID,
    action_id: UUID = ACTION_ID,
) -> AndroidActionCommand:
    return AndroidActionCommand(
        command_id=command_id,
        action_id=action_id,
        issued_at_ms=1_000,
        deadline_at_ms=61_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
        ),
    )


def _command_envelope(
    command: AndroidActionCommand,
    *,
    message_id: UUID | None = None,
) -> ProtocolEnvelope:
    return ProtocolEnvelope(
        message_id=message_id or uuid4(),
        type="device.action_command",
        sent_at_ms=1_000,
        device_id=DEVICE_ID,
        payload=command.model_dump(mode="json"),
    )


def _completed_entry(
    *,
    command_id: UUID = COMMAND_ID,
    action_id: UUID = ACTION_ID,
    updated_at_ms: int = 2_000,
    ack_status: ActionResultAckStatus | None = "accepted",
    command_message_id: UUID | None = None,
    result_message_id: UUID | None = None,
) -> ActionJournalEntryV1:
    command = _command(command_id=command_id, action_id=action_id)
    command_envelope = _command_envelope(command, message_id=command_message_id)
    result = AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.BLOCKED,
        failure_code=ActionFailureCode.PRECONDITION_FAILED,
        started_at_ms=1_500,
        finished_at_ms=1_600,
        attempts=0,
        detail="fixture precondition changed",
    )
    return new_journal_entry(
        device_id=DEVICE_ID,
        command=command,
        command_envelope=command_envelope,
        phase="completed",
        created_at_ms=1_000,
        updated_at_ms=updated_at_ms,
        delivery_count=1,
        last_session_id=SESSION_ID,
        command_ack=DeviceActionCommandAckPayload(
            command_id=command.command_id,
            action_id=command.action_id,
            status="accepted",
            received_at_ms=1_200,
            detail="fixture accepted",
        ),
        cancel_envelope=ProtocolEnvelope(
            message_id=uuid4(),
            type="device.action_cancel",
            sent_at_ms=1_300,
            device_id=DEVICE_ID,
            correlation_id=command_envelope.message_id,
            payload={
                "command_id": str(command.command_id),
                "action_id": str(command.action_id),
                "reason": "fixture cancellation",
            },
        ),
        cancel_ack=DeviceActionCancelAckPayload(
            command_id=command.command_id,
            action_id=command.action_id,
            status="accepted",
            received_at_ms=1_400,
        ),
        result=result,
        result_envelope_id=result_message_id or uuid4(),
        result_correlation_id=command_envelope.message_id,
        result_ack_status=ack_status,
        result_ack_sent_at_ms=(1_700 if ack_status is not None else None),
        detail=result.detail,
    )


def _queued_entry(
    *,
    command_id: UUID = COMMAND_ID,
    action_id: UUID = ACTION_ID,
    command_message_id: UUID | None = None,
) -> ActionJournalEntryV1:
    command = _command(command_id=command_id, action_id=action_id)
    return new_journal_entry(
        device_id=DEVICE_ID,
        command=command,
        command_envelope=_command_envelope(command, message_id=command_message_id),
        phase="queued",
        created_at_ms=1_000,
        updated_at_ms=1_000,
    )


def _database_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "action-journal.sqlite3"


def test_sqlite_round_trip_survives_close_and_reopen(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    entry = _completed_entry()

    journal = SQLiteActionJournal(path)
    journal.upsert(entry)
    journal.close()

    reopened = SQLiteActionJournal(path)
    try:
        assert reopened.load() == [entry]
    finally:
        reopened.close()


def test_in_memory_and_sqlite_share_validation_contract(tmp_path: Path) -> None:
    entry = _completed_entry()
    memory = InMemoryActionJournal()
    sqlite = SQLiteActionJournal(_database_path(tmp_path))
    try:
        memory.upsert(entry)
        sqlite.upsert(entry)

        assert memory.load() == sqlite.load() == [entry]
    finally:
        memory.close()
        sqlite.close()


def test_complete_payload_hash_detects_manual_tampering(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    journal = SQLiteActionJournal(path)
    journal.upsert(_completed_entry())
    journal.close()

    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT payload_json FROM action_records WHERE action_id = ?",
            (str(ACTION_ID),),
        ).fetchone()
        assert row is not None
        payload = json.loads(str(row[0]))
        payload["detail"] = "tampered after commit"
        connection.execute(
            "UPDATE action_records SET payload_json = ? WHERE action_id = ?",
            (
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                str(ACTION_ID),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    corrupted = SQLiteActionJournal(path)
    try:
        with pytest.raises(ActionJournalCorruptionError, match="payload hash mismatch"):
            corrupted.load()
    finally:
        corrupted.close()


def test_indexed_column_mismatch_detects_manual_tampering(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    journal = SQLiteActionJournal(path)
    journal.upsert(_completed_entry())
    journal.close()

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE action_records SET phase = 'rejected' WHERE action_id = ?",
            (str(ACTION_ID),),
        )
        connection.commit()
    finally:
        connection.close()

    corrupted = SQLiteActionJournal(path)
    try:
        with pytest.raises(ActionJournalCorruptionError, match="indexed columns"):
            corrupted.load()
    finally:
        corrupted.close()


def test_unknown_schema_version_fails_closed(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE action_journal_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO action_journal_metadata(key, value) VALUES('schema_version', '999')"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ActionJournalSchemaError, match="unsupported"):
        SQLiteActionJournal(path)


def test_command_id_conflict_is_atomic_and_preserves_original(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    first = _queued_entry()
    conflicting = _queued_entry(action_id=uuid4())
    journal = SQLiteActionJournal(path)
    try:
        journal.upsert(first)
        with pytest.raises(ActionJournalConflictError):
            journal.upsert(conflicting)

        assert journal.load() == [first]
    finally:
        journal.close()


def test_command_and_result_message_ids_are_globally_unique(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    command_message_id = uuid4()
    result_message_id = uuid4()
    first = _completed_entry(
        command_id=uuid4(),
        action_id=uuid4(),
        command_message_id=command_message_id,
        result_message_id=result_message_id,
    )
    journal = SQLiteActionJournal(path)
    try:
        journal.upsert(first)
        with pytest.raises(ActionJournalConflictError):
            journal.upsert(
                _completed_entry(
                    command_id=uuid4(),
                    action_id=uuid4(),
                    command_message_id=command_message_id,
                )
            )
        with pytest.raises(ActionJournalConflictError):
            journal.upsert(
                _completed_entry(
                    command_id=uuid4(),
                    action_id=uuid4(),
                    result_message_id=result_message_id,
                )
            )

        assert journal.load() == [first]
    finally:
        journal.close()


def test_terminal_retention_prunes_oldest_rows_only(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    journal = SQLiteActionJournal(path, max_terminal_records=2)
    first = _completed_entry(
        command_id=uuid4(),
        action_id=uuid4(),
        updated_at_ms=2_000,
    )
    second = _completed_entry(
        command_id=uuid4(),
        action_id=uuid4(),
        updated_at_ms=3_000,
    )
    third = _completed_entry(
        command_id=uuid4(),
        action_id=uuid4(),
        updated_at_ms=4_000,
    )
    queued = _queued_entry(command_id=uuid4(), action_id=uuid4())
    try:
        for entry in (first, second, queued, third):
            journal.upsert(entry)

        loaded = journal.load()
        loaded_action_ids = {entry.action_id for entry in loaded}
        assert first.action_id not in loaded_action_ids
        assert loaded_action_ids == {
            second.action_id,
            third.action_id,
            queued.action_id,
        }
    finally:
        journal.close()


def test_delete_is_durable(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    journal = SQLiteActionJournal(path)
    journal.upsert(_queued_entry())
    journal.delete(device_id=DEVICE_ID, action_id=ACTION_ID)
    journal.close()

    reopened = SQLiteActionJournal(path)
    try:
        assert reopened.load() == []
    finally:
        reopened.close()


def test_closed_journal_rejects_all_operations(tmp_path: Path) -> None:
    journal = SQLiteActionJournal(_database_path(tmp_path))
    journal.close()

    with pytest.raises(ActionJournalClosedError):
        journal.load()
    with pytest.raises(ActionJournalClosedError):
        journal.upsert(_queued_entry())
    with pytest.raises(ActionJournalClosedError):
        journal.delete(device_id=DEVICE_ID, action_id=ACTION_ID)


def test_entry_rejects_result_hash_or_ack_shape_mismatch() -> None:
    entry = _completed_entry()
    payload = entry.model_dump(mode="json")
    payload["result_payload_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="result_payload_sha256"):
        ActionJournalEntryV1.model_validate(payload)

    payload = entry.model_dump(mode="json")
    payload["result_ack_sent_at_ms"] = None
    with pytest.raises(ValueError, match="present together"):
        ActionJournalEntryV1.model_validate(payload)


def test_canonical_serialization_is_stable_and_schema_is_versioned() -> None:
    entry = _completed_entry()
    reconstructed = ActionJournalEntryV1.model_validate(entry.model_dump(mode="json"))

    assert entry.schema_version == ACTION_JOURNAL_SCHEMA_VERSION
    assert canonical_json(entry) == canonical_json(reconstructed)
    assert canonical_sha256(entry) == canonical_sha256(reconstructed)
