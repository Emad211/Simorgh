from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
from simorgh_core.devices.action_capabilities import (
    CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
    OPEN_APP_EXECUTION_CAPABILITY,
)
from simorgh_core.devices.actions import (
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidVerificationPolicy,
    ObservationPrecondition,
    OpenAppOperation,
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


def _register(websocket, device_id: UUID) -> None:
    registration = ProtocolEnvelope.create(
        message_type="device.register",
        device_id=device_id,
        payload=DeviceRegistrationPayload(
            app_version="0.1.0",
            sdk_int=31,
            android_release="12",
            manufacturer="Samsung",
            model="SM-A536B",
            build_fingerprint="samsung/a53/ack-transition-test",
            support_tier="FULL",
            capabilities=[
                "device.action_transport.v1",
                OPEN_APP_EXECUTION_CAPABILITY,
                CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
            ],
        ),
    )
    websocket.send_text(registration.model_dump_json())
    registered = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert registered.type == "device.registered"


def _command() -> AndroidActionCommand:
    now_ms = int(time.time() * 1000)
    return AndroidActionCommand(
        command_id=uuid4(),
        action_id=uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 60_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(package_name="com.example"),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name="com.example")],
        ),
    )


def _dispatch(client: TestClient, device_id: UUID, command: AndroidActionCommand):
    return client.post(
        f"/v1/devices/{device_id}/actions",
        headers=OPERATOR_HEADERS,
        json=command.model_dump(mode="json"),
    )


def _command_ack(
    *,
    device_id: UUID,
    command_envelope: ProtocolEnvelope,
    command: AndroidActionCommand,
    status: str,
) -> ProtocolEnvelope:
    return ProtocolEnvelope.create(
        message_type="device.action_command_ack",
        device_id=device_id,
        correlation_id=command_envelope.message_id,
        payload=DeviceActionCommandAckPayload(
            command_id=command.command_id,
            action_id=command.action_id,
            status=status,
            received_at_ms=int(time.time() * 1000),
            detail=f"fixture {status}",
        ),
    )


def _heartbeat_round_trip(websocket, device_id: UUID, sequence: int) -> None:
    heartbeat = ProtocolEnvelope.create(
        message_type="device.heartbeat",
        device_id=device_id,
        payload=DeviceHeartbeatPayload(sequence=sequence, app_uptime_ms=sequence * 100),
    )
    websocket.send_text(heartbeat.model_dump_json())
    acknowledgement = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert acknowledgement.type == "device.heartbeat_ack"
    assert acknowledgement.correlation_id == heartbeat.message_id


def test_accepted_command_ack_cannot_be_overwritten_by_rejected_ack(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)
        assert _dispatch(client, device_id, command).status_code == 202
        command_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())

        accepted_ack = _command_ack(
            device_id=device_id,
            command_envelope=command_envelope,
            command=command,
            status="accepted",
        )
        websocket.send_text(accepted_ack.model_dump_json())
        _heartbeat_round_trip(websocket, device_id, sequence=1)

        conflicting_ack = _command_ack(
            device_id=device_id,
            command_envelope=command_envelope,
            command=command,
            status="rejected",
        )
        websocket.send_text(conflicting_ack.model_dump_json())
        error_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())

        assert error_envelope.type == "device.error"
        assert error_envelope.correlation_id == conflicting_ack.message_id
        status_response = client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert status_response.status_code == 200
        assert status_response.json()["phase"] == "accepted"
        assert status_response.json()["command_ack"]["status"] == "accepted"


def test_late_accepted_command_ack_does_not_exit_cancelling_phase(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)
        assert _dispatch(client, device_id, command).status_code == 202
        command_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())

        cancel_response = client.post(
            f"/v1/devices/{device_id}/actions/{command.action_id}/cancel",
            headers=OPERATOR_HEADERS,
            json={"reason": "cancel before command ack"},
        )
        assert cancel_response.status_code == 202
        assert cancel_response.json()["phase"] == "cancelling"
        cancel_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        assert cancel_envelope.type == "device.action_cancel"

        accepted_ack = _command_ack(
            device_id=device_id,
            command_envelope=command_envelope,
            command=command,
            status="accepted",
        )
        websocket.send_text(accepted_ack.model_dump_json())
        _heartbeat_round_trip(websocket, device_id, sequence=2)

        status_response = client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert status_response.status_code == 200
        assert status_response.json()["phase"] == "cancelling"
        assert status_response.json()["command_ack"]["status"] == "accepted"
