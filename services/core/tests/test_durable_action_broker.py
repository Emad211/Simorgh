from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocket

from simorgh_core.devices.action_broker import (
    DeviceActionBroker,
    DeviceActionConflictError,
    DeviceActionJournalUnavailableError,
    DeviceActionPhase,
)
from simorgh_core.devices.action_capabilities import (
    CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
    OPEN_APP_EXECUTION_CAPABILITY,
)
from simorgh_core.devices.action_journal import (
    ActionJournalCorruptionError,
    ActionJournalEntryV1,
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
    DeviceRegistrationPayload,
    ProtocolEnvelope,
)
from simorgh_core.devices.registry import DeviceSession, registry

TARGET_PACKAGE = "com.example.target"


@dataclass
class RecordingWebSocket:
    sent: list[str] = field(default_factory=list)
    fail_writes: int = 0

    async def send_text(self, value: str) -> None:
        if self.fail_writes > 0:
            self.fail_writes -= 1
            raise OSError("fixture socket write failed")
        self.sent.append(value)


class FailingActionJournal:
    def load(self) -> list[ActionJournalEntryV1]:
        return []

    def upsert(self, entry: ActionJournalEntryV1) -> None:
        raise ActionJournalCorruptionError("fixture durable write failure")

    def delete(self, *, device_id: UUID, action_id: UUID) -> None:
        raise ActionJournalCorruptionError("fixture durable delete failure")

    def clear(self) -> None:
        raise ActionJournalCorruptionError("fixture durable clear failure")

    def close(self) -> None:
        return None


def _registration() -> DeviceRegistrationPayload:
    return DeviceRegistrationPayload(
        app_version="0.1.0",
        sdk_int=31,
        android_release="12",
        manufacturer="Samsung",
        model="SM-A536B",
        build_fingerprint="samsung/a53/durable-broker-test",
        support_tier="FULL",
        capabilities=[
            "device.action_transport.v1",
            OPEN_APP_EXECUTION_CAPABILITY,
            CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
        ],
    )


def _session(
    device_id: UUID,
    *,
    fail_writes: int = 0,
) -> tuple[DeviceSession, RecordingWebSocket]:
    websocket = RecordingWebSocket(fail_writes=fail_writes)
    return (
        DeviceSession.create(
            device_id=device_id,
            websocket=cast(WebSocket, websocket),
            registration=_registration(),
        ),
        websocket,
    )


def _command(
    *,
    command_id: UUID | None = None,
    action_id: UUID | None = None,
) -> AndroidActionCommand:
    now_ms = int(time.time() * 1000)
    return AndroidActionCommand(
        command_id=command_id or uuid4(),
        action_id=action_id or uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 60_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
        ),
    )


def _accepted_ack_envelope(
    *,
    device_id: UUID,
    command: AndroidActionCommand,
    command_envelope: ProtocolEnvelope,
) -> tuple[ProtocolEnvelope, DeviceActionCommandAckPayload]:
    acknowledgement = DeviceActionCommandAckPayload(
        command_id=command.command_id,
        action_id=command.action_id,
        status="accepted",
        received_at_ms=int(time.time() * 1000),
        detail="fixture accepted",
    )
    return (
        ProtocolEnvelope.create(
            message_type="device.action_command_ack",
            device_id=device_id,
            correlation_id=command_envelope.message_id,
            payload=acknowledgement,
        ),
        acknowledgement,
    )


def _failed_result(command: AndroidActionCommand) -> AndroidActionResult:
    now_ms = int(time.time() * 1000)
    return AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.FAILED,
        failure_code=ActionFailureCode.TARGET_NOT_FOUND,
        started_at_ms=now_ms,
        finished_at_ms=now_ms + 1,
        attempts=0,
        detail="fixture target package was not installed",
    )


def _result_envelope(
    *,
    device_id: UUID,
    command_envelope: ProtocolEnvelope,
    result: AndroidActionResult,
    message_id: UUID | None = None,
) -> ProtocolEnvelope:
    return ProtocolEnvelope(
        message_id=message_id or uuid4(),
        type="device.action_result",
        sent_at_ms=int(time.time() * 1000),
        device_id=device_id,
        correlation_id=command_envelope.message_id,
        payload=result.model_dump(mode="json"),
    )


