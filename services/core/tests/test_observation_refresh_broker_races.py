from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocket

from simorgh_core.devices.observation_refresh_broker import (
    ObservationRefreshBroker,
    ObservationRefreshDeviceUnavailableError,
    ObservationRefreshPhase,
    ObservationRefreshRecord,
)
from simorgh_core.devices.observation_refresh_protocol import (
    OBSERVATION_REFRESH_CAPABILITY,
    DeviceObservationRefreshAckEnvelope,
    DeviceObservationRefreshAckPayload,
    ObservationRefreshAckStatus,
)
from simorgh_core.devices.protocol import DeviceRegistrationPayload
from simorgh_core.devices.registry import DeviceSession, registry


@dataclass
class RecordingWebSocket:
    sent: list[str] = field(default_factory=list)

    async def send_text(self, value: str) -> None:
        self.sent.append(value)


class FailFirstDeliveryBroker(ObservationRefreshBroker):
    def __init__(self) -> None:
        super().__init__(now_ms=lambda: 10_000)
        self._fail_next_delivery = True

    async def _deliver(
        self,
        *,
        record: ObservationRefreshRecord,
        session: DeviceSession,
    ) -> None:
        if self._fail_next_delivery:
            self._fail_next_delivery = False
            raise ObservationRefreshDeviceUnavailableError(
                "device session was replaced before refresh delivery"
            )
        await super()._deliver(record=record, session=session)


def _registration() -> DeviceRegistrationPayload:
    return DeviceRegistrationPayload(
        app_version="0.1.0",
        sdk_int=31,
        android_release="12",
        manufacturer="Samsung",
        model="SM-A536B",
        build_fingerprint="samsung/a53/refresh-race-test",
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
    *,
    timeout_ms: int = 5_000,
) -> ObservationRefreshRecord:
    return await broker.create(
        device_id=device_id,
        timeout_ms=timeout_ms,
        expected_state_fingerprint=None,
        expected_active_package=None,
        reason="race fixture",
    )


def _ack(
    *,
    device_id: UUID,
    request_id: UUID,
    status: ObservationRefreshAckStatus,
    received_at_ms: int,
) -> tuple[DeviceObservationRefreshAckEnvelope, DeviceObservationRefreshAckPayload]:
    payload = DeviceObservationRefreshAckPayload(
        request_id=request_id,
        status=status,
        received_at_ms=received_at_ms,
        detail=f"fixture {status}",
    )
    return (
        DeviceObservationRefreshAckEnvelope.create(
            device_id=device_id,
            request_envelope_id=request_id,
            payload=payload,
        ),
        payload,
    )


def test_failed_initial_delivery_does_not_leave_device_permanently_busy() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        session, websocket = _session(device_id)
        await registry.register(session)
        broker = FailFirstDeliveryBroker()
        try:
            with pytest.raises(
                ObservationRefreshDeviceUnavailableError,
                match="replaced before refresh delivery",
            ):
                await _create(broker, device_id)

            replacement = await _create(broker, device_id)
            assert replacement.phase == ObservationRefreshPhase.DELIVERED
            assert replacement.delivery_count == 1
            assert len(websocket.sent) == 1
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())


def test_core_expiry_is_authoritative_over_late_android_timeout_ack() -> None:
    async def scenario() -> None:
        now = [10_000]
        device_id = uuid4()
        session, _ = _session(device_id)
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: now[0])
        try:
            record = await _create(broker, device_id, timeout_ms=250)
            accepted_envelope, accepted = _ack(
                device_id=device_id,
                request_id=record.request_id,
                status="accepted",
                received_at_ms=10_010,
            )
            accepted_record = await broker.record_ack(
                session=session,
                envelope=accepted_envelope,
                acknowledgement=accepted,
            )
            assert accepted_record.phase == ObservationRefreshPhase.ACCEPTED

            now[0] = 10_251
            expired_envelope, expired = _ack(
                device_id=device_id,
                request_id=record.request_id,
                status="expired",
                received_at_ms=10_251,
            )
            final_record = await broker.record_ack(
                session=session,
                envelope=expired_envelope,
                acknowledgement=expired,
            )

            assert final_record.phase == ObservationRefreshPhase.EXPIRED
            assert final_record.detail == "observation refresh deadline elapsed"
            assert final_record.acknowledgement == accepted
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())


def test_cancelled_refresh_ignores_late_accepted_ack_without_reopening() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        session, _ = _session(device_id)
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        try:
            record = await _create(broker, device_id)
            cancelled = await broker.cancel(
                device_id=device_id,
                request_id=record.request_id,
                reason="operator cancelled fixture",
            )
            assert cancelled.phase == ObservationRefreshPhase.CANCELLED

            envelope, acknowledgement = _ack(
                device_id=device_id,
                request_id=record.request_id,
                status="accepted",
                received_at_ms=10_010,
            )
            final_record = await broker.record_ack(
                session=session,
                envelope=envelope,
                acknowledgement=acknowledgement,
            )

            assert final_record.phase == ObservationRefreshPhase.CANCELLED
            assert final_record.detail == "operator cancelled fixture"
            assert final_record.acknowledgement is None
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())
