from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import WebSocket

from simorgh_core.devices.protocol import DeviceRegistrationPayload


@dataclass(slots=True)
class DeviceSession:
    device_id: UUID
    session_id: UUID
    websocket: WebSocket
    registration: DeviceRegistrationPayload
    connected_at_ms: int

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


class DeviceRegistry:
    """In-memory live-connection index; durable device metadata comes later."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[UUID, DeviceSession] = {}

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

    async def count(self) -> int:
        async with self._lock:
            return len(self._sessions)


registry = DeviceRegistry()