def test_recovered_accepted_action_is_not_redelivered_and_accepts_orphaned_result(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = tmp_path / "accepted-recovery.sqlite3"
        device_id = uuid4()
        command = _command()

        journal_one = SQLiteActionJournal(path)
        broker_one = DeviceActionBroker(journal_one)
        first_session, first_socket = _session(device_id)
        await registry.register(first_session)
        try:
            delivered = await broker_one.dispatch(device_id=device_id, command=command)
            assert delivered.phase == DeviceActionPhase.DELIVERED
            assert len(first_socket.sent) == 1
            command_envelope = ProtocolEnvelope.model_validate_json(first_socket.sent[0])
            ack_envelope, acknowledgement = _accepted_ack_envelope(
                device_id=device_id,
                command=command,
                command_envelope=command_envelope,
            )
            accepted = await broker_one.record_command_ack(
                session=first_session,
                envelope=ack_envelope,
                acknowledgement=acknowledgement,
            )
            assert accepted.phase == DeviceActionPhase.ACCEPTED
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=first_session.session_id,
            )
            journal_one.close()

        journal_two = SQLiteActionJournal(path)
        broker_two = DeviceActionBroker(journal_two)
        second_session, second_socket = _session(device_id)
        await registry.register(second_session)
        try:
            await broker_two.redeliver(second_session)
            assert second_socket.sent == []
            recovered = await broker_two.get(
                device_id=device_id,
                action_id=command.action_id,
            )
            assert recovered.phase == DeviceActionPhase.ACCEPTED
            assert recovered.last_session_id == second_session.session_id
            assert "was not redelivered" in recovered.detail

            result = _failed_result(command)
            result_envelope = _result_envelope(
                device_id=device_id,
                command_envelope=command_envelope,
                result=result,
            )
            result_status, completed = await broker_two.record_result(
                session=second_session,
                envelope=result_envelope,
                result=result,
            )
            assert result_status == "accepted"
            assert completed is not None
            assert completed.phase == DeviceActionPhase.COMPLETED

            next_command = _command()
            next_record = await broker_two.dispatch(
                device_id=device_id,
                command=next_command,
            )
            assert next_record.phase == DeviceActionPhase.DELIVERED
            assert len(second_socket.sent) == 1
            assert AndroidActionCommand.model_validate(
                ProtocolEnvelope.model_validate_json(second_socket.sent[0]).payload
            ) == next_command
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=second_session.session_id,
            )
            journal_two.close()

    asyncio.run(scenario())


def test_persisted_result_replay_is_duplicate_after_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "result-replay.sqlite3"
        device_id = uuid4()
        command = _command()
        result = _failed_result(command)

        journal_one = SQLiteActionJournal(path)
        broker_one = DeviceActionBroker(journal_one)
        first_session, first_socket = _session(device_id)
        await registry.register(first_session)
        try:
            await broker_one.dispatch(device_id=device_id, command=command)
            command_envelope = ProtocolEnvelope.model_validate_json(first_socket.sent[0])
            result_envelope = _result_envelope(
                device_id=device_id,
                command_envelope=command_envelope,
                result=result,
            )
            status, record = await broker_one.record_result(
                session=first_session,
                envelope=result_envelope,
                result=result,
            )
            assert status == "accepted"
            assert record is not None
            assert record.result_ack_status is None
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=first_session.session_id,
            )
            journal_one.close()

        journal_two = SQLiteActionJournal(path)
        broker_two = DeviceActionBroker(journal_two)
        second_session, second_socket = _session(device_id)
        await registry.register(second_session)
        try:
            await broker_two.redeliver(second_session)
            assert second_socket.sent == []
            duplicate_status, duplicate_record = await broker_two.record_result(
                session=second_session,
                envelope=result_envelope,
                result=result,
            )
            assert duplicate_status == "duplicate"
            assert duplicate_record is not None

            sent_at_ms = int(time.time() * 1000)
            acknowledged = await broker_two.record_result_ack_sent(
                device_id=device_id,
                action_id=command.action_id,
                result_envelope_id=result_envelope.message_id,
                status="duplicate",
                sent_at_ms=sent_at_ms,
            )
            assert acknowledged.result_ack_status == "duplicate"
            assert acknowledged.result_ack_sent_at_ms == sent_at_ms

            conflicting_envelope = _result_envelope(
                device_id=device_id,
                command_envelope=command_envelope,
                result=result,
            )
            with pytest.raises(DeviceActionConflictError, match="different result identity"):
                await broker_two.record_result(
                    session=second_session,
                    envelope=conflicting_envelope,
                    result=result,
                )
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=second_session.session_id,
            )
            journal_two.close()

    asyncio.run(scenario())


