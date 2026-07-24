from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
from simorgh_core.devices.actions import (
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidNodeSelector,
    AndroidVerificationPolicy,
    NodeExistsPredicate,
    ObservationPrecondition,
    OpenAppOperation,
    SelectorField,
    TextCriterion,
)
from simorgh_core.devices.protocol import (
    DeviceActionCommandAckPayload,
    DeviceHeartbeatPayload,
    DeviceRegistrationPayload,
    ProtocolEnvelope,
)

DEVICE_HEADERS = {"Authorization": "Bearer test-device-token"}
OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
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
            build_fingerprint="samsung/a53/open-app-contract-test",
            support_tier="FULL",
            capabilities=[
                "device.action_transport.v1",
                "android.open_app.execution.v1",
                "android.accessibility.observe.platform",
            ],
        ),
    )


def _round_trip_heartbeat(websocket, device_id: UUID) -> None:
    heartbeat = ProtocolEnvelope.create(
        message_type="device.heartbeat",
        device_id=device_id,
        payload=DeviceHeartbeatPayload(sequence=1, app_uptime_ms=100),
    )
    websocket.send_text(heartbeat.model_dump_json())
    acknowledgement = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert acknowledgement.type == "device.heartbeat_ack"
    assert acknowledgement.correlation_id == heartbeat.message_id


def test_open_app_observation_binding_and_verification_reach_android_unchanged(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command_id = uuid4()
    action_id = uuid4()
    stream_id = uuid4()
    now_ms = int(time.time() * 1000)
    expected_fingerprint = "a" * 64
    command = AndroidActionCommand(
        command_id=command_id,
        action_id=action_id,
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 60_000,
        precondition=ObservationPrecondition(
            expected_stream_id=stream_id,
            minimum_sequence=42,
            expected_state_fingerprint=expected_fingerprint,
            expected_active_package="com.android.launcher",
            maximum_age_ms=1_500,
        ),
        operation=OpenAppOperation(
            package_name="com.example.target",
            uri="example://orders/123",
        ),
        verification=AndroidVerificationPolicy(
            predicates=[
                ActivePackageEqualsPredicate(package_name="com.example.target"),
                NodeExistsPredicate(
                    selector=AndroidNodeSelector(
                        package_name="com.example.target",
                        view_id="com.example.target:id/order_title",
                        text=TextCriterion(value="سفارش ۱۲۳"),
                        required_fields={SelectorField.VIEW_ID},
                    )
                ),
            ],
            timeout_ms=7_500,
            stable_samples=2,
        ),
    )

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        websocket.send_text(_registration(device_id).model_dump_json())
        registered = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        assert registered.type == "device.registered"

        response = client.post(
            f"/v1/devices/{device_id}/actions",
            headers=OPERATOR_HEADERS,
            json=command.model_dump(mode="json"),
        )
        assert response.status_code == 202

        command_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        delivered = AndroidActionCommand.model_validate(command_envelope.payload)

        assert command_envelope.type == "device.action_command"
        assert command_envelope.device_id == device_id
        assert delivered == command
        assert delivered.precondition.expected_stream_id == stream_id
        assert delivered.precondition.minimum_sequence == 42
        assert delivered.precondition.expected_state_fingerprint == expected_fingerprint
        assert delivered.verification.stable_samples == 2
        assert delivered.verification.timeout_ms == 7_500
        assert isinstance(delivered.operation, OpenAppOperation)
        assert delivered.operation.uri == "example://orders/123"
        assert delivered.verification.predicates[1].kind == "node_exists"

        rejected = ProtocolEnvelope.create(
            message_type="device.action_command_ack",
            device_id=device_id,
            correlation_id=command_envelope.message_id,
            payload=DeviceActionCommandAckPayload(
                command_id=command_id,
                action_id=action_id,
                status="rejected",
                received_at_ms=int(time.time() * 1000),
                detail="contract fixture completed without device execution",
            ),
        )
        websocket.send_text(rejected.model_dump_json())
        _round_trip_heartbeat(websocket, device_id)
