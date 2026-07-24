from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

from fastapi import WebSocket

from simorgh_core.devices.observation_refresh_broker import (
    ObservationRefreshBroker,
    ObservationRefreshDeviceUnavailableError,
    ObservationRefreshPhase,
    ObservationRefreshRecord,
)
from simorgh_core.devices.observation_refresh_protocol import (
    OBSERVATION_REFRESH_CAPABILITY,
)
from simorgh_core.devices.protocol import DeviceRegistrationPayload
from simorgh_core.devices.registry import DeviceSession, registry


@dataclass
class RecordingWebSocket:
    sent: list[str] = field(default_factory=list)

    async def send_text(self, value: str) -> None:
        self.sent.append(value)


class ReplacementAlreadyOwnsDeliveryBroker(ObservationRefreshBroker):
    def __init__(self, replacement_session_id: UUID) -> None:
        super().__init__(now_ms=lambda: 10_000)
        self._replacement_session_id = replacement_session_id
        self._simulate_once = True

    async def _deliver(
        self,
        *,
        record: ObservationRefreshRecord,
        session: DeviceSession,
    ) -> None:
        if self._simulate_once:
            self._simulate_once = False
            record.phase = ObservationRefreshPhase.DELIVERED
            record.delivery_count = 1
            record.last_session_id = self._replacement_session_id
            record.detail = "replacement session delivered exact request"
            raise ObservationRefreshDeviceUnavailableError(
                "original session was replaced before refresh delivery"
            )
        await super()._deliver(record=record, session=session)


def _registration() -> DeviceRegistrationPayload:
    return DeviceRegistrationPayload(
        app_version="0.1.0",
        sdk_int=31,
        android_release="12",
        manufacturer="Samsung",
        model="SM-A536B",
        build_fingerprint="samsung/a53/replacement-race-test",
        support_tier="FULL",
        capabilities=[
            "android.accessibility.observe.platform",
            OBSERVATION_REFRESH_CAPABILITY,
        ],
    )


def _session(device_id: UUID) -> tuple[DeviceSession, RecordingWebSocket]:
    websocket = RecordingWebSocket()
    return (
        DeviceSession.create(
            device_id=device_id,
            websocket=cast(WebSocket, websocket),
            registration=_registration(),
        ),
        websocket,
    )


async def _create(
    broker: ObservationRefreshBroker,
    device_id: UUID,
) -> ObservationRefreshRecord:
    return await broker.create(
        device_id=device_id,
        timeout_ms=5_000,
        expected_state_fingerprint=None,
        expected_active_package=None,
        reason="replacement race fixture",
    )


def test_create_preserves_delivery_already_owned_by_replacement_session() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        original_session, _ = _session(device_id)
        replacement_session_id = uuid4()
        await registry.register(original_session)
        broker = ReplacementAlreadyOwnsDeliveryBroker(replacement_session_id)
        try:
            record = await _create(broker, device_id)

            assert record.phase == ObservationRefreshPhase.DELIVERED
            assert record.last_session_id == replacement_session_id
            assert record.delivery_count == 1
            assert record.detail == "replacement session delivered exact request"
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=original_session.session_id,
            )

    asyncio.run(scenario())


def test_obsolete_redelivery_call_is_noop_and_newest_session_can_take_ownership() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        first_session, first_socket = _session(device_id)
        await registry.register(first_session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        record = await _create(broker, device_id)
        assert len(first_socket.sent) == 1
        first_wire = first_socket.sent[0]

        second_session, second_socket = _session(device_id)
        await registry.register(second_session)
        try:
            await broker.redeliver(first_session)
            unchanged = await broker.get(
                device_id=device_id,
                request_id=record.request_id,
            )
            assert unchanged.last_session_id == first_session.session_id
            assert unchanged.delivery_count == 1

            await broker.redeliver(second_session)
            transferred = await broker.get(
                device_id=device_id,
                request_id=record.request_id,
            )
            assert transferred.last_session_id == second_session.session_id
            assert transferred.delivery_count == 2
            assert second_socket.sent == [first_wire]
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=second_session.session_id,
            )

    asyncio.run(scenario())
