from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocket

from simorgh_core.devices.observation_refresh_broker import (
    ObservationRefreshBroker,
    ObservationRefreshBusyError,
    ObservationRefreshConflictError,
    ObservationRefreshDeviceUnavailableError,
    ObservationRefreshPhase,
    ObservationRefreshRecord,
)
from simorgh_core.devices.observation_refresh_protocol import (
    OBSERVATION_REFRESH_CAPABILITY,
    DeviceObservationRefreshAckEnvelope,
    DeviceObservationRefreshAckPayload,
    DeviceObservationRefreshEnvelope,
    DeviceObservationRefreshPayload,
    ObservationRefreshAckStatus,
)
from simorgh_core.devices.protocol import (
    AccessibilitySnapshotPayload,
    DeviceObservationPayload,
    DeviceRegistrationPayload,
    calculate_accessibility_state_fingerprint,
)
from simorgh_core.devices.registry import DeviceSession, registry


@dataclass
class RecordingWebSocket:
    sent: list[str] = field(default_factory=list)
    closed: list[tuple[int, str]] = field(default_factory=list)

    async def send_text(self, value: str) -> None:
        self.sent.append(value)

    async def close(self, *, code: int = 1000, reason: str | None = None) -> None:
        self.closed.append((code, reason or ""))


def _registration(*, refresh_capable: bool = True) -> DeviceRegistrationPayload:
    capabilities = ["android.accessibility.observe.platform"]
    if refresh_capable:
        capabilities.append(OBSERVATION_REFRESH_CAPABILITY)
    return DeviceRegistrationPayload(
        app_version="0.1.0",
        sdk_int=31,
        android_release="12",
        manufacturer="Samsung",
        model="SM-A536B",
        build_fingerprint="samsung/a53/refresh-broker-test",
        support_tier="FULL",
        capabilities=capabilities,
    )


def _session(
    *,
    device_id: UUID,
    refresh_capable: bool = True,
) -> tuple[DeviceSession, RecordingWebSocket]:
    websocket = RecordingWebSocket()
    session = DeviceSession.create(
        device_id=device_id,
        websocket=cast(WebSocket, websocket),
        registration=_registration(refresh_capable=refresh_capable),
    )
    return session, websocket


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


def _observation(
    *,
    stream_id: UUID,
    sequence: int,
    active_package: str,
    captured_at_ms: int,
) -> DeviceObservationPayload:
    snapshot = AccessibilitySnapshotPayload(
        snapshot_id=uuid4(),
        captured_at_ms=captured_at_ms,
        active_package=active_package,
        active_window_id=None,
        root_node_id=None,
        windows=[],
        nodes=[],
        truncated=False,
        truncation_reasons=[],
        max_depth_observed=0,
    )
    return DeviceObservationPayload(
        stream_id=stream_id,
        sequence=sequence,
        state_fingerprint=calculate_accessibility_state_fingerprint(snapshot),
        snapshot=snapshot,
    )


async def _create(
    broker: ObservationRefreshBroker,
    device_id: UUID,
    *,
    expected_state_fingerprint: str | None = None,
    expected_active_package: str | None = None,
    timeout_ms: int = 5_000,
) -> ObservationRefreshRecord:
    return await broker.create(
        device_id=device_id,
        timeout_ms=timeout_ms,
        expected_state_fingerprint=expected_state_fingerprint,
        expected_active_package=expected_active_package,
        reason="fixture refresh",
    )


def test_create_delivers_one_stable_typed_request() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        session, websocket = _session(device_id=device_id)
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        try:
            record = await _create(broker, device_id)

            assert record.phase == ObservationRefreshPhase.DELIVERED
            assert record.delivery_count == 1
            assert record.last_session_id == session.session_id
            assert record.request_id == record.request_envelope.message_id
            assert len(websocket.sent) == 1
            decoded = DeviceObservationRefreshEnvelope.model_validate_json(
                websocket.sent[0]
            )
            payload = DeviceObservationRefreshPayload.model_validate(decoded.payload)
            assert decoded.message_id == record.request_id
            assert payload.request_id == record.request_id
            assert payload.timeout_ms == 5_000
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())


def test_create_requires_connected_refresh_capability() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        session, websocket = _session(
            device_id=device_id,
            refresh_capable=False,
        )
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        try:
            with pytest.raises(
                ObservationRefreshDeviceUnavailableError,
                match="does not advertise",
            ):
                await _create(broker, device_id)
            assert websocket.sent == []
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())


def test_single_flight_blocks_second_refresh_until_terminal() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        session, _ = _session(device_id=device_id)
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        try:
            first = await _create(broker, device_id)
            with pytest.raises(ObservationRefreshBusyError, match="active"):
                await _create(broker, device_id)

            cancelled = await broker.cancel(
                device_id=device_id,
                request_id=first.request_id,
                reason="fixture cancellation",
            )
            assert cancelled.phase == ObservationRefreshPhase.CANCELLED
            second = await _create(broker, device_id)
            assert second.request_id != first.request_id
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())


