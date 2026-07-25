from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from starlette.websockets import WebSocketDisconnect

from simorgh_core.devices.action_capabilities import (
    AndroidActionCapabilityRequirement,
    UnsupportedAndroidOperationError,
    missing_capabilities,
    requirement_for_operation,
)
from simorgh_core.devices.action_journal import (
    ActionJournal,
    ActionJournalCorruptionError,
    ActionJournalEntryV1,
    ActionJournalError,
    InMemoryActionJournal,
    canonical_sha256,
    new_journal_entry,
)
from simorgh_core.devices.actions import AndroidActionCommand, AndroidActionResult
from simorgh_core.devices.protocol import (
    ActionCommandAckStatus,
    ActionResultAckStatus,
    DeviceActionCancelAckPayload,
    DeviceActionCommandAckPayload,
    ProtocolEnvelope,
)
from simorgh_core.devices.registry import DeviceSession, registry

MAX_TERMINAL_ACTIONS = 256
_MAX_SESSION_RESOLUTION_ATTEMPTS = 3
_ACCEPTED_COMMAND_ACKS = frozenset({"accepted", "duplicate"})
_ACCEPTED_CANCEL_ACKS = frozenset({"accepted", "duplicate"})


class DeviceActionBrokerError(ValueError):
    """Base class for deterministic action broker failures."""


class DeviceActionConflictError(DeviceActionBrokerError):
    """Raised when an action or command identifier is reused with different content."""


class DeviceActionBusyError(DeviceActionBrokerError):
    """Raised when one device already has another non-terminal action."""


class DeviceActionNotFoundError(DeviceActionBrokerError):
    """Raised when an action identifier has never been dispatched."""


class DeviceActionDeviceUnavailableError(DeviceActionBrokerError):
    """Raised when no current connected device Session can own dispatch."""

    def __init__(self, operation_kind: str, message: str = "device is not connected") -> None:
        self.operation_kind = operation_kind
        super().__init__(message)


class DeviceActionUnsupportedOperationError(DeviceActionBrokerError):
    """Raised when the action schema has no enabled execution-capability mapping."""

    def __init__(self, operation_kind: str) -> None:
        self.operation_kind = operation_kind
        super().__init__(
            f"Android operation {operation_kind!r} is not enabled for Core dispatch"
        )


class DeviceActionUnsupportedCapabilityError(DeviceActionBrokerError):
    """Raised when the current Session lacks a required versioned capability."""

    def __init__(
        self,
        *,
        operation_kind: str,
        required_capabilities: tuple[str, ...],
        missing: tuple[str, ...],
        available: tuple[str, ...],
    ) -> None:
        self.operation_kind = operation_kind
        self.required_capabilities = required_capabilities
        self.missing_capabilities = missing
        self.available_capabilities = available
        super().__init__(
            "current device session lacks required capability: " + ", ".join(missing)
        )


class DeviceActionJournalUnavailableError(DeviceActionBrokerError):
    """Raised after a journal failure makes further action transitions unsafe."""


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
    cancel_envelope: ProtocolEnvelope | None = None
    cancel_ack: DeviceActionCancelAckPayload | None = None
    result: AndroidActionResult | None = None
    result_envelope_id: UUID | None = None
    result_correlation_id: UUID | None = None
    result_payload_sha256: str | None = None
    result_ack_status: ActionResultAckStatus | None = None
    result_ack_sent_at_ms: int | None = None
    detail: str = ""
    recovered_from_journal: bool = False

    @property
    def action_id(self) -> UUID:
        return self.command.action_id

    @property
    def command_id(self) -> UUID:
        return self.command.command_id

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    @property
    def may_have_crossed_device_boundary(self) -> bool:
        return (
            self.delivery_count > 0
            or self.last_session_id is not None
            or self.command_ack is not None
        )


