from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import WebSocket

from simorgh_core.devices.protocol import (
    DeviceObservationPayload,
    DeviceRegistrationPayload,
    ObservationAckStatus,
    ProtocolEnvelope,
)

MAX_RECENT_OBSERVATION_MESSAGES = 256


class ReplacedDeviceSessionError(ValueError):
    """Raised when an obsolete WebSocket tries to mutate current device state."""


class ObservationStreamConflictError(ValueError):
    """Raised when one device session changes its observation stream identity."""


class ObservationSequenceConflictError(ValueError):
    """Raised when one stream reuses a sequence for different observation content."""


@dataclass(frozen=True, slots=True)
class ObservationIdentity:
    stream_id: UUID
    sequence: int
    snapshot_id: UUID
    state_fingerprint: str

    @classmethod
    def from_payload(cls, payload: DeviceObservationPayload) -> ObservationIdentity:
        return cls(
            stream_id=payload.stream_id,
            sequence=payload.sequence,
            snapshot_id=payload.snapshot.snapshot_id,
            state_fingerprint=payload.state_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class StoredDeviceObservation:
    message_id: UUID
    session_id: UUID
    received_at_ms: int
    payload: DeviceObservationPayload

    @property
    def identity(self) -> ObservationIdentity:
        return ObservationIdentity.from_payload(self.payload)


@dataclass(slots=True)
class _DeviceObservationState:
    current_stream_id: UUID | None = None
    highest_sequence: int = -1
    latest_session_id: UUID | None = None
    latest: StoredDeviceObservation | None = None
    recent_messages: OrderedDict[UUID, ObservationIdentity] = field(default_factory=OrderedDict)

    def remember(self, message_id: UUID, identity: ObservationIdentity) -> None:
        self.recent_messages[message_id] = identity
        self.recent_messages.move_to_end(message_id)
        while len(self.recent_messages) > MAX_RECENT_OBSERVATION_MESSAGES:
            self.recent_messages.popitem(last=False)


@dataclass(slots=True)
class DeviceSession:
    device_id: UUID
    session_id: UUID
    websocket: WebSocket
    registration: DeviceRegistrationPayload
    connected_at_ms: int
    observation_stream_id: UUID | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @classmethod
    def create(
        cls,
        *,
        device_id: UUID,
        websocket: WebSocket,
        registration: DeviceRegistrationPayload,
    ) -> DeviceSession:
        return cls(
            device_id=device_id,
            session_id=uuid4(),
            websocket=websocket,
            registration=registration,
            connected_at_ms=int(time.time() * 1000),
        )

    async def send_envelope(self, envelope: ProtocolEnvelope) -> None:
        """Serialize writes because heartbeats, acks, and commands share one socket."""

        async with self.send_lock:
            await self.websocket.send_text(envelope.model_dump_json())


class DeviceRegistry:
    """Live sessions plus bounded in-memory device observation state."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[UUID, DeviceSession] = {}
        self._observation_states: dict[UUID, _DeviceObservationState] = {}

    async def register(self, session: DeviceSession) -> DeviceSession | None:
        async with self._lock:
            previous = self._sessions.get(session.device_id)
            self._sessions[session.device_id] = session
            return previous

    async def unregister(self, *, device_id: UUID, session_id: UUID) -> None:
        async with self._lock:
            current = self._sessions.get(device_id)
            if current and current.session_id == session_id:
                self._sessions.pop(device_id, None)

    async def get(self, device_id: UUID) -> DeviceSession | None:
        async with self._lock:
            return self._sessions.get(device_id)

    async def is_current(self, session: DeviceSession) -> bool:
        async with self._lock:
            current = self._sessions.get(session.device_id)
            return current is not None and current.session_id == session.session_id

    async def record_observation(
        self,
        *,
        session: DeviceSession,
        message_id: UUID,
        observation: DeviceObservationPayload,
        received_at_ms: int,
    ) -> ObservationAckStatus:
        identity = ObservationIdentity.from_payload(observation)

        async with self._lock:
            current = self._sessions.get(session.device_id)
            if current is None or current.session_id != session.session_id:
                raise ReplacedDeviceSessionError("device session has been replaced")

            if session.observation_stream_id is None:
                session.observation_stream_id = observation.stream_id
            elif session.observation_stream_id != observation.stream_id:
                raise ObservationStreamConflictError(
                    "one device session cannot change observation stream_id"
                )

            state = self._observation_states.setdefault(
                session.device_id,
                _DeviceObservationState(),
            )
            previous_identity = state.recent_messages.get(message_id)
            if previous_identity is not None:
                if previous_identity != identity:
                    raise ObservationSequenceConflictError(
                        "message_id was reused for different observation content"
                    )
                state.recent_messages.move_to_end(message_id)
                return "duplicate"

            stream_changed = state.current_stream_id != observation.stream_id
            if stream_changed and state.latest_session_id == session.session_id:
                raise ObservationStreamConflictError(
                    "observation stream changed inside the current device session"
                )

            if not stream_changed:
                if observation.sequence < state.highest_sequence:
                    state.remember(message_id, identity)
                    return "stale"
                if observation.sequence == state.highest_sequence:
                    latest = state.latest
                    if latest is not None and latest.identity == identity:
                        state.remember(message_id, identity)
                        return "duplicate"
                    raise ObservationSequenceConflictError(
                        "observation sequence was reused for different content"
                    )

            latest = state.latest
            status: ObservationAckStatus = (
                "unchanged"
                if latest is not None
                and latest.payload.state_fingerprint == observation.state_fingerprint
                else "accepted"
            )
            state.current_stream_id = observation.stream_id
            state.highest_sequence = observation.sequence
            state.latest_session_id = session.session_id
            state.latest = StoredDeviceObservation(
                message_id=message_id,
                session_id=session.session_id,
                received_at_ms=received_at_ms,
                payload=observation,
            )
            state.remember(message_id, identity)
            return status

    async def latest_observation(self, device_id: UUID) -> StoredDeviceObservation | None:
        async with self._lock:
            state = self._observation_states.get(device_id)
            return state.latest if state is not None else None

    async def count(self) -> int:
        async with self._lock:
            return len(self._sessions)


registry = DeviceRegistry()