def test_accepted_refresh_can_report_terminal_capture_timeout() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        session, _ = _session(device_id=device_id)
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        try:
            record = await _create(broker, device_id)
            accepted_envelope, accepted = _ack(
                device_id=device_id,
                request_id=record.request_id,
                status="accepted",
                received_at_ms=10_010,
            )
            record = await broker.record_ack(
                session=session,
                envelope=accepted_envelope,
                acknowledgement=accepted,
            )
            assert record.phase == ObservationRefreshPhase.ACCEPTED

            expired_envelope, expired = _ack(
                device_id=device_id,
                request_id=record.request_id,
                status="expired",
                received_at_ms=10_500,
            )
            record = await broker.record_ack(
                session=session,
                envelope=expired_envelope,
                acknowledgement=expired,
            )
            assert record.phase == ObservationRefreshPhase.EXPIRED
            assert record.acknowledgement == expired
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())


def test_correlated_observation_completes_with_exact_core_evidence() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        session, _ = _session(device_id=device_id)
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        try:
            record = await _create(
                broker,
                device_id,
                expected_active_package="com.example",
            )
            ack_envelope, ack_payload = _ack(
                device_id=device_id,
                request_id=record.request_id,
                status="accepted",
                received_at_ms=10_010,
            )
            await broker.record_ack(
                session=session,
                envelope=ack_envelope,
                acknowledgement=ack_payload,
            )

            observation = _observation(
                stream_id=uuid4(),
                sequence=0,
                active_package="com.example",
                captured_at_ms=10_020,
            )
            observation_status = await registry.record_observation(
                session=session,
                message_id=uuid4(),
                observation=observation,
                received_at_ms=10_030,
            )
            candidate = await broker.prepare_observation_completion(
                session=session,
                refresh_request_id=record.request_id,
                observation=observation,
                observation_status=observation_status,
            )
            assert candidate is not None
            completed = await broker.complete_observation(
                device_id=device_id,
                candidate=candidate,
            )
            assert completed is not None
            assert completed.phase == ObservationRefreshPhase.COMPLETED
            assert completed.evidence == candidate.evidence
            assert completed.evidence.snapshot_id == observation.snapshot.snapshot_id
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())


def test_expected_state_mismatch_rejects_refresh_but_keeps_observation() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        session, _ = _session(device_id=device_id)
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        try:
            record = await _create(
                broker,
                device_id,
                expected_state_fingerprint="a" * 64,
            )
            observation = _observation(
                stream_id=uuid4(),
                sequence=0,
                active_package="com.changed",
                captured_at_ms=10_020,
            )
            status = await registry.record_observation(
                session=session,
                message_id=uuid4(),
                observation=observation,
                received_at_ms=10_030,
            )
            candidate = await broker.prepare_observation_completion(
                session=session,
                refresh_request_id=record.request_id,
                observation=observation,
                observation_status=status,
            )
            assert candidate is None
            rejected = await broker.get(
                device_id=device_id,
                request_id=record.request_id,
            )
            assert rejected.phase == ObservationRefreshPhase.REJECTED
            latest = await registry.latest_observation(device_id)
            assert latest is not None
            assert latest.payload == observation
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())


def test_reconnect_redelivers_exact_request_and_replaces_owner() -> None:
    async def scenario() -> None:
        device_id = uuid4()
        first_session, first_socket = _session(device_id=device_id)
        await registry.register(first_session)
        broker = ObservationRefreshBroker(now_ms=lambda: 10_000)
        record = await _create(broker, device_id)
        assert len(first_socket.sent) == 1
        first_wire = first_socket.sent[0]

        second_session, second_socket = _session(device_id=device_id)
        await registry.register(second_session)
        try:
            await broker.redeliver(second_session)
            assert second_socket.sent == [first_wire]
            current = await broker.get(
                device_id=device_id,
                request_id=record.request_id,
            )
            assert current.delivery_count == 2
            assert current.last_session_id == second_session.session_id

            old_envelope, old_ack = _ack(
                device_id=device_id,
                request_id=record.request_id,
                status="accepted",
                received_at_ms=10_010,
            )
            with pytest.raises(ObservationRefreshConflictError, match="does not own"):
                await broker.record_ack(
                    session=first_session,
                    envelope=old_envelope,
                    acknowledgement=old_ack,
                )
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=second_session.session_id,
            )

    asyncio.run(scenario())


def test_deadline_expiry_is_terminal_and_deterministic() -> None:
    async def scenario() -> None:
        now = [10_000]
        device_id = uuid4()
        session, _ = _session(device_id=device_id)
        await registry.register(session)
        broker = ObservationRefreshBroker(now_ms=lambda: now[0])
        try:
            record = await _create(
                broker,
                device_id,
                timeout_ms=250,
            )
            now[0] = 10_251
            expired = await broker.get(
                device_id=device_id,
                request_id=record.request_id,
            )
            assert expired.phase == ObservationRefreshPhase.EXPIRED
            assert expired.detail == "observation refresh deadline elapsed"
        finally:
            await registry.unregister(
                device_id=device_id,
                session_id=session.session_id,
            )

    asyncio.run(scenario())