class DeviceActionBroker:
    """Per-device single-flight broker backed by one strict action journal."""

    def __init__(
        self,
        journal: ActionJournal | None = None,
        *,
        max_terminal_actions: int = MAX_TERMINAL_ACTIONS,
    ) -> None:
        if max_terminal_actions < 0:
            raise ValueError("max_terminal_actions cannot be negative")
        self._lock = asyncio.Lock()
        self._journal: ActionJournal = journal or InMemoryActionJournal(
            max_terminal_records=max_terminal_actions
        )
        self._max_terminal_actions = max_terminal_actions
        self._records: dict[tuple[UUID, UUID], DeviceActionRecord] = {}
        self._terminal_order: OrderedDict[tuple[UUID, UUID], None] = OrderedDict()
        self._journal_failure: ActionJournalError | None = None
        self._load_initial_journal()

    async def configure_journal(
        self,
        journal: ActionJournal,
        *,
        max_terminal_actions: int = MAX_TERMINAL_ACTIONS,
    ) -> None:
        """Replace runtime state with one fully validated journal at app startup."""

        if max_terminal_actions < 0:
            raise ValueError("max_terminal_actions cannot be negative")
        entries = journal.load()
        records, terminal_order = self._decode_loaded_entries(entries)
        now_ms = int(time.time() * 1000)
        for key, record in list(records.items()):
            if record.terminal or record.command.deadline_at_ms > now_ms:
                continue
            expired = replace(
                record,
                phase=DeviceActionPhase.EXPIRED,
                updated_at_ms=now_ms,
                detail="action command deadline elapsed during Core recovery",
            )
            journal.upsert(self._entry_from_record(expired))
            records[key] = expired
            terminal_order[key] = None

        self._prune_loaded_terminal_records(
            records=records,
            terminal_order=terminal_order,
            maximum=max_terminal_actions,
        )
        async with self._lock:
            old_journal = self._journal
            self._journal = journal
            self._max_terminal_actions = max_terminal_actions
            self._records = records
            self._terminal_order = terminal_order
            self._journal_failure = None
        old_journal.close()

    async def reset_to_memory_journal(self) -> None:
        """Close configured storage and reset globals after one application lifespan."""

        replacement = InMemoryActionJournal(
            max_terminal_records=MAX_TERMINAL_ACTIONS
        )
        async with self._lock:
            old_journal = self._journal
            self._journal = replacement
            self._max_terminal_actions = MAX_TERMINAL_ACTIONS
            self._records.clear()
            self._terminal_order.clear()
            self._journal_failure = None
        old_journal.close()

    async def dispatch(
        self,
        *,
        device_id: UUID,
        command: AndroidActionCommand,
    ) -> DeviceActionRecord:
        now_ms = int(time.time() * 1000)
        if command.deadline_at_ms <= now_ms:
            raise DeviceActionBrokerError("action command is already expired")

        requirement = self._requirement_for_command(command)
        initial_session = await registry.get(device_id)
        self._require_compatible_session(initial_session, requirement)

        key = (device_id, command.action_id)
        created = False
        async with self._lock:
            self._require_healthy_locked()
            self._expire_locked(now_ms)
            command_owner = self._record_for_command_id_locked(
                device_id=device_id,
                command_id=command.command_id,
            )
            if command_owner is not None and command_owner.action_id != command.action_id:
                raise DeviceActionConflictError(
                    "command_id was reused for a different action_id"
                )

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
                record = self._commit_candidate_locked(
                    DeviceActionRecord(
                        device_id=device_id,
                        command=command,
                        command_envelope=envelope,
                        phase=DeviceActionPhase.QUEUED,
                        created_at_ms=now_ms,
                        updated_at_ms=now_ms,
                    )
                )
                created = True

        if record.terminal:
            return record
        if record.recovered_from_journal and record.may_have_crossed_device_boundary:
            assert initial_session is not None
            return await self._transfer_recovered_ownership(
                record=record,
                session=initial_session,
            )

        try:
            return await self._deliver_command_to_current_session(
                record=record,
                requirement=requirement,
            )
        except (
            DeviceActionDeviceUnavailableError,
            DeviceActionUnsupportedCapabilityError,
        ):
            if created:
                await self._rollback_never_delivered_record(record)
            raise

    async def redeliver(self, session: DeviceSession) -> None:
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._require_healthy_locked()
            self._expire_locked(now_ms)
            record = self._active_record_for_device_locked(session.device_id)
        if record is None:
            return

        if record.phase == DeviceActionPhase.CANCELLING and record.cancel_envelope is not None:
            await self._deliver_cancel(record=record, session=session)
            return

        if record.recovered_from_journal and record.may_have_crossed_device_boundary:
            await self._transfer_recovered_ownership(record=record, session=session)
            return

        try:
            requirement = self._requirement_for_command(record.command)
        except DeviceActionUnsupportedOperationError as exc:
            await self._note_incompatible_redelivery(record=record, detail=str(exc))
            return

        missing = missing_capabilities(
            requirement,
            session.registration.capabilities,
        )
        if missing:
            await self._note_incompatible_redelivery(
                record=record,
                detail=(
                    "current replacement session lacks required capability: "
                    + ", ".join(missing)
                    + "; command was not redelivered"
                ),
            )
            return

        await self._deliver_command(record=record, session=session)

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
            self._require_healthy_locked()
            record = self._records.get(key)
            if record is None:
                raise DeviceActionNotFoundError(
                    "command acknowledgement references unknown action"
                )
            self._require_current_session(record, session)
            self._require_ack_identity(record, envelope, acknowledgement)

            if record.result is not None or record.terminal:
                return record

            previous = record.command_ack
            if previous is not None:
                if self._command_ack_statuses_are_equivalent(
                    previous.status,
                    acknowledgement.status,
                ):
                    return record
                raise DeviceActionConflictError(
                    "action command acknowledgement changed after it was recorded"
                )

            next_phase = self._phase_from_command_ack(acknowledgement.status)
            if (
                record.phase == DeviceActionPhase.CANCELLING
                and next_phase == DeviceActionPhase.ACCEPTED
            ):
                next_phase = DeviceActionPhase.CANCELLING
            return self._commit_candidate_locked(
                replace(
                    record,
                    command_ack=acknowledgement,
                    phase=next_phase,
                    updated_at_ms=now_ms,
                    detail=acknowledgement.detail,
                )
            )

    async def record_cancel_ack(
        self,
        *,
        session: DeviceSession,
        envelope: ProtocolEnvelope,
        acknowledgement: DeviceActionCancelAckPayload,
    ) -> DeviceActionRecord:
        key = (session.device_id, acknowledgement.action_id)
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._require_healthy_locked()
            record = self._records.get(key)
            if record is None:
                raise DeviceActionNotFoundError(
                    "cancel acknowledgement references unknown action"
                )
            self._require_current_session(record, session)
            if acknowledgement.command_id != record.command_id:
                raise DeviceActionConflictError("cancel ack command_id does not match dispatch")
            cancel_envelope = record.cancel_envelope
            if cancel_envelope is None or envelope.correlation_id != cancel_envelope.message_id:
                raise DeviceActionConflictError(
                    "cancel ack correlation_id does not match cancel message_id"
                )

            previous = record.cancel_ack
            if previous is not None:
                if self._cancel_ack_statuses_are_equivalent(
                    previous.status,
                    acknowledgement.status,
                ):
                    return record
                raise DeviceActionConflictError(
                    "action cancellation acknowledgement changed after it was recorded"
                )

            detail = record.detail
            if acknowledgement.status == "not_found":
                detail = "device did not have an active matching action"
            return self._commit_candidate_locked(
                replace(
                    record,
                    cancel_ack=acknowledgement,
                    updated_at_ms=now_ms,
                    detail=detail,
                )
            )

    async def record_result(
        self,
        *,
        session: DeviceSession,
        envelope: ProtocolEnvelope,
        result: AndroidActionResult,
    ) -> tuple[ActionResultAckStatus, DeviceActionRecord | None]:
        key = (session.device_id, result.action_id)
        now_ms = int(time.time() * 1000)
        result_hash = canonical_sha256(result)
        async with self._lock:
            self._require_healthy_locked()
            record = self._records.get(key)
            if record is None:
                return "unknown_action", None
            if result.command_id != record.command_id:
                raise DeviceActionConflictError(
                    "action result command_id does not match dispatch"
                )
            if envelope.correlation_id != record.command_envelope.message_id:
                raise DeviceActionConflictError(
                    "action result correlation_id does not match command message_id"
                )

            if record.result is not None:
                if (
                    record.result != result
                    or record.result_envelope_id != envelope.message_id
                    or record.result_correlation_id != envelope.correlation_id
                    or record.result_payload_sha256 != result_hash
                ):
                    raise DeviceActionConflictError(
                        "completed action was replayed with different result identity or content"
                    )
                return "duplicate", record

            if not record.recovered_from_journal:
                self._require_current_session(record, session)
            if record.phase == DeviceActionPhase.REJECTED:
                raise DeviceActionConflictError(
                    "rejected action cannot later publish a result"
                )

            candidate = replace(
                record,
                result=result,
                result_envelope_id=envelope.message_id,
                result_correlation_id=envelope.correlation_id,
                result_payload_sha256=result_hash,
                phase=(
                    DeviceActionPhase.CANCELLED
                    if result.outcome.value == "cancelled"
                    else DeviceActionPhase.COMPLETED
                ),
                updated_at_ms=now_ms,
                last_session_id=session.session_id,
                detail=result.detail,
                recovered_from_journal=False,
            )
            return "accepted", self._commit_candidate_locked(candidate)

    async def record_result_ack_sent(
        self,
        *,
        device_id: UUID,
        action_id: UUID,
        result_envelope_id: UUID,
        status: ActionResultAckStatus,
        sent_at_ms: int,
    ) -> DeviceActionRecord:
        if status not in {"accepted", "duplicate"}:
            raise DeviceActionConflictError(
                "only accepted or duplicate result ACKs can be journaled"
            )
        key = (device_id, action_id)
        async with self._lock:
            self._require_healthy_locked()
            record = self._records.get(key)
            if record is None or record.result is None:
                raise DeviceActionNotFoundError(
                    "result ACK bookkeeping references unknown durable result"
                )
            if record.result_envelope_id != result_envelope_id:
                raise DeviceActionConflictError(
                    "result ACK message_id does not match durable result"
                )
            return self._commit_candidate_locked(
                replace(
                    record,
                    result_ack_status=status,
                    result_ack_sent_at_ms=sent_at_ms,
                    updated_at_ms=max(record.updated_at_ms, sent_at_ms),
                )
            )

    async def get(self, *, device_id: UUID, action_id: UUID) -> DeviceActionRecord:
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._require_healthy_locked()
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
            self._require_healthy_locked()
            self._expire_locked(now_ms)
            record = self._records.get((device_id, action_id))
            if record is None:
                raise DeviceActionNotFoundError("action not found")
            if record.terminal:
                return record
            cancel_envelope = record.cancel_envelope or ProtocolEnvelope.create(
                message_type="device.action_cancel",
                device_id=device_id,
                correlation_id=record.command_envelope.message_id,
                payload={
                    "command_id": str(record.command_id),
                    "action_id": str(record.action_id),
                    "reason": reason[:1_000],
                },
            )
            record = self._commit_candidate_locked(
                replace(
                    record,
                    cancel_envelope=cancel_envelope,
                    phase=DeviceActionPhase.CANCELLING,
                    updated_at_ms=now_ms,
                    detail=reason[:1_000],
                )
            )

        session = await registry.get(device_id)
        if session is not None:
            await self._deliver_cancel(record=record, session=session)
        return record

    async def clear(self) -> None:
        """Reset broker and journal state for deterministic tests."""

        async with self._lock:
            self._require_healthy_locked()
            try:
                self._journal.clear()
            except ActionJournalError as exc:
                self._mark_journal_failed_locked(exc)
            self._records.clear()
            self._terminal_order.clear()

    async def _deliver_command_to_current_session(
        self,
        *,
        record: DeviceActionRecord,
        requirement: AndroidActionCapabilityRequirement,
    ) -> DeviceActionRecord:
        for _ in range(_MAX_SESSION_RESOLUTION_ATTEMPTS):
            session = await registry.get(record.device_id)
            self._require_compatible_session(session, requirement)
            assert session is not None
            delivered = await self._deliver_command(record=record, session=session)
            if delivered is not None:
                return delivered
        raise DeviceActionDeviceUnavailableError(
            requirement.operation_kind,
            "device session changed repeatedly before action delivery",
        )

    async def _deliver_command(
        self,
        *,
        record: DeviceActionRecord,
        session: DeviceSession,
    ) -> DeviceActionRecord | None:
        if not await registry.is_current(session):
            return None
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._require_healthy_locked()
            current = self._records.get((record.device_id, record.action_id))
            if current is None or current.terminal:
                return current
            current = self._commit_candidate_locked(
                replace(
                    current,
                    phase=DeviceActionPhase.DELIVERED,
                    updated_at_ms=now_ms,
                    delivery_count=current.delivery_count + 1,
                    last_session_id=session.session_id,
                    detail="command delivery attempt journaled before socket write",
                    recovered_from_journal=False,
                )
            )

        try:
            await session.send_envelope(current.command_envelope)
        except (OSError, RuntimeError, WebSocketDisconnect):
            await self._annotate_transport_pause(
                record=current,
                detail="command socket write failed; exact envelope awaits reconnect",
            )
        return current

    async def _deliver_cancel(
        self,
        *,
        record: DeviceActionRecord,
        session: DeviceSession,
    ) -> DeviceActionRecord:
        envelope = record.cancel_envelope
        if envelope is None or not await registry.is_current(session):
            return record
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._require_healthy_locked()
            current = self._records.get((record.device_id, record.action_id))
            if current is None or current.terminal:
                return current or record
            current = self._commit_candidate_locked(
                replace(
                    current,
                    phase=DeviceActionPhase.CANCELLING,
                    updated_at_ms=now_ms,
                    last_session_id=(
                        session.session_id
                        if current.delivery_count > 0
                        else current.last_session_id
                    ),
                    detail="cancellation delivery journaled before socket write",
                )
            )
        try:
            await session.send_envelope(envelope)
        except (OSError, RuntimeError, WebSocketDisconnect):
            await self._annotate_transport_pause(
                record=current,
                detail="cancellation socket write failed; exact envelope awaits reconnect",
            )
        return current

    async def _transfer_recovered_ownership(
        self,
        *,
        record: DeviceActionRecord,
        session: DeviceSession,
    ) -> DeviceActionRecord:
        if not await registry.is_current(session):
            return record
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._require_healthy_locked()
            current = self._records.get((record.device_id, record.action_id))
            if current is None or current.terminal:
                return current or record
            return self._commit_candidate_locked(
                replace(
                    current,
                    last_session_id=session.session_id,
                    updated_at_ms=now_ms,
                    detail=(
                        "recovered action ownership transferred to current session; "
                        "command was not redelivered because prior delivery is uncertain"
                    ),
                )
            )

    async def _annotate_transport_pause(
        self,
        *,
        record: DeviceActionRecord,
        detail: str,
    ) -> None:
        async with self._lock:
            self._require_healthy_locked()
            current = self._records.get((record.device_id, record.action_id))
            if current is None or current.terminal:
                return
            self._commit_candidate_locked(
                replace(
                    current,
                    updated_at_ms=max(current.updated_at_ms, int(time.time() * 1000)),
                    detail=detail[:2_000],
                )
            )

    async def _rollback_never_delivered_record(self, record: DeviceActionRecord) -> None:
        key = (record.device_id, record.action_id)
        async with self._lock:
            self._require_healthy_locked()
            current = self._records.get(key)
            if (
                current is not None
                and current.phase == DeviceActionPhase.QUEUED
                and current.delivery_count == 0
                and current.last_session_id is None
                and current.command_ack is None
                and current.result is None
                and current.cancel_envelope is None
            ):
                try:
                    self._journal.delete(
                        device_id=current.device_id,
                        action_id=current.action_id,
                    )
                except ActionJournalError as exc:
                    self._mark_journal_failed_locked(exc)
                self._records.pop(key, None)

    async def _note_incompatible_redelivery(
        self,
        *,
        record: DeviceActionRecord,
        detail: str,
    ) -> None:
        now_ms = int(time.time() * 1000)
        async with self._lock:
            self._require_healthy_locked()
            current = self._records.get((record.device_id, record.action_id))
            if current is None or current.terminal:
                return
            phase = current.phase
            if current.delivery_count == 0 and current.command_ack is None:
                phase = DeviceActionPhase.REJECTED
            self._commit_candidate_locked(
                replace(
                    current,
                    phase=phase,
                    updated_at_ms=now_ms,
                    detail=detail[:2_000],
                )
            )

    def _load_initial_journal(self) -> None:
        entries = self._journal.load()
        self._records, self._terminal_order = self._decode_loaded_entries(entries)

    def _decode_loaded_entries(
        self,
        entries: list[ActionJournalEntryV1],
    ) -> tuple[
        dict[tuple[UUID, UUID], DeviceActionRecord],
        OrderedDict[tuple[UUID, UUID], None],
    ]:
        records: dict[tuple[UUID, UUID], DeviceActionRecord] = {}
        active_devices: set[UUID] = set()
        command_owners: set[tuple[UUID, UUID]] = set()
        terminal_rows: list[tuple[int, str, str, tuple[UUID, UUID]]] = []
        for entry in entries:
            record = self._record_from_entry(entry)
            key = (record.device_id, record.action_id)
            command_key = (record.device_id, record.command_id)
            if key in records:
                raise DeviceActionConflictError("journal contains duplicate action ownership")
            if command_key in command_owners:
                raise DeviceActionConflictError("journal contains duplicate command ownership")
            command_owners.add(command_key)
            if not record.terminal:
                if record.device_id in active_devices:
                    raise DeviceActionConflictError(
                        "journal contains multiple non-terminal actions for one device"
                    )
                active_devices.add(record.device_id)
            else:
                terminal_rows.append(
                    (record.updated_at_ms, str(record.device_id), str(record.action_id), key)
                )
            records[key] = record

        terminal_order: OrderedDict[tuple[UUID, UUID], None] = OrderedDict()
        for _, _, _, key in sorted(terminal_rows):
            terminal_order[key] = None
        return records, terminal_order

    def _record_from_entry(self, entry: ActionJournalEntryV1) -> DeviceActionRecord:
        return DeviceActionRecord(
            device_id=entry.device_id,
            command=entry.command,
            command_envelope=entry.command_envelope,
            phase=DeviceActionPhase(entry.phase),
            created_at_ms=entry.created_at_ms,
            updated_at_ms=entry.updated_at_ms,
            delivery_count=entry.delivery_count,
            last_session_id=entry.last_session_id,
            command_ack=entry.command_ack,
            cancel_envelope=entry.cancel_envelope,
            cancel_ack=entry.cancel_ack,
            result=entry.result,
            result_envelope_id=entry.result_envelope_id,
            result_correlation_id=entry.result_correlation_id,
            result_payload_sha256=entry.result_payload_sha256,
            result_ack_status=entry.result_ack_status,
            result_ack_sent_at_ms=entry.result_ack_sent_at_ms,
            detail=entry.detail,
            recovered_from_journal=True,
        )

    def _entry_from_record(self, record: DeviceActionRecord) -> ActionJournalEntryV1:
        return new_journal_entry(
            device_id=record.device_id,
            command=record.command,
            command_envelope=record.command_envelope,
            phase=record.phase.value,
            created_at_ms=record.created_at_ms,
            updated_at_ms=record.updated_at_ms,
            delivery_count=record.delivery_count,
            last_session_id=record.last_session_id,
            command_ack=record.command_ack,
            cancel_envelope=record.cancel_envelope,
            cancel_ack=record.cancel_ack,
            result=record.result,
            result_envelope_id=record.result_envelope_id,
            result_correlation_id=record.result_correlation_id,
            result_ack_status=record.result_ack_status,
            result_ack_sent_at_ms=record.result_ack_sent_at_ms,
            detail=record.detail,
        )

    def _commit_candidate_locked(self, candidate: DeviceActionRecord) -> DeviceActionRecord:
        self._require_healthy_locked()
        key = (candidate.device_id, candidate.action_id)
        try:
            entry = self._entry_from_record(candidate)
            self._journal.upsert(entry)
        except ActionJournalError as exc:
            self._mark_journal_failed_locked(exc)
        except ValueError as exc:
            self._mark_journal_failed_locked(
                ActionJournalCorruptionError(
                    f"broker produced an invalid durable action record: {exc}"
                )
            )
        self._records[key] = candidate
        if candidate.terminal:
            self._terminal_order[key] = None
            self._terminal_order.move_to_end(key)
            self._prune_terminal_memory_locked()
        else:
            self._terminal_order.pop(key, None)
        return candidate

    def _expire_locked(self, now_ms: int) -> None:
        for record in list(self._records.values()):
            if record.terminal or record.command.deadline_at_ms > now_ms:
                continue
            self._commit_candidate_locked(
                replace(
                    record,
                    phase=DeviceActionPhase.EXPIRED,
                    updated_at_ms=now_ms,
                    detail="action command deadline elapsed",
                )
            )

    def _prune_terminal_memory_locked(self) -> None:
        while len(self._terminal_order) > self._max_terminal_actions:
            expired_key, _ = self._terminal_order.popitem(last=False)
            record = self._records.get(expired_key)
            if record is not None and record.terminal:
                self._records.pop(expired_key, None)

    @staticmethod
    def _prune_loaded_terminal_records(
        *,
        records: dict[tuple[UUID, UUID], DeviceActionRecord],
        terminal_order: OrderedDict[tuple[UUID, UUID], None],
        maximum: int,
    ) -> None:
        while len(terminal_order) > maximum:
            expired_key, _ = terminal_order.popitem(last=False)
            record = records.get(expired_key)
            if record is not None and record.terminal:
                records.pop(expired_key, None)

    def _mark_journal_failed_locked(self, exc: ActionJournalError) -> None:
        self._journal_failure = exc
        raise DeviceActionJournalUnavailableError(
            f"action journal failed closed: {exc}"
        ) from exc

    def _require_healthy_locked(self) -> None:
        if self._journal_failure is not None:
            raise DeviceActionJournalUnavailableError(
                f"action journal is unavailable: {self._journal_failure}"
            )

    def _requirement_for_command(
        self,
        command: AndroidActionCommand,
    ) -> AndroidActionCapabilityRequirement:
        try:
            return requirement_for_operation(command.operation)
        except UnsupportedAndroidOperationError as exc:
            raise DeviceActionUnsupportedOperationError(exc.operation_kind) from exc

    def _require_compatible_session(
        self,
        session: DeviceSession | None,
        requirement: AndroidActionCapabilityRequirement,
    ) -> None:
        if session is None:
            raise DeviceActionDeviceUnavailableError(requirement.operation_kind)
        available = tuple(sorted(set(session.registration.capabilities)))
        missing = missing_capabilities(requirement, set(available))
        if missing:
            raise DeviceActionUnsupportedCapabilityError(
                operation_kind=requirement.operation_kind,
                required_capabilities=tuple(sorted(requirement.required_capabilities)),
                missing=missing,
                available=available,
            )

    def _active_record_for_device_locked(
        self,
        device_id: UUID,
    ) -> DeviceActionRecord | None:
        return next(
            (
                record
                for (record_device_id, _), record in self._records.items()
                if record_device_id == device_id and not record.terminal
            ),
            None,
        )

    def _record_for_command_id_locked(
        self,
        *,
        device_id: UUID,
        command_id: UUID,
    ) -> DeviceActionRecord | None:
        return next(
            (
                record
                for (record_device_id, _), record in self._records.items()
                if record_device_id == device_id and record.command_id == command_id
            ),
            None,
        )

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

    def _command_ack_statuses_are_equivalent(
        self,
        previous: ActionCommandAckStatus,
        current: ActionCommandAckStatus,
    ) -> bool:
        if previous == current:
            return True
        return previous in _ACCEPTED_COMMAND_ACKS and current in _ACCEPTED_COMMAND_ACKS

    def _cancel_ack_statuses_are_equivalent(self, previous: str, current: str) -> bool:
        if previous == current:
            return True
        return previous in _ACCEPTED_CANCEL_ACKS and current in _ACCEPTED_CANCEL_ACKS

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
