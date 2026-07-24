from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
from simorgh_core.devices.protocol import (
    DeviceHeartbeatAckPayload,
    DeviceHeartbeatPayload,
    DeviceRegisteredPayload,
    DeviceRegistrationPayload,
    ProtocolEnvelope,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_device_registers_and_receives_heartbeat_ack(client: TestClient) -> None:
    device_id = uuid4()
    registration = ProtocolEnvelope.create(
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
                "android.accessibility.gesture.platform",
                "android.screen.capture.accessibility.platform",
            ],
        ),
    )

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
