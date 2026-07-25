from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.devices.action_capabilities import OPEN_APP_EXECUTION_CAPABILITY
from simorgh_core.devices.actions import (
    ActionFailureCode,
    ActionOutcome,
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidActionResult,
    AndroidVerificationPolicy,
    ObservationPrecondition,
    OpenAppOperation,
)
from simorgh_core.devices.protocol import (
    DeviceActionCommandAckPayload,
    DeviceActionResultAckPayload,
    DeviceHeartbeatPayload,
    DeviceRegistrationPayload,
    ProtocolEnvelope,
)

DEVICE_HEADERS = {"Authorization": "Bearer test-device-token"}
OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}
TARGET_PACKAGE = "com.example.target"


def _registration(device_id: UUID, *, suffix: str) -> ProtocolEnvelope:
    return ProtocolEnvelope.create(
        message_type="device.register",
        device_id=device_id,
        payload=DeviceRegistrationPayload(
            app_version="0.1.0",
            sdk_int=31,
            android_release="12",
            manufacturer="Samsung",
            model="SM-A536B",
            build_fingerprint=f"samsung/a53/journal-restart-{suffix}",
            support_tier="FULL",
            capabilities=[
                "device.action_transport.v1",
                OPEN_APP_EXECUTION_CAPABILITY,
            ],
        ),
    )


def _register(websocket, device_id: UUID, *, suffix: str) -> None:
    registration = _registration(device_id, suffix=suffix)
    websocket.send_text(registration.model_dump_json())
    registered = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert registered.type == "device.registered"
    assert registered.correlation_id == registration.message_id


def _command() -> AndroidActionCommand:
    now_ms = int(time.time() * 1000)
    return AndroidActionCommand(
        command_id=uuid4(),
        action_id=uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 60_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
        ),
    )


def _dispatch(
    client: TestClient,
    *,
    device_id: UUID,
    command: AndroidActionCommand,
):
    return client.post(
        f"/v1/devices/{device_id}/actions",
        headers=OPERATOR_HEADERS,
        json=command.model_dump(mode="json"),
    )


def _send_command_ack(
    websocket,
    *,
    device_id: UUID,
    command: AndroidActionCommand,
    command_envelope: ProtocolEnvelope,
    status: str,
) -> None:
    acknowledgement = ProtocolEnvelope.create(
        message_type="device.action_command_ack",
        device_id=device_id,
        correlation_id=command_envelope.message_id,
        payload=DeviceActionCommandAckPayload(
            command_id=command.command_id,
            action_id=command.action_id,
            status=status,
            received_at_ms=int(time.time() * 1000),
            detail=f"restart fixture {status}",
        ),
    )
    websocket.send_text(acknowledgement.model_dump_json())
    _heartbeat_round_trip(websocket, device_id=device_id, sequence=10)


def _heartbeat_round_trip(websocket, *, device_id: UUID, sequence: int) -> None:
    heartbeat = ProtocolEnvelope.create(
        message_type="device.heartbeat",
        device_id=device_id,
        payload=DeviceHeartbeatPayload(sequence=sequence, app_uptime_ms=sequence * 100),
    )
    websocket.send_text(heartbeat.model_dump_json())
    acknowledgement = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert acknowledgement.type == "device.heartbeat_ack"
    assert acknowledgement.correlation_id == heartbeat.message_id


def _failed_result(command: AndroidActionCommand) -> AndroidActionResult:
    now_ms = int(time.time() * 1000)
    return AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.FAILED,
        failure_code=ActionFailureCode.TARGET_NOT_FOUND,
        started_at_ms=now_ms,
        finished_at_ms=now_ms + 1,
        attempts=0,
        detail="target package was not installed",
    )


def test_core_restart_accepts_orphaned_result_without_reexecuting_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    device_id = uuid4()
    command = _command()
    command_envelope: ProtocolEnvelope

    with TestClient(app) as first_client, first_client.websocket_connect(
        "/v1/devices/ws",
        headers=DEVICE_HEADERS,
    ) as first_socket:
        _register(first_socket, device_id, suffix="before")
        response = _dispatch(
            first_client,
            device_id=device_id,
            command=command,
        )
        assert response.status_code == 202
        command_envelope = ProtocolEnvelope.model_validate_json(
            first_socket.receive_text()
        )
        assert command_envelope.type == "device.action_command"
        _send_command_ack(
            first_socket,
            device_id=device_id,
            command=command,
            command_envelope=command_envelope,
            status="accepted",
        )

    stable_result = _failed_result(command)
    stable_result_envelope = ProtocolEnvelope(
        message_id=uuid4(),
        type="device.action_result",
        sent_at_ms=int(time.time() * 1000),
        device_id=device_id,
        correlation_id=command_envelope.message_id,
        payload=stable_result.model_dump(mode="json"),
    )

    with TestClient(app) as restarted_client, restarted_client.websocket_connect(
        "/v1/devices/ws",
        headers=DEVICE_HEADERS,
    ) as restarted_socket:
        _register(restarted_socket, device_id, suffix="after")

        # The recovered accepted command is not sent again. A heartbeat must be the next
        # round trip after registration.
        _heartbeat_round_trip(restarted_socket, device_id=device_id, sequence=20)

        restarted_socket.send_text(stable_result_envelope.model_dump_json())
        result_ack_envelope = ProtocolEnvelope.model_validate_json(
            restarted_socket.receive_text()
        )
        result_ack = DeviceActionResultAckPayload.model_validate(
            result_ack_envelope.payload
        )
        assert result_ack_envelope.type == "device.action_result_ack"
        assert result_ack_envelope.correlation_id == stable_result_envelope.message_id
        assert result_ack.status == "accepted"

        completed = restarted_client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert completed.status_code == 200
        assert completed.json()["phase"] == "completed"
        assert completed.json()["result"]["outcome"] == "failed"

        next_command = _command()
        next_response = _dispatch(
            restarted_client,
            device_id=device_id,
            command=next_command,
        )
        assert next_response.status_code == 202
        next_envelope = ProtocolEnvelope.model_validate_json(
            restarted_socket.receive_text()
        )
        assert next_envelope.type == "device.action_command"
        assert AndroidActionCommand.model_validate(next_envelope.payload) == next_command

        _send_command_ack(
            restarted_socket,
            device_id=device_id,
            command=next_command,
            command_envelope=next_envelope,
            status="rejected",
        )
