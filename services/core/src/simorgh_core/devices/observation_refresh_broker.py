from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from simorgh_core.devices.observation_refresh_protocol import (
    OBSERVATION_REFRESH_CAPABILITY,
    DeviceObservationRefreshAckEnvelope,
    DeviceObservationRefreshAckPayload,
    DeviceObservationRefreshEnvelope,
    DeviceObservationRefreshPayload,
)
from simorgh_core.devices.protocol import DeviceObservationPayload, ObservationAckStatus
from simorgh_core.devices.registry import (
    DeviceSession,
    StoredObservationEvidence,
    registry,
)

MAX_TERMINAL_REFRESHES = 256
_ACCEPTED_ACKS = frozenset({"accepted", "duplicate"})


class ObservationRefreshBrokerError(ValueError):
    """Base class for deterministic refresh broker failures."""


class ObservationRefreshBusyError(ObservationRefreshBrokerError):
    """Raised when one device already owns a non-terminal refresh."""


class ObservationRefreshNotFoundError(ObservationRefreshBrokerError):
    """Raised when a refresh identifier does not exist."""


class ObservationRefreshConflictError(ObservationRefreshBrokerError):
    """Raised when stable refresh identity is replayed with conflicting data."""


class ObservationRefreshDeviceUnavailableError(ObservationRefreshBrokerError):
    """Raised when no compatible current device session can accept a refresh."""


