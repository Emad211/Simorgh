from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.devices.action_journal import (
    ActionJournalConflictError,
    ActionJournalEntryV1,
    InMemoryActionJournal,
    SQLiteActionJournal,
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
    DeviceActionCommandAckPayload,
    ProtocolEnvelope,
)

DEVICE_ID = UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = UUID("22222222-2222-2222-2222-222222222222")
TARGET_PACKAGE = "com.example.target"


def _command(
    *,
    command_id: UUID | None = None,
    action_id: UUID | None = None,
    package_name: str = TARGET_PACKAGE,
) -> AndroidActionCommand:
    return AndroidActionCommand(
        command_id=command_id or uuid4(),
        action_id=action_id or uuid4(),
        issued_at_ms=1_000,
        deadline_at_ms=61_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(package_name=package_name),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=package_name)]
        ),
    )


def _envelope(
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


def _queued(
    command: AndroidActionCommand,
    envelope: ProtocolEnvelope,
) -> ActionJournalEntryV1:
    return new_journal_entry(
        device_id=DEVICE_ID,
        command=command,
        command_envelope=envelope,
        phase="queued",
        created_at_ms=1_000,
        updated_at_ms=1_000,
    )


def _delivered(entry: ActionJournalEntryV1) -> ActionJournalEntryV1:
    return new_journal_entry(
        device_id=entry.device_id,
        command=entry.command,
        command_envelope=entry.command_envelope,
        phase="delivered",
        created_at_ms=entry.created_at_ms,
        updated_at_ms=1_100,
        delivery_count=1,
        last_session_id=SESSION_ID,
    )


def _accepted(entry: ActionJournalEntryV1) -> ActionJournalEntryV1:
    acknowledgement = DeviceActionCommandAckPayload(
        command_id=entry.command_id,
        action_id=entry.action_id,
        status="accepted",
        received_at_ms=1_200,
        detail="transition fixture accepted",
    )
    return new_journal_entry(
        device_id=entry.device_id,
        command=entry.command,
        command_envelope=entry.command_envelope,
        phase="accepted",
        created_at_ms=entry.created_at_ms,
        updated_at_ms=1_200,
        delivery_count=1,
        last_session_id=SESSION_ID,
        command_ack=acknowledgement,
    )


def _completed(entry: ActionJournalEntryV1) -> ActionJournalEntryV1:
    result = AndroidActionResult(
        command_id=entry.command_id,
        action_id=entry.action_id,
        outcome=ActionOutcome.FAILED,
        failure_code=ActionFailureCode.TARGET_NOT_FOUND,
        started_at_ms=1_300,
        finished_at_ms=1_301,
        attempts=0,
        detail="transition fixture target not found",
    )
    return new_journal_entry(
        device_id=entry.device_id,
        command=entry.command,
        command_envelope=entry.command_envelope,
        phase="completed",
        created_at_ms=entry.created_at_ms,
        updated_at_ms=1_400,
        delivery_count=1,
        last_session_id=SESSION_ID,
        command_ack=entry.command_ack,
        result=result,
        result_envelope_id=uuid4(),
        result_correlation_id=entry.command_envelope.message_id,
        detail=result.detail,
    )


def _journals(tmp_path: Path):
    memory = InMemoryActionJournal()
    sqlite = SQLiteActionJournal(tmp_path / "transition-journal.sqlite3")
    return memory, sqlite


def test_valid_lifecycle_is_identical_in_memory_and_sqlite(tmp_path: Path) -> None:
    command = _command()
    envelope = _envelope(command)
    queued = _queued(command, envelope)
    delivered = _delivered(queued)
    accepted = _accepted(delivered)
    completed = _completed(accepted)

    for journal in _journals(tmp_path):
        try:
            for entry in (queued, delivered, accepted, completed):
                journal.upsert(entry)
            assert journal.load() == [completed]
        finally:
            journal.close()


def test_same_action_id_cannot_be_rebound_to_another_command(tmp_path: Path) -> None:
    action_id = uuid4()
    first_command = _command(action_id=action_id)
    first = _queued(first_command, _envelope(first_command))
    other_command = _command(action_id=action_id, package_name="com.example.other")
    conflicting = _queued(other_command, _envelope(other_command))

    for journal in _journals(tmp_path):
        try:
            journal.upsert(first)
            with pytest.raises(ActionJournalConflictError, match="command content is immutable"):
                journal.upsert(conflicting)
            assert journal.load() == [first]
        finally:
            journal.close()


def test_command_envelope_and_created_time_are_immutable(tmp_path: Path) -> None:
    command = _command()
    original = _queued(command, _envelope(command))
    changed_envelope = _queued(command, _envelope(command))
    changed_created = original.model_copy(
        update={"created_at_ms": 999, "updated_at_ms": 1_000}
    )

    for journal in _journals(tmp_path):
        try:
            journal.upsert(original)
            with pytest.raises(ActionJournalConflictError, match="command envelope"):
                journal.upsert(changed_envelope)
            with pytest.raises(ActionJournalConflictError, match="created_at_ms"):
                journal.upsert(changed_created)
        finally:
            journal.close()


def test_delivery_count_and_phase_cannot_move_backwards(tmp_path: Path) -> None:
    command = _command()
    queued = _queued(command, _envelope(command))
    delivered = _delivered(queued)
    accepted = _accepted(delivered)
    lower_delivery = accepted.model_copy(
        update={
            "phase": "accepted",
            "delivery_count": 0,
            "last_session_id": None,
            "updated_at_ms": 1_300,
        }
    )
    backwards_phase = delivered.model_copy(update={"updated_at_ms": 1_300})

    for journal in _journals(tmp_path):
        try:
            journal.upsert(queued)
            journal.upsert(delivered)
            journal.upsert(accepted)
            with pytest.raises(ActionJournalConflictError, match="delivery_count cannot decrease"):
                journal.upsert(lower_delivery)
            with pytest.raises(ActionJournalConflictError, match="phase transition"):
                journal.upsert(backwards_phase)
        finally:
            journal.close()


def test_persisted_result_identity_cannot_change(tmp_path: Path) -> None:
    command = _command()
    completed = _completed(_accepted(_delivered(_queued(command, _envelope(command)))))
    conflicting = completed.model_copy(update={"result_envelope_id": uuid4()})

    for journal in _journals(tmp_path):
        try:
            journal.upsert(completed)
            with pytest.raises(ActionJournalConflictError, match="result identity"):
                journal.upsert(conflicting)
            assert journal.load() == [completed]
        finally:
            journal.close()


def test_invalid_phase_shape_is_rejected_before_storage() -> None:
    command = _command()
    queued = _queued(command, _envelope(command))

    with pytest.raises(ValueError, match="queued phase cannot contain delivery"):
        ActionJournalEntryV1.model_validate(
            queued.model_copy(
                update={
                    "delivery_count": 1,
                    "last_session_id": SESSION_ID,
                }
            ).model_dump(mode="json")
        )
