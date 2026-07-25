from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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
from simorgh_core.devices.registry import DeviceSession

DEVICE_HEADERS = {"Authorization": "Bearer test-device-token"}
OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}
TARGET_PACKAGE = "com.example.target"


def _register(websocket, device_id: UUID, *, suffix: str) -> None:
    registration = ProtocolEnvelope.create(
        message_type="device.register",
        device_id=device_id,
        payload=DeviceRegistrationPayload(
            app_version="0.1.0",
            sdk_int=31,
            android_release="12",
            manufacturer="Samsung",
            model="SM-A536B",
            build_fingerprint=f"samsung/a53/result-ack-crash-{suffix}",
            support_tier="FULL",
            capabilities=[
                "device.action_transport.v1",
                OPEN_APP_EXECUTION_CAPABILITY,
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
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
        ),
    )


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
        detail="fixture package was not installed",
    )


def _heartbeat(websocket, device_id: UUID, sequence: int) -> None:
    envelope = ProtocolEnvelope.create(
        message_type="device.heartbeat",
        device_id=device_id,
        payload=DeviceHeartbeatPayload(sequence=sequence, app_uptime_ms=sequence * 100),
    )
    websocket.send_text(envelope.model_dump_json())
    acknowledgement = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert acknowledgement.type == "device.heartbeat_ack"


def test_result_replay_is_duplicate_after_ack_socket_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    device_id = uuid4()
    command = _command()
    result = _failed_result(command)
    result_envelope: ProtocolEnvelope

    original_send = DeviceSession.send_envelope
    fail_next_result_ack = True

    async def crash_before_result_ack(
        session: DeviceSession,
        envelope: ProtocolEnvelope,
    ) -> None:
        nonlocal fail_next_result_ack
        if envelope.type == "device.action_result_ack" and fail_next_result_ack:
            fail_next_result_ack = False
            raise WebSocketDisconnect(code=1006, reason="fixture Core crash before ACK")
        await original_send(session, envelope)

    monkeypatch.setattr(DeviceSession, "send_envelope", crash_before_result_ack)

    with TestClient(app) as first_client, first_client.websocket_connect(
        "/v1/devices/ws",
        headers=DEVICE_HEADERS,
    ) as first_socket:
        _register(first_socket, device_id, suffix="before")
        response = first_client.post(
            f"/v1/devices/{device_id}/actions",
            headers=OPERATOR_HEADERS,
            json=command.model_dump(mode="json"),
        )
        assert response.status_code == 202
        command_envelope = ProtocolEnvelope.model_validate_json(first_socket.receive_text())

        command_ack = ProtocolEnvelope.create(
            message_type="device.action_command_ack",
            device_id=device_id,
            correlation_id=command_envelope.message_id,
            payload=DeviceActionCommandAckPayload(
                command_id=command.command_id,
                action_id=command.action_id,
                status="accepted",
                received_at_ms=int(time.time() * 1000),
                detail="fixture accepted",
            ),
        )
        first_socket.send_text(command_ack.model_dump_json())
        _heartbeat(first_socket, device_id, sequence=1)

        result_envelope = ProtocolEnvelope(
            message_id=uuid4(),
            type="device.action_result",
            sent_at_ms=int(time.time() * 1000),
            device_id=device_id,
            correlation_id=command_envelope.message_id,
            payload=result.model_dump(mode="json"),
        )
        first_socket.send_text(result_envelope.model_dump_json())
        with pytest.raises(WebSocketDisconnect):
            first_socket.receive_text()

        completed = first_client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert completed.status_code == 200
        assert completed.json()["phase"] == "completed"

    monkeypatch.setattr(DeviceSession, "send_envelope", original_send)

    with TestClient(app) as restarted_client, restarted_client.websocket_connect(
        "/v1/devices/ws",
        headers=DEVICE_HEADERS,
    ) as restarted_socket:
        _register(restarted_socket, device_id, suffix="after")
        _heartbeat(restarted_socket, device_id, sequence=2)

        restarted_socket.send_text(result_envelope.model_dump_json())
        ack_envelope = ProtocolEnvelope.model_validate_json(restarted_socket.receive_text())
        acknowledgement = DeviceActionResultAckPayload.model_validate(ack_envelope.payload)
        assert ack_envelope.type == "device.action_result_ack"
        assert ack_envelope.correlation_id == result_envelope.message_id
        assert acknowledgement.status == "duplicate"

        durable = restarted_client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert durable.status_code == 200
        assert durable.json()["phase"] == "completed"
        assert durable.json()["result"]["detail"] == result.detail
