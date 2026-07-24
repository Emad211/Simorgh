from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from fastapi import WebSocketDisconnect

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
_ACCEPTED_ACK_STATUSES = frozenset({"accepted", "duplicate"})
_COMPLETION_ELIGIBLE_PHASES = frozenset({"delivered", "accepted"})


class ObservationRefreshBrokerError(ValueError):
    """Base class for deterministic observation-refresh failures."""


class ObservationRefreshBusyError(ObservationRefreshBrokerError):
    """Raised when a device already owns a non-terminal refresh."""


class ObservationRefreshNotFoundError(ObservationRefreshBrokerError):
    """Raised when a refresh identifier does not exist."""


class ObservationRefreshConflictError(ObservationRefreshBrokerError):
    """Raised when stable refresh identity is reused inconsistently."""


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


_TERMINAL_PHASES = frozenset(
    {
        ObservationRefreshPhase.COMPLETED,
        ObservationRefreshPhase.REJECTED,
        ObservationRefreshPhase.EXPIRED,
        ObservationRefreshPhase.CANCELLED,
    }
)


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
        return self.phase in _TERMINAL_PHASES


@dataclass(frozen=True, slots=True)
class ObservationRefreshCompletionCandidate:
    device_id: UUID
    request_id: UUID
    session_id: UUID
    evidence: StoredObservationEvidence