class ObservationRefreshPhase(StrEnum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_PHASES = {
    ObservationRefreshPhase.COMPLETED,
    ObservationRefreshPhase.REJECTED,
    ObservationRefreshPhase.EXPIRED,
    ObservationRefreshPhase.CANCELLED,
}


@dataclass(slots=True)
class ObservationRefreshRecord:
    device_id: UUID
    request: DeviceObservationRefreshPayload
    request_envelope: DeviceObservationRefreshEnvelope
    phase: ObservationRefreshPhase
    created_at_ms: int
    updated_at_ms: int
    deadline_at_ms: int
    delivery_count: int = 0
    last_session_id: UUID | None = None
    acknowledgement: DeviceObservationRefreshAckPayload | None = None
    evidence: StoredObservationEvidence | None = None
    detail: str = ""

    @property
    def request_id(self) -> UUID:
        return self.request.request_id

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES


@dataclass(frozen=True, slots=True)
class ObservationRefreshCompletionCandidate:
    request_id: UUID
    evidence: StoredObservationEvidence


class ObservationRefreshBroker:
    """Single-flight observation refresh delivery and exact evidence binding."""

    def __init__(self, *, now_ms: callable | None = None) -> None:
        self._lock = asyncio.Lock()
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._records: dict[tuple[UUID, UUID], ObservationRefreshRecord] = {}
        self._terminal_order: OrderedDict[tuple[UUID, UUID], None] = OrderedDict()

    async def create(
        self,
        *,
        device_id: UUID,
        timeout_ms: int,
        expected_state_fingerprint: str | None,
        expected_active_package: str | None,
        reason: str,
    ) -> ObservationRefreshRecord:
        now_ms = self._now_ms()
        request_id = uuid4()
        request = DeviceObservationRefreshPayload(
            request_id=request_id,
            timeout_ms=timeout_ms,
            expected_state_fingerprint=expected_state_fingerprint,
            expected_active_package=expected_active_package,
            reason=reason,
        )
        envelope = DeviceObservationRefreshEnvelope.create(
            device_id=device_id,
            payload=request,
            message_id=request_id,
        )
        record = ObservationRefreshRecord(
            device_id=device_id,
            request=request,
            request_envelope=envelope,
            phase=ObservationRefreshPhase.QUEUED,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            deadline_at_ms=now_ms + timeout_ms,
        )

        session = await registry.get(device_id)
        self._require_compatible_session(session)

        async with self._lock:
            self._expire_locked(now_ms)
            active = self._active_record_for_device_locked(device_id)
            if active is not None:
                raise ObservationRefreshBusyError(
                    f"device already has active observation refresh {active.request_id}"
                )
            self._records[(device_id, request_id)] = record

        assert session is not None
        await self._deliver(record, session)
        return record

    async def redeliver(self, session: DeviceSession) -> None:
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._active_record_for_device_locked(session.device_id)
        if record is None:
            return
        if OBSERVATION_REFRESH_CAPABILITY not in session.registration.capabilities:
            async with self._lock:
                if not record.terminal:
                    record.phase = ObservationRefreshPhase.REJECTED
                    record.updated_at_ms = now_ms
                    record.detail = "replacement device session lacks observation refresh capability"
                    self._remember_terminal_locked((record.device_id, record.request_id))
            return
        await self._deliver(record, session)

    async def record_ack(
        self,
        *,
        session: DeviceSession,
        envelope: DeviceObservationRefreshAckEnvelope,
        acknowledgement: DeviceObservationRefreshAckPayload,
    ) -> ObservationRefreshRecord:
        key = (session.device_id, acknowledgement.request_id)
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get(key)
            if record is None:
                raise ObservationRefreshNotFoundError(
                    "refresh acknowledgement references unknown request"
                )
            self._require_current_delivery(record, session)
            if envelope.correlation_id != record.request_envelope.message_id:
                raise ObservationRefreshConflictError(
                    "refresh acknowledgement correlation_id does not match request message_id"
                )
            if acknowledgement.request_id != record.request_id:
                raise ObservationRefreshConflictError(
                    "refresh acknowledgement request_id does not match request"
                )

            previous = record.acknowledgement
            if previous is not None:
                if self._ack_statuses_equivalent(previous.status, acknowledgement.status):
                    return record
                raise ObservationRefreshConflictError(
                    "refresh acknowledgement changed after it was recorded"
                )

            record.acknowledgement = acknowledgement
            record.updated_at_ms = now_ms
            record.detail = acknowledgement.detail
            if acknowledgement.status in _ACCEPTED_ACKS:
                record.phase = ObservationRefreshPhase.ACCEPTED
            elif acknowledgement.status == "expired":
                record.phase = ObservationRefreshPhase.EXPIRED
            else:
                record.phase = ObservationRefreshPhase.REJECTED
            if record.terminal:
                self._remember_terminal_locked(key)
            return record

    async def prepare_observation_completion(
        self,
        *,
        session: DeviceSession,
        refresh_request_id: UUID,
        observation: DeviceObservationPayload,
        observation_status: ObservationAckStatus,
    ) -> ObservationRefreshCompletionCandidate | None:
        key = (session.device_id, refresh_request_id)
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get(key)
            if record is None or record.terminal:
                return None
            self._require_current_delivery(record, session)
            if observation_status == "stale":
                record.phase = ObservationRefreshPhase.REJECTED
                record.updated_at_ms = now_ms
                record.detail = "correlated refresh observation was stale"
                self._remember_terminal_locked(key)
                return None
            expected_fingerprint = record.request.expected_state_fingerprint
            if (
                expected_fingerprint is not None
                and observation.state_fingerprint != expected_fingerprint
            ):
                record.phase = ObservationRefreshPhase.REJECTED
                record.updated_at_ms = now_ms
                record.detail = "fresh observation state fingerprint changed"
                self._remember_terminal_locked(key)
                return None
            expected_package = record.request.expected_active_package
            if (
                expected_package is not None
                and observation.snapshot.active_package != expected_package
            ):
                record.phase = ObservationRefreshPhase.REJECTED
                record.updated_at_ms = now_ms
                record.detail = "fresh observation active package changed"
                self._remember_terminal_locked(key)
                return None

        evidence = await registry.observation_evidence(
            device_id=session.device_id,
            stream_id=observation.stream_id,
            sequence=observation.sequence,
            snapshot_id=observation.snapshot.snapshot_id,
            state_fingerprint=observation.state_fingerprint,
        )
        if evidence is None:
            async with self._lock:
                record = self._records.get(key)
                if record is not None and not record.terminal:
                    record.phase = ObservationRefreshPhase.REJECTED
                    record.updated_at_ms = self._now_ms()
                    record.detail = "Core could not resolve correlated observation evidence"
                    self._remember_terminal_locked(key)
            return None
        return ObservationRefreshCompletionCandidate(
            request_id=refresh_request_id,
            evidence=evidence,
        )

    async def complete_observation(
        self,
        *,
        device_id: UUID,
        candidate: ObservationRefreshCompletionCandidate,
    ) -> ObservationRefreshRecord | None:
        key = (device_id, candidate.request_id)
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get(key)
            if record is None or record.terminal:
                return record
            record.evidence = candidate.evidence
            record.phase = ObservationRefreshPhase.COMPLETED
            record.updated_at_ms = now_ms
            record.detail = "fresh observation acknowledged and bound to refresh request"
            self._remember_terminal_locked(key)
            return record

    async def get(
        self,
        *,
        device_id: UUID,
        request_id: UUID,
    ) -> ObservationRefreshRecord:
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get((device_id, request_id))
            if record is None:
                raise ObservationRefreshNotFoundError("observation refresh not found")
            return record

    async def cancel(
        self,
        *,
        device_id: UUID,
        request_id: UUID,
        reason: str,
    ) -> ObservationRefreshRecord:
        now_ms = self._now_ms()
        key = (device_id, request_id)
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get(key)
            if record is None:
                raise ObservationRefreshNotFoundError("observation refresh not found")
            if record.terminal:
                return record
            record.phase = ObservationRefreshPhase.CANCELLED
            record.updated_at_ms = now_ms
            record.detail = reason[:1_000]
            self._remember_terminal_locked(key)
            return record

    async def _deliver(
        self,
        record: ObservationRefreshRecord,
        session: DeviceSession,
    ) -> None:
        self._require_compatible_session(session)
        if not await registry.is_current(session):
            raise ObservationRefreshDeviceUnavailableError(
                "device session was replaced before refresh delivery"
            )
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            current = self._records.get((record.device_id, record.request_id))
            if current is None or current.terminal:
                return
            if current.deadline_at_ms <= now_ms:
                return

        try:
            await session.send_envelope(record.request_envelope)
        except Exception:
            async with self._lock:
                current = self._records.get((record.device_id, record.request_id))
                if current is not None and not current.terminal:
                    current.phase = ObservationRefreshPhase.QUEUED
                    current.updated_at_ms = self._now_ms()
                    current.detail = "refresh delivery paused until reconnect"
            raise

        async with self._lock:
            current = self._records.get((record.device_id, record.request_id))
            if current is None or current.terminal:
                return
            current.phase = ObservationRefreshPhase.DELIVERED
            current.updated_at_ms = self._now_ms()
            current.delivery_count += 1
            current.last_session_id = session.session_id
            current.detail = "refresh request delivered to Android"

    def _expire_locked(self, now_ms: int) -> None:
        for key, record in list(self._records.items()):
            if record.terminal or record.deadline_at_ms > now_ms:
                continue
            record.phase = ObservationRefreshPhase.EXPIRED
            record.updated_at_ms = now_ms
            record.detail = "observation refresh deadline elapsed"
            self._remember_terminal_locked(key)

    def _active_record_for_device_locked(
        self,
        device_id: UUID,
    ) -> ObservationRefreshRecord | None:
        return next(
            (
                record
                for (record_device_id, _), record in self._records.items()
                if record_device_id == device_id and not record.terminal
            ),
            None,
        )

    def _remember_terminal_locked(self, key: tuple[UUID, UUID]) -> None:
        self._terminal_order[key] = None
        self._terminal_order.move_to_end(key)
        while len(self._terminal_order) > MAX_TERMINAL_REFRESHES:
            expired_key, _ = self._terminal_order.popitem(last=False)
            record = self._records.get(expired_key)
            if record is not None and record.terminal:
                self._records.pop(expired_key, None)

    @staticmethod
    def _require_compatible_session(session: DeviceSession | None) -> None:
        if session is None:
            raise ObservationRefreshDeviceUnavailableError("device is not connected")
        if OBSERVATION_REFRESH_CAPABILITY not in session.registration.capabilities:
            raise ObservationRefreshDeviceUnavailableError(
                "device does not advertise android.observation.refresh.v1"
            )

    @staticmethod
    def _require_current_delivery(
        record: ObservationRefreshRecord,
        session: DeviceSession,
    ) -> None:
        if record.last_session_id != session.session_id:
            raise ObservationRefreshConflictError(
                "refresh message came from a session that does not own current delivery"
            )

    @staticmethod
    def _ack_statuses_equivalent(left: str, right: str) -> bool:
        return left == right or (left in _ACCEPTED_ACKS and right in _ACCEPTED_ACKS)


observation_refresh_broker = ObservationRefreshBroker()
