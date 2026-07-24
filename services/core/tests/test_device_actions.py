from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
from simorgh_core.devices.actions import (
    ActionFailureCode,
    ActionOutcome,
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidActionResult,
    AndroidVerificationPolicy,
    ObservationPrecondition,
    ObservationReference,
    OpenAppOperation,
    PredicateEvidence,
    PredicateOutcome,
)
from simorgh_core.devices.protocol import (
    AccessibilitySnapshotPayload,
    DeviceActionCancelAckPayload,
    DeviceActionCommandAckPayload,
    DeviceActionResultAckPayload,
    DeviceHeartbeatPayload,
    DeviceObservationAckPayload,
    DeviceObservationPayload,
    DeviceRegisteredPayload,
    DeviceRegistrationPayload,
    ProtocolEnvelope,
    calculate_accessibility_state_fingerprint,
)

DEVICE_HEADERS = {"Authorization": "Bearer test-device-token"}
OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}
TARGET_PACKAGE = "com.example"


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
            build_fingerprint="samsung/a53/action-test",
            support_tier="FULL",
            capabilities=[
                "device.identity",
                "android.accessibility.observe.platform",
                "android.accessibility.gesture.platform",
                "android.open_app.execution.v1",
            ],
        ),
    )


def _register(websocket, device_id: UUID) -> DeviceRegisteredPayload:
    websocket.send_text(_registration(device_id).model_dump_json())
    registered_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert registered_envelope.type == "device.registered"
    return DeviceRegisteredPayload.model_validate(registered_envelope.payload)


def _command(
    *,
    action_id: UUID | None = None,
    command_id: UUID | None = None,
) -> AndroidActionCommand:
    now_ms = int(time.time() * 1000)
    return AndroidActionCommand(
        command_id=command_id or uuid4(),
        action_id=action_id or uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 60_000,
        precondition=ObservationPrecondition(maximum_age_ms=2_000),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)],
        ),
    )


def _dispatch(client: TestClient, device_id: UUID, command: AndroidActionCommand):
    return client.post(
        f"/v1/devices/{device_id}/actions",
        headers=OPERATOR_HEADERS,
        json=command.model_dump(mode="json"),
    )


def _send_command_ack(
    websocket,
    *,
    device_id: UUID,
    command_envelope: ProtocolEnvelope,
    command: AndroidActionCommand,
    status: str = "accepted",
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
        ),
    )
    websocket.send_text(acknowledgement.model_dump_json())
    _round_trip_heartbeat(websocket, device_id)


def _send_target_observation(
    websocket,
    *,
    device_id: UUID,
    sequence: int = 0,
) -> tuple[DeviceObservationPayload, DeviceObservationAckPayload]:
    captured_at_ms = int(time.time() * 1000)
    snapshot = AccessibilitySnapshotPayload(
        snapshot_id=uuid4(),
        captured_at_ms=captured_at_ms,
        active_package=TARGET_PACKAGE,
        active_window_id=None,
        root_node_id=None,
        windows=[],
        nodes=[],
        truncated=False,
        truncation_reasons=[],
        max_depth_observed=0,
    )
    observation = DeviceObservationPayload(
        stream_id=uuid4(),
        sequence=sequence,
        state_fingerprint=calculate_accessibility_state_fingerprint(snapshot),
        snapshot=snapshot,
    )
    envelope = ProtocolEnvelope.create(
        message_type="device.observation",
        device_id=device_id,
        payload=observation,
    )
    websocket.send_text(envelope.model_dump_json())
    ack_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    acknowledgement = DeviceObservationAckPayload.model_validate(ack_envelope.payload)
    assert ack_envelope.type == "device.observation_ack"
    assert ack_envelope.correlation_id == envelope.message_id
    assert acknowledgement.status == "accepted"
    return observation, acknowledgement


def _reference(observation: DeviceObservationPayload) -> ObservationReference:
    return ObservationReference(
        stream_id=observation.stream_id,
        sequence=observation.sequence,
        snapshot_id=observation.snapshot.snapshot_id,
        state_fingerprint=observation.state_fingerprint,
        captured_at_ms=observation.snapshot.captured_at_ms,
        active_package=observation.snapshot.active_package,
    )


def _verified_success_result(
    *,
    command: AndroidActionCommand,
    observation: DeviceObservationPayload,
) -> AndroidActionResult:
    reference = _reference(observation)
    now_ms = int(time.time() * 1000)
    return AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.SUCCEEDED,
        failure_code=ActionFailureCode.NONE,
        started_at_ms=now_ms,
        finished_at_ms=now_ms,
        attempts=0,
        before_observation=reference,
        after_observation=reference,
        predicates=[
            PredicateEvidence(
                kind="active_package_equals",
                outcome=PredicateOutcome.SATISFIED,
                detail=f"active package={TARGET_PACKAGE} expected={TARGET_PACKAGE}",
            )
        ],
        detail="target package was already active",
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


def test_operator_authentication_is_separate_from_device_token(client: TestClient) -> None:
    command = _command()
    device_id = uuid4()

    missing = client.post(
        f"/v1/devices/{device_id}/actions",
        json=command.model_dump(mode="json"),
    )
    device_credential = client.post(
        f"/v1/devices/{device_id}/actions",
        headers=DEVICE_HEADERS,
        json=command.model_dump(mode="json"),
    )

    assert missing.status_code == 401
    assert device_credential.status_code == 401


