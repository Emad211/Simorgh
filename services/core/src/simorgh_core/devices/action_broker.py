from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from simorgh_core.devices.actions import AndroidActionCommand, AndroidActionResult
from simorgh_core.devices.protocol import (
    ActionCommandAckStatus,
    ActionResultAckStatus,
    DeviceActionCommandAckPayload,
    ProtocolEnvelope,
)
from simorgh_core.devices.registry import DeviceSession, registry

MAX_TERMINAL_ACTIONS = 256


class DeviceActionBrokerError(ValueError):
    """Base class for deterministic action broker failures."""


class DeviceActionConflictError(DeviceActionBrokerError):
    """Raised when an action or command identifier is reused with different content."""


class DeviceActionBusyError(DeviceActionBrokerError):
    """Raised when one device already has another non-terminal action."""


class DeviceActionNotFoundError(DeviceActionBrokerError):
    """Raised when an action identifier has never been dispatched."""


class DeviceActionPhase(StrEnum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_PHASES = {
    DeviceActionPhase.COMPLETED,
    DeviceActionPhase.REJECTED,
    DeviceActionPhase.EXPIRED,
    DeviceActionPhase.CANCELLED,
}


@dataclass(slots=True)
class DeviceActionRecord:
    device_id: UUID
    command: AndroidActionCommand
    command_envelope: ProtocolEnvelope
    phase: DeviceActionPhase
    created_at_ms: int
    updated_at_ms: int
    delivery_count: int = 0
    last_session_id: UUID | None = None
    command_ack: DeviceActionCommandAckPayload | None = None
    result: AndroidActionResult | None = None
    detail: str = ""

    @property
    def action_id(self) -> UUID:
        return self.command.action_id

    @property
    def command_id(self) -> UUID:
        return self.command.command_id

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES


class DeviceActionBroker:
    """Per-device single-flight action delivery with replay-safe terminal history."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._records: dict[tuple[UUID, UUID], DeviceActionRecord] = {}
        self._terminal_order: OrderedDict[tuple[UUID, UUID], None] = OrderedDict()

    async def dispatch(
        self,
        *,
        device_id: UUID,
        command: AndroidActionCommand,
    ) -> DeviceActionRecord:
        now_ms = int(time.time() * 1000)
        if command.deadline_at_ms <= now_ms:
            raise DeviceActionBrokerError("action command is already expired")

        key = (device_id, command.action_id)
        async with self._lock:
            self._expire_locked(now_ms)
            existing = self._records.get(key)
            if existing is not None:
                self._require_same_command(existing, command)
                record = existing
            else:
                active = self._active_record_for_device_locked(device_id)
                if active is not None:
                    raise DeviceActionBusyError(
                        f"device already has active action {active.action_id}"
                    )
                envelope = ProtocolEnvelope.create(
                    message_type="device.action_command",
                    device_id=device_id,
                    payload=command,
                )
                record = DeviceActionRecord(
                    device_id=device_id,
                    command=command,
                    command_envelope=envelope,
                    phase=DeviceActionPhase.QUEUED,
                    created_at_ms=now_ms,
                    updated_at_ms=now_ms,
                )
                self._records[key] = record

        session = await registry.get(device_id)
        if session is not None:
            await self._deliver(record, session)
        return record

    async def redeliver(self, session: DeviceSession) -> None:
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._active_record_for_device_locked(session.device_id)
        if record is not None:
            await self._deliver(record, session)

    async def record_command_ack(
        self,
        *,
        session: DeviceSession,
        envelope: ProtocolEnvelope,
        acknowledgement: DeviceActionCommandAckPayload,
    ) -> DeviceActionRecord:
        key = (session.device_id, acknowledgement.action_id)
        now_ms = int(time.time() * 1000)
        async with self._lock:
            record = self._records.get(key)
            if record is None:
                raise DeviceActionNotFoundError("command acknowledgement references unknown action")
            self._require_current_session(record, session)
            self._require_ack_identity(record, envelope, acknowledgement)
            previous = record.command_ack
            if previous is not None and previous != acknowledgement:
                raise DeviceActionConflictError(
                    "action command acknowledgement changed after it was recorded"
                )
            record.command_ack = acknowledgement
            record.updated_at_ms = now_ms
            record.detail = acknowledgement.detail
            record.phase = self._phase_from_command_ack(acknowledgement.status)
            if record.terminal:
                self._remember_terminal_locked(key)
            return record

    async def record_result(
        self,
        *,
        session: DeviceSession,
        envelope: ProtocolEnvelope,
        result: AndroidActionResult,
    ) -> tuple[ActionResultAckStatus, DeviceActionRecord | None]:
        key = (session.device_id, result.action_id)
        now_ms = int(time.time() * 1000)
        async with self._lock:
            record = self._records.get(key)
            if record is None:
                return "unknown_action", None
            if result.command_id != record.command_id:
                raise DeviceActionConflictError("action result command_id does not match dispatch")
            if envelope.correlation_id != record.command_envelope.message_id:
                raise DeviceActionConflictError(
                    "action result correlation_id does not match command message_id"
                )
            if record.result is not None:
                if record.result != result:
                    raise DeviceActionConflictError(
                        "completed action was replayed with a different result"
                    )
                return "duplicate", record

            self._require_current_session(record, session)
            record.result = result
            record.phase = (
                DeviceActionPhase.CANCELLED
                if result.outcome.value == "cancelled"
                else DeviceActionPhase.COMPLETED
            )
            record.updated_at_ms = now_ms
            record.detail = result.detail
            self._remember_terminal_locked(key)
            return "accepted", record

    async def get(self, *, device_id: UUID, action_id: UUID) -> DeviceActionRecord:
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get((device_id, action_id))
            if record is None:
                raise DeviceActionNotFoundError("action not found")
            return record

    async def cancel(
        self,
        *,
        device_id: UUID,
        action_id: UUID,
        reason: str,
    ) -> DeviceActionRecord:
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get((device_id, action_id))
            if record is None:
                raise DeviceActionNotFoundError("action not found")
            if record.terminal:
                return record
            cancel_envelope = ProtocolEnvelope.create(
                message_type="device.action_cancel",
                device_id=device_id,
                correlation_id=record.command_envelope.message_id,
                payload={
                    "command_id": str(record.command_id),
                    "action_id": str(record.action_id),
                    "reason": reason[:1_000],
                },
            )
            record.phase = DeviceActionPhase.CANCELLING
            record.updated_at_ms = now_ms
            record.detail = reason[:1_000]

        session = await registry.get(device_id)
        if session is not None:
            await session.send_envelope(cancel_envelope)
        return record

    async def _deliver(self, record: DeviceActionRecord, session: DeviceSession) -> None:
        if record.terminal or record.command.deadline_at_ms <= int(time.time() * 1000):
            return
        if not await registry.is_current(session):
            return
        await session.send_envelope(record.command_envelope)
        now_ms = int(time.time() * 1000)
        async with self._lock:
            current = self._records.get((record.device_id, record.action_id))
            if current is record and not record.terminal:
                record.delivery_count += 1
                record.last_session_id = session.session_id
                record.phase = DeviceActionPhase.DELIVERED
                record.updated_at_ms = now_ms

    def _active_record_for_device_locked(self, device_id: UUID) -> DeviceActionRecord | None:
        return next(
            (
                record
                for (record_device_id, _), record in self._records.items()
                if record_device_id == device_id and not record.terminal
            ),
            None,
        )

    def _expire_locked(self, now_ms: int) -> None:
        for key, record in self._records.items():
            if not record.terminal and record.command.deadline_at_ms <= now_ms:
                record.phase = DeviceActionPhase.EXPIRED
                record.updated_at_ms = now_ms
                record.detail = "action command deadline elapsed"
                self._remember_terminal_locked(key)

    def _remember_terminal_locked(self, key: tuple[UUID, UUID]) -> None:
        self._terminal_order[key] = None
        self._terminal_order.move_to_end(key)
        while len(self._terminal_order) > MAX_TERMINAL_ACTIONS:
            expired_key, _ = self._terminal_order.popitem(last=False)
            record = self._records.get(expired_key)
            if record is not None and record.terminal:
                self._records.pop(expired_key, None)

    def _require_same_command(
        self,
        record: DeviceActionRecord,
        command: AndroidActionCommand,
    ) -> None:
        if record.command != command:
            raise DeviceActionConflictError(
                "action_id was reused with different command content"
            )

    def _require_current_session(
        self,
        record: DeviceActionRecord,
        session: DeviceSession,
    ) -> None:
        if record.last_session_id is not None and record.last_session_id != session.session_id:
            raise DeviceActionConflictError("message came from an obsolete device session")

    def _require_ack_identity(
        self,
        record: DeviceActionRecord,
        envelope: ProtocolEnvelope,
        acknowledgement: DeviceActionCommandAckPayload,
    ) -> None:
        if acknowledgement.command_id != record.command_id:
            raise DeviceActionConflictError("ack command_id does not match dispatch")
        if envelope.correlation_id != record.command_envelope.message_id:
            raise DeviceActionConflictError(
                "ack correlation_id does not match command message_id"
            )

    def _phase_from_command_ack(
        self,
        status: ActionCommandAckStatus,
    ) -> DeviceActionPhase:
        return {
            "accepted": DeviceActionPhase.ACCEPTED,
            "duplicate": DeviceActionPhase.ACCEPTED,
            "busy": DeviceActionPhase.REJECTED,
            "expired": DeviceActionPhase.EXPIRED,
            "rejected": DeviceActionPhase.REJECTED,
        }[status]


action_broker = DeviceActionBroker()
