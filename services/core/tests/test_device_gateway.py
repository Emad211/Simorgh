from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
from simorgh_core.devices.protocol import (
    AccessibilityNodePayload,
    AccessibilitySnapshotPayload,
    DeviceErrorPayload,
    DeviceHeartbeatAckPayload,
    DeviceHeartbeatPayload,
    DeviceObservationAckPayload,
    DeviceObservationPayload,
    DeviceRegisteredPayload,
    DeviceRegistrationPayload,
    ProtocolEnvelope,
    ScreenBoundsPayload,
    calculate_accessibility_state_fingerprint,
)

ROOT_ID = "1" * 24
SEMANTIC_ID = "2" * 24


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _registration(device_id: UUID) -> ProtocolEnvelope:
    return ProtocolEnvelope.create(
        message_type="device.register",
        device_id=device_id,
        payload=DeviceRegistrationPayload(
            app_version="0.1.0",
            sdk_int=31,
            android_release="12",
            manufacturer="Samsung",
            model="SM-A536B",
            build_fingerprint="samsung/a53/example",
            support_tier="FULL",
            capabilities=[
                "device.identity",
                "android.accessibility.observe.platform",
                "android.accessibility.gesture.platform",
                "android.screen.capture.accessibility.platform",
            ],
        ),
    )


def _snapshot(*, captured_at_ms: int, text: str = "سلام") -> AccessibilitySnapshotPayload:
    return AccessibilitySnapshotPayload(
        snapshot_id=uuid4(),
        captured_at_ms=captured_at_ms,
        active_package="com.example",
        active_window_id=1,
        root_node_id=ROOT_ID,
        windows=[],
        nodes=[
            AccessibilityNodePayload(
                node_id=ROOT_ID,
                path="0",
                depth=0,
                window_id=1,
                package_name="com.example",
                class_name="android.widget.FrameLayout",
                text=text,
                bounds=ScreenBoundsPayload(left=0, top=0, right=1080, bottom=2400),
                semantic_fingerprint=SEMANTIC_ID,
                child_count=0,
                input_type=0,
                clickable=False,
                long_clickable=False,
                focusable=False,
                focused=False,
                editable=False,
                scrollable=False,
                enabled=True,
                selected=False,
                checkable=False,
                checked=False,
                visible_to_user=True,
                accessibility_focused=False,
                password=False,
                heading=False,
                actions=[],
            )
        ],
        truncated=False,
        truncation_reasons=[],
        max_depth_observed=0,
    )


def _observation(
    *,
    device_id: UUID,
    stream_id: UUID,
    sequence: int,
    captured_at_ms: int,
    text: str = "سلام",
    snapshot_id: UUID | None = None,
) -> ProtocolEnvelope:
    snapshot = _snapshot(captured_at_ms=captured_at_ms, text=text)
    if snapshot_id is not None:
        snapshot = snapshot.model_copy(update={"snapshot_id": snapshot_id})
    return ProtocolEnvelope.create(
        message_type="device.observation",
        device_id=device_id,
        payload=DeviceObservationPayload(
            stream_id=stream_id,
            sequence=sequence,
            state_fingerprint=calculate_accessibility_state_fingerprint(snapshot),
            snapshot=snapshot,
        ),
    )


def _connect_and_register(client: TestClient, device_id: UUID):
    websocket = client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    )
    websocket.__enter__()
    registration = _registration(device_id)
    websocket.send_text(registration.model_dump_json())
    registered_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    registered = DeviceRegisteredPayload.model_validate(registered_envelope.payload)
    return websocket, registration, registered_envelope, registered


def _receive_observation_ack(websocket) -> tuple[ProtocolEnvelope, DeviceObservationAckPayload]:
    envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    return envelope, DeviceObservationAckPayload.model_validate(envelope.payload)


def test_device_registers_and_receives_heartbeat_ack(client: TestClient) -> None:
    device_id = uuid4()
    registration = _registration(device_id)

    with client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    ) as websocket:
        websocket.send_text(registration.model_dump_json())

        registered_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        registered = DeviceRegisteredPayload.model_validate(registered_envelope.payload)

        assert registered_envelope.type == "device.registered"
        assert registered_envelope.device_id == device_id
        assert registered_envelope.correlation_id == registration.message_id
        assert registered.heartbeat_interval_seconds == 25

        heartbeat = ProtocolEnvelope.create(
            message_type="device.heartbeat",
            device_id=device_id,
            payload=DeviceHeartbeatPayload(sequence=7, app_uptime_ms=123_456),
        )
        websocket.send_text(heartbeat.model_dump_json())

        ack_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        acknowledgement = DeviceHeartbeatAckPayload.model_validate(ack_envelope.payload)

        assert ack_envelope.type == "device.heartbeat_ack"
        assert ack_envelope.correlation_id == heartbeat.message_id
        assert acknowledgement.sequence == 7