class ObservationRefreshBroker:
    """Single-flight delivery and evidence binding for explicit refresh requests."""

    def __init__(self, *, now_ms: Callable[[], int] | None = None) -> None:
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
        session = await registry.get(device_id)
        self._require_compatible_session(session)

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
        key = (device_id, request_id)

        async with self._lock:
            self._expire_locked(now_ms)
            active = self._active_for_device_locked(device_id)
            if active is not None:
                raise ObservationRefreshBusyError(
                    f"device already has active observation refresh {active.request_id}"
                )
            self._records[key] = record

        assert session is not None
        try:
            await self._deliver(record=record, session=session)
        except ObservationRefreshDeviceUnavailableError as exc:
            async with self._lock:
                current = self._records.get(key)
                if current is None:
                    raise
                # A replacement session may have redelivered this exact request before the
                # original create path notices that its session is obsolete. Preserve that
                # newer ownership (or a result it already completed) instead of rejecting it.
                replacement_owns_delivery = (
                    current.last_session_id is not None
                    and current.last_session_id != session.session_id
                )
                if current.terminal or replacement_owns_delivery:
                    return current
                self._finish_locked(
                    key=key,
                    record=current,
                    phase=ObservationRefreshPhase.REJECTED,
                    detail=str(exc),
                    now_ms=self._now_ms(),
                )
            raise
        return record

    async def redeliver(self, session: DeviceSession) -> None:
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._active_for_device_locked(session.device_id)
        if record is None:
            return

        if OBSERVATION_REFRESH_CAPABILITY not in session.registration.capabilities:
            async with self._lock:
                current = self._records.get((record.device_id, record.request_id))
                if current is not None and not current.terminal:
                    self._finish_locked(
                        key=(current.device_id, current.request_id),
                        record=current,
                        phase=ObservationRefreshPhase.REJECTED,
                        detail=(
                            "replacement device session lacks "
                            "android.observation.refresh.v1"
                        ),
                        now_ms=now_ms,
                    )
            return

        try:
            await self._deliver(record=record, session=session)
        except ObservationRefreshDeviceUnavailableError:
            # Another registration superseded this redelivery call. The newest session owns
            # the next redelivery opportunity; an obsolete session must not fail the gateway.
            return

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
            self._require_delivery_owner(record=record, session=session)
            if envelope.correlation_id != record.request_envelope.message_id:
                raise ObservationRefreshConflictError(
                    "refresh acknowledgement correlation_id does not match request"
                )
            if acknowledgement.request_id != record.request_id:
                raise ObservationRefreshConflictError(
                    "refresh acknowledgement request_id does not match request"
                )

            # Core's terminal phase is authoritative. Android's relative capture timer can
            # legitimately emit a later terminal ACK after Core's absolute record deadline.
            # The identity and delivery owner were verified above; ignore the late status
            # without mutating final state or turning a benign race into protocol failure.
            if record.terminal:
                return record

            previous = record.acknowledgement
            if previous is not None:
                if previous.status not in _ACCEPTED_ACK_STATUSES:
                    raise ObservationRefreshConflictError(
                        "non-terminal refresh has an invalid prior acknowledgement"
                    )
                if acknowledgement.status in _ACCEPTED_ACK_STATUSES:
                    record.phase = ObservationRefreshPhase.ACCEPTED
                    record.updated_at_ms = now_ms
                    return record

                record.acknowledgement = acknowledgement
                terminal_phase = (
                    ObservationRefreshPhase.EXPIRED
                    if acknowledgement.status == "expired"
                    else ObservationRefreshPhase.REJECTED
                )
                self._finish_locked(
                    key=key,
                    record=record,
                    phase=terminal_phase,
                    detail=acknowledgement.detail,
                    now_ms=now_ms,
                )
                return record

            record.acknowledgement = acknowledgement
            record.updated_at_ms = now_ms
            record.detail = acknowledgement.detail
            if acknowledgement.status in _ACCEPTED_ACK_STATUSES:
                record.phase = ObservationRefreshPhase.ACCEPTED
                return record

            terminal_phase = (
                ObservationRefreshPhase.EXPIRED
                if acknowledgement.status == "expired"
                else ObservationRefreshPhase.REJECTED
            )
            self._finish_locked(
                key=key,
                record=record,
                phase=terminal_phase,
                detail=acknowledgement.detail,
                now_ms=now_ms,
            )
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
            self._require_delivery_owner(record=record, session=session)
            if record.phase.value not in _COMPLETION_ELIGIBLE_PHASES:
                raise ObservationRefreshConflictError(
                    "correlated observation arrived before refresh delivery ownership"
                )
            if observation_status == "stale":
                self._finish_locked(
                    key=key,
                    record=record,
                    phase=ObservationRefreshPhase.REJECTED,
                    detail="correlated refresh observation was stale",
                    now_ms=now_ms,
                )
                return None
            expected_fingerprint = record.request.expected_state_fingerprint
            if (
                expected_fingerprint is not None
                and observation.state_fingerprint != expected_fingerprint
            ):
                self._finish_locked(
                    key=key,
                    record=record,
                    phase=ObservationRefreshPhase.REJECTED,
                    detail="fresh observation state fingerprint changed",
                    now_ms=now_ms,
                )
                return None
            expected_package = record.request.expected_active_package
            if (
                expected_package is not None
                and observation.snapshot.active_package != expected_package
            ):
                self._finish_locked(
                    key=key,
                    record=record,
                    phase=ObservationRefreshPhase.REJECTED,
                    detail="fresh observation active package changed",
                    now_ms=now_ms,
                )
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
                current = self._records.get(key)
                if current is not None and not current.terminal:
                    self._finish_locked(
                        key=key,
                        record=current,
                        phase=ObservationRefreshPhase.REJECTED,
                        detail="Core could not resolve correlated observation evidence",
                        now_ms=self._now_ms(),
                    )
            return None

        return ObservationRefreshCompletionCandidate(
            device_id=session.device_id,
            request_id=refresh_request_id,
            session_id=session.session_id,
            evidence=evidence,
        )

    async def complete_observation(
        self,
        *,
        device_id: UUID,
        candidate: ObservationRefreshCompletionCandidate,
    ) -> ObservationRefreshRecord | None:
        if candidate.device_id != device_id:
            raise ObservationRefreshConflictError(
                "refresh completion candidate device_id does not match caller"
            )
        key = (device_id, candidate.request_id)
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get(key)
            if record is None or record.terminal:
                return record
            if record.last_session_id != candidate.session_id:
                return record
            record.evidence = candidate.evidence
            self._finish_locked(
                key=key,
                record=record,
                phase=ObservationRefreshPhase.COMPLETED,
                detail="fresh observation acknowledged and bound to refresh request",
                now_ms=now_ms,
            )
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
        key = (device_id, request_id)
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            record = self._records.get(key)
            if record is None:
                raise ObservationRefreshNotFoundError("observation refresh not found")
            if record.terminal:
                return record
            self._finish_locked(
                key=key,
                record=record,
                phase=ObservationRefreshPhase.CANCELLED,
                detail=reason[:1_000],
                now_ms=now_ms,
            )
            return record

    async def _deliver(
        self,
        *,
        record: ObservationRefreshRecord,
        session: DeviceSession,
    ) -> None:
        self._require_compatible_session(session)
        if not await registry.is_current(session):
            raise ObservationRefreshDeviceUnavailableError(
                "device session was replaced before refresh delivery"
            )

        key = (record.device_id, record.request_id)
        now_ms = self._now_ms()
        async with self._lock:
            self._expire_locked(now_ms)
            current = self._records.get(key)
            if current is None or current.terminal:
                return
            previous_phase = current.phase
            current.phase = ObservationRefreshPhase.DELIVERED
            current.updated_at_ms = now_ms
            current.delivery_count += 1
            current.last_session_id = session.session_id
            current.detail = "refresh request delivery started"

        try:
            await session.send_envelope(record.request_envelope)
        except (OSError, RuntimeError, WebSocketDisconnect):
            async with self._lock:
                current = self._records.get(key)
                if (
                    current is not None
                    and not current.terminal
                    and current.last_session_id == session.session_id
                ):
                    current.phase = (
                        previous_phase
                        if previous_phase == ObservationRefreshPhase.ACCEPTED
                        else ObservationRefreshPhase.QUEUED
                    )
                    current.updated_at_ms = self._now_ms()
                    current.detail = "refresh delivery paused until reconnect"
            return

        async with self._lock:
            current = self._records.get(key)
            if (
                current is not None
                and not current.terminal
                and current.last_session_id == session.session_id
            ):
                current.updated_at_ms = self._now_ms()
                current.detail = "refresh request delivered to Android"

    def _expire_locked(self, now_ms: int) -> None:
        for key, record in list(self._records.items()):
            if record.terminal or record.deadline_at_ms > now_ms:
                continue
            self._finish_locked(
                key=key,
                record=record,
                phase=ObservationRefreshPhase.EXPIRED,
                detail="observation refresh deadline elapsed",
                now_ms=now_ms,
            )

    def _finish_locked(
        self,
        *,
        key: tuple[UUID, UUID],
        record: ObservationRefreshRecord,
        phase: ObservationRefreshPhase,
        detail: str,
        now_ms: int,
    ) -> None:
        record.phase = phase
        record.updated_at_ms = now_ms
        record.detail = detail[:1_000]
        self._terminal_order[key] = None
        self._terminal_order.move_to_end(key)
        while len(self._terminal_order) > MAX_TERMINAL_REFRESHES:
            expired_key, _ = self._terminal_order.popitem(last=False)
            expired_record = self._records.get(expired_key)
            if expired_record is not None and expired_record.terminal:
                self._records.pop(expired_key, None)

    def _active_for_device_locked(
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

    @staticmethod
    def _require_compatible_session(session: DeviceSession | None) -> None:
        if session is None:
            raise ObservationRefreshDeviceUnavailableError("device is not connected")
        if OBSERVATION_REFRESH_CAPABILITY not in session.registration.capabilities:
            raise ObservationRefreshDeviceUnavailableError(
                "device does not advertise android.observation.refresh.v1"
            )

    @staticmethod
    def _require_delivery_owner(
        *,
        record: ObservationRefreshRecord,
        session: DeviceSession,
    ) -> None:
        if record.last_session_id != session.session_id:
            raise ObservationRefreshConflictError(
                "refresh message came from a session that does not own current delivery"
            )


observation_refresh_broker = ObservationRefreshBroker()