def test_action_dispatch_ack_verified_result_and_duplicate_result(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)

        response = _dispatch(client, device_id, command)
        assert response.status_code == 202
        assert response.json()["phase"] == "delivered"

        command_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        decoded_command = AndroidActionCommand.model_validate(command_envelope.payload)
        assert command_envelope.type == "device.action_command"
        assert decoded_command == command

        _send_command_ack(
            websocket,
            device_id=device_id,
            command_envelope=command_envelope,
            command=command,
        )
        accepted = client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert accepted.status_code == 200
        assert accepted.json()["phase"] == "accepted"

        observation, _ = _send_target_observation(
            websocket,
            device_id=device_id,
        )
        result = _verified_success_result(command=command, observation=observation)
        result_envelope = ProtocolEnvelope.create(
            message_type="device.action_result",
            device_id=device_id,
            correlation_id=command_envelope.message_id,
            payload=result,
        )
        websocket.send_text(result_envelope.model_dump_json())

        result_ack_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        result_ack = DeviceActionResultAckPayload.model_validate(result_ack_envelope.payload)
        assert result_ack_envelope.type == "device.action_result_ack"
        assert result_ack_envelope.correlation_id == result_envelope.message_id
        assert result_ack.status == "accepted"

        completed = client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert completed.status_code == 200
        assert completed.json()["phase"] == "completed"
        assert completed.json()["result"]["outcome"] == "succeeded"

        websocket.send_text(result_envelope.model_dump_json())
        duplicate_ack_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        duplicate_ack = DeviceActionResultAckPayload.model_validate(
            duplicate_ack_envelope.payload
        )
        assert duplicate_ack.status == "duplicate"


def test_unverifiable_success_is_rejected_without_completing_action(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)
        assert _dispatch(client, device_id, command).status_code == 202
        command_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        _send_command_ack(
            websocket,
            device_id=device_id,
            command_envelope=command_envelope,
            command=command,
        )

        now_ms = int(time.time() * 1000)
        forged = AndroidActionResult(
            command_id=command.command_id,
            action_id=command.action_id,
            outcome=ActionOutcome.SUCCEEDED,
            failure_code=ActionFailureCode.NONE,
            started_at_ms=now_ms,
            finished_at_ms=now_ms,
            attempts=0,
            detail="claims success without evidence",
        )
        result_envelope = ProtocolEnvelope.create(
            message_type="device.action_result",
            device_id=device_id,
            correlation_id=command_envelope.message_id,
            payload=forged,
        )
        websocket.send_text(result_envelope.model_dump_json())

        ack_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        acknowledgement = DeviceActionResultAckPayload.model_validate(ack_envelope.payload)
        assert acknowledgement.status == "rejected"
        assert "requires before and after" in acknowledgement.detail

        current = client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert current.status_code == 200
        assert current.json()["phase"] == "accepted"
        assert current.json()["result"] is None


def test_pending_command_is_redelivered_with_same_message_id_after_reconnect(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as first_socket:
        _register(first_socket, device_id)
        response = _dispatch(client, device_id, command)
        assert response.status_code == 202
        first_envelope = ProtocolEnvelope.model_validate_json(first_socket.receive_text())

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as second_socket:
        _register(second_socket, device_id)
        replayed = ProtocolEnvelope.model_validate_json(second_socket.receive_text())
        assert replayed.type == "device.action_command"
        assert replayed.message_id == first_envelope.message_id
        assert replayed.payload == first_envelope.payload

        _send_command_ack(
            second_socket,
            device_id=device_id,
            command_envelope=replayed,
            command=command,
            status="rejected",
        )


def test_device_enforces_single_flight_actions(client: TestClient) -> None:
    device_id = uuid4()
    first = _command()
    second = _command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)
        first_response = _dispatch(client, device_id, first)
        first_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        second_response = _dispatch(client, device_id, second)

        assert first_response.status_code == 202
        assert second_response.status_code == 409
        assert "active action" in second_response.json()["detail"]

        _send_command_ack(
            websocket,
            device_id=device_id,
            command_envelope=first_envelope,
            command=first,
            status="rejected",
        )


def test_cancel_uses_a_stable_typed_message(client: TestClient) -> None:
    device_id = uuid4()
    command = _command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)
        assert _dispatch(client, device_id, command).status_code == 202
        command_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        _send_command_ack(
            websocket,
            device_id=device_id,
            command_envelope=command_envelope,
            command=command,
        )

        response = client.post(
            f"/v1/devices/{device_id}/actions/{command.action_id}/cancel",
            headers=OPERATOR_HEADERS,
            json={"reason": "test cancellation"},
        )
        assert response.status_code == 202
        assert response.json()["phase"] == "cancelling"

        cancel_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        assert cancel_envelope.type == "device.action_cancel"
        assert cancel_envelope.correlation_id == command_envelope.message_id

        cancel_ack_envelope = ProtocolEnvelope.create(
            message_type="device.action_cancel_ack",
            device_id=device_id,
            correlation_id=cancel_envelope.message_id,
            payload=DeviceActionCancelAckPayload(
                command_id=command.command_id,
                action_id=command.action_id,
                status="accepted",
                received_at_ms=int(time.time() * 1000),
            ),
        )
        websocket.send_text(cancel_ack_envelope.model_dump_json())
        _round_trip_heartbeat(websocket, device_id)