def test_observation_statuses_distinguish_state_and_delivery(client: TestClient) -> None:
    device_id = uuid4()
    stream_id = uuid4()
    first = _observation(
        device_id=device_id,
        stream_id=stream_id,
        sequence=0,
        captured_at_ms=2_000,
    )

    with client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    ) as websocket:
        websocket.send_text(_registration(device_id).model_dump_json())
        ProtocolEnvelope.model_validate_json(websocket.receive_text())

        websocket.send_text(first.model_dump_json())
        first_envelope, first_ack = _receive_observation_ack(websocket)
        assert first_ack.status == "accepted"
        assert first_envelope.correlation_id == first.message_id

        websocket.send_text(first.model_dump_json())
        _, replay_ack = _receive_observation_ack(websocket)
        assert replay_ack.status == "duplicate"

        same_state = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=1,
            captured_at_ms=3_000,
        )
        websocket.send_text(same_state.model_dump_json())
        _, unchanged_ack = _receive_observation_ack(websocket)
        assert unchanged_ack.status == "unchanged"

        stale = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=0,
            captured_at_ms=4_000,
            text="قدیمی",
        )
        websocket.send_text(stale.model_dump_json())
        _, stale_ack = _receive_observation_ack(websocket)
        assert stale_ack.status == "stale"

        changed = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=2,
            captured_at_ms=5_000,
            text="صفحه جدید",
        )
        websocket.send_text(changed.model_dump_json())
        _, changed_ack = _receive_observation_ack(websocket)
        assert changed_ack.status == "accepted"
        assert changed_ack.sequence == 2
        assert changed_ack.stream_id == stream_id


def test_replayed_observation_is_deduplicated_after_reconnect(client: TestClient) -> None:
    device_id = uuid4()
    stream_id = uuid4()
    observation = _observation(
        device_id=device_id,
        stream_id=stream_id,
        sequence=0,
        captured_at_ms=2_000,
    )

    with client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    ) as first_socket:
        first_socket.send_text(_registration(device_id).model_dump_json())
        first_socket.receive_text()
        first_socket.send_text(observation.model_dump_json())
        _, first_ack = _receive_observation_ack(first_socket)
        assert first_ack.status == "accepted"

    with client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    ) as second_socket:
        second_socket.send_text(_registration(device_id).model_dump_json())
        second_socket.receive_text()
        second_socket.send_text(observation.model_dump_json())
        _, replay_ack = _receive_observation_ack(second_socket)
        assert replay_ack.status == "duplicate"


def test_new_process_stream_is_accepted_on_new_session(client: TestClient) -> None:
    device_id = uuid4()

    with client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    ) as first_socket:
        first_socket.send_text(_registration(device_id).model_dump_json())
        first_socket.receive_text()
        first = _observation(
            device_id=device_id,
            stream_id=uuid4(),
            sequence=5,
            captured_at_ms=2_000,
        )
        first_socket.send_text(first.model_dump_json())
        _, first_ack = _receive_observation_ack(first_socket)
        assert first_ack.status == "accepted"

    with client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    ) as second_socket:
        second_socket.send_text(_registration(device_id).model_dump_json())
        second_socket.receive_text()
        restarted = _observation(
            device_id=device_id,
            stream_id=uuid4(),
            sequence=0,
            captured_at_ms=3_000,
            text="پس از راه‌اندازی مجدد",
        )
        second_socket.send_text(restarted.model_dump_json())
        _, restarted_ack = _receive_observation_ack(second_socket)
        assert restarted_ack.status == "accepted"


def test_invalid_state_fingerprint_returns_correlated_error(client: TestClient) -> None:
    device_id = uuid4()
    stream_id = uuid4()
    valid = _observation(
        device_id=device_id,
        stream_id=stream_id,
        sequence=0,
        captured_at_ms=2_000,
    )
    payload = dict(valid.payload)
    payload["state_fingerprint"] = "0" * 64
    invalid = valid.model_copy(update={"payload": payload})

    with client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    ) as websocket:
        websocket.send_text(_registration(device_id).model_dump_json())
        websocket.receive_text()
        websocket.send_text(invalid.model_dump_json())

        error_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        error = DeviceErrorPayload.model_validate(error_envelope.payload)
        assert error_envelope.type == "device.error"
        assert error_envelope.correlation_id == invalid.message_id
        assert error.code == "invalid_message"
        assert "state_fingerprint" in error.message
