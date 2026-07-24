from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
from simorgh_core.devices.protocol import (
    AccessibilityNodePayload,
    AccessibilitySnapshotPayload,
    DeviceHeartbeatAckPayload,
    DeviceHeartbeatPayload,
    DeviceObservationAckPayload,
    DeviceObservationPayload,
    DeviceRegisteredPayload,
    DeviceRegistrationPayload,
    ProtocolEnvelope,
    ScreenBoundsPayload,
)


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


def _observation(
    *,
    device_id: UUID,
    captured_at_ms: int,
    state_fingerprint: str,
    snapshot_id: UUID | None = None,
) -> ProtocolEnvelope:
    resolved_snapshot_id = snapshot_id or uuid4()
    return ProtocolEnvelope.create(
        message_type="device.observation",
        device_id=device_id,
        payload=DeviceObservationPayload(
            state_fingerprint=state_fingerprint,
            snapshot=AccessibilitySnapshotPayload(
                snapshot_id=resolved_snapshot_id,
                captured_at_ms=captured_at_ms,
                active_package="com.example",
                active_window_id=1,
                root_node_id="root",
                windows=[],
                nodes=[
                    AccessibilityNodePayload(
                        node_id="root",
                        path="0",
                        depth=0,
                        window_id=1,
                        package_name="com.example",
                        class_name="android.widget.FrameLayout",
                        text="سلام",
                        bounds=ScreenBoundsPayload(left=0, top=0, right=1080, bottom=2400),
                        semantic_fingerprint="semantic-root",
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
            ),
        ),
    )


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


def test_observation_is_accepted_deduplicated_and_stale_checked(client: TestClient) -> None:
    device_id = uuid4()
    registration = _registration(device_id)
    accepted_observation = _observation(
        device_id=device_id,
        captured_at_ms=2_000,
        state_fingerprint="state-new",
    )

    with client.websocket_connect(
        "/v1/devices/ws",
        headers={"Authorization": "Bearer test-device-token"},
    ) as websocket:
        websocket.send_text(registration.model_dump_json())
        ProtocolEnvelope.model_validate_json(websocket.receive_text())

        websocket.send_text(accepted_observation.model_dump_json())
        accepted_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        accepted = DeviceObservationAckPayload.model_validate(accepted_envelope.payload)

        assert accepted_envelope.type == "device.observation_ack"
        assert accepted_envelope.correlation_id == accepted_observation.message_id
        assert accepted.status == "accepted"

        websocket.send_text(accepted_observation.model_dump_json())
        duplicate_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        duplicate = DeviceObservationAckPayload.model_validate(duplicate_envelope.payload)

        assert duplicate_envelope.correlation_id == accepted_observation.message_id
        assert duplicate.snapshot_id == accepted.snapshot_id
        assert duplicate.status == "duplicate"

        stale_observation = _observation(
            device_id=device_id,
            captured_at_ms=1_000,
            state_fingerprint="state-old",
        )
        websocket.send_text(stale_observation.model_dump_json())
        stale_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        stale = DeviceObservationAckPayload.model_validate(stale_envelope.payload)

        assert stale_envelope.correlation_id == stale_observation.message_id
        assert stale.status == "stale"