def test_never_delivered_queued_record_is_safely_delivered_after_restart(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = tmp_path / "queued-recovery.sqlite3"
        device_id = uuid4()
        command = _command()
        command_envelope = ProtocolEnvelope.create(
            message_type="device.action_command",
            device_id=device_id,
            payload=command,
        )
        journal = SQLiteActionJournal(path)
        journal.upsert(
            new_journal_entry(
                device_id=device_id,
                command=command,
                command_envelope=command_envelope,
                phase="queued",
                created_at_ms=command.issued_at_ms,
                updated_at_ms=command.issued_at_ms,
            )
        )
        journal.close()

        recovered_journal = SQLiteActionJournal(path)
        broker = DeviceActionBroker(recovered_journal)
        session, socket = _session(device_id)
        await registry.register(session)
        try:
            await broker.redeliver(session)
            assert len(socket.sent) == 1
            sent = ProtocolEnvelope.model_validate_json(socket.sent[0])
            assert sent.message_id == command_envelope.message_id
            assert sent.payload == command_envelope.payload
            record = await broker.get(device_id=device_id, action_id=command.action_id)
            assert record.phase == DeviceActionPhase.DELIVERED
            assert record.delivery_count == 1
        finally:
            await registry.unregister(device_id=device_id, session_id=session.session_id)
            recovered_journal.close()

    asyncio.run(scenario())


def test_socket_failure_is_journaled_as_uncertain_and_not_reexecuted_after_restart(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = tmp_path / "uncertain-delivery.sqlite3"
        device_id = uuid4()
        command = _command()
        journal_one = SQLiteActionJournal(path)
        broker_one = DeviceActionBroker(journal_one)
        failing_session, failing_socket = _session(device_id, fail_writes=1)
        await registry.register(failing_session)
        try:
            record = await broker_one.dispatch(device_id=device_id, command=command)
            assert record.phase == DeviceActionPhase.DELIVERED
            assert failing_socket.sent == []
            assert record.delivery_count == 1
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=failing_session.session_id,
            )
            journal_one.close()

        journal_two = SQLiteActionJournal(path)
        broker_two = DeviceActionBroker(journal_two)
        replacement, replacement_socket = _session(device_id)
        await registry.register(replacement)
        try:
            await broker_two.redeliver(replacement)
            assert replacement_socket.sent == []
            recovered = await broker_two.get(
                device_id=device_id,
                action_id=command.action_id,
            )
            assert recovered.last_session_id == replacement.session_id
            assert "was not redelivered" in recovered.detail
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=replacement.session_id,
            )
            journal_two.close()

    asyncio.run(scenario())


def test_journal_write_failure_prevents_command_visibility_and_socket_send() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        command = _command()
        broker = DeviceActionBroker(FailingActionJournal())
        session, socket = _session(device_id)
        await registry.register(session)
        try:
            with pytest.raises(DeviceActionJournalUnavailableError, match="failed closed"):
                await broker.dispatch(device_id=device_id, command=command)
            assert socket.sent == []
            with pytest.raises(DeviceActionJournalUnavailableError, match="unavailable"):
                await broker.get(device_id=device_id, action_id=command.action_id)
        finally:
            await registry.unregister(device_id=device_id, session_id=session.session_id)

    asyncio.run(scenario())
