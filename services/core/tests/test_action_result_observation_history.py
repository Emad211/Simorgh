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
    DeviceActionCommandAckPayload,
    DeviceActionResultAckPayload,
    DeviceHeartbeatAckPayload,
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
SOURCE_PACKAGE = "com.example.source"
TARGET_PACKAGE = "com.example.target"
LATER_PACKAGE = "com.example.later"


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
            build_fingerprint="samsung/a53/history-test",
            support_tier="FULL",
            capabilities=[
                "device.identity",
                "android.accessibility.observe.platform",
                "android.open_app.execution.v1",
                "android.core_clock.bounded_estimate.v1",
            ],
        ),
    )


def _register(websocket, device_id: UUID) -> DeviceRegisteredPayload:
    websocket.send_text(_registration(device_id).model_dump_json())
    envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert envelope.type == "device.registered"
    return DeviceRegisteredPayload.model_validate(envelope.payload)


def _observation(
    *,
    device_id: UUID,
    stream_id: UUID,
    sequence: int,
    active_package: str,
    captured_at_ms: int,
) -> tuple[ProtocolEnvelope, DeviceObservationPayload]:
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
    payload = DeviceObservationPayload(
        stream_id=stream_id,
        sequence=sequence,
        state_fingerprint=calculate_accessibility_state_fingerprint(snapshot),
        snapshot=snapshot,
    )
    return (
        ProtocolEnvelope.create(
            message_type="device.observation",
            device_id=device_id,
            payload=payload,
        ),
        payload,
    )


def _send_observation(websocket, envelope: ProtocolEnvelope) -> DeviceObservationAckPayload:
    websocket.send_text(envelope.model_dump_json())
    acknowledgement_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert acknowledgement_envelope.type == "device.observation_ack"
    assert acknowledgement_envelope.correlation_id == envelope.message_id
    acknowledgement = DeviceObservationAckPayload.model_validate(
        acknowledgement_envelope.payload
    )
    assert acknowledgement.status in {"accepted", "unchanged"}
    return acknowledgement


def _reference(observation: DeviceObservationPayload) -> ObservationReference:
    snapshot = observation.snapshot
    return ObservationReference(
        stream_id=observation.stream_id,
        sequence=observation.sequence,
        snapshot_id=snapshot.snapshot_id,
        state_fingerprint=observation.state_fingerprint,
        captured_at_ms=snapshot.captured_at_ms,
        active_package=snapshot.active_package,
    )


def _command(before: DeviceObservationPayload) -> AndroidActionCommand:
    now_ms = int(time.time() * 1000)
    return AndroidActionCommand(
        action_id=uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 60_000,
        precondition=ObservationPrecondition(
            expected_stream_id=before.stream_id,
            minimum_sequence=before.sequence,
            expected_state_fingerprint=before.state_fingerprint,
            expected_active_package=before.snapshot.active_package,
            maximum_age_ms=30_000,
        ),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)],
            timeout_ms=10_000,
            stable_samples=1,
        ),
    )


def _dispatch(
    client: TestClient,
    device_id: UUID,
    command: AndroidActionCommand,
) -> None:
    response = client.post(
        f"/v1/devices/{device_id}/actions",
        headers=OPERATOR_HEADERS,
        json=command.model_dump(mode="json"),
    )
    assert response.status_code == 202
    assert response.json()["phase"] == "delivered"


def _accept_command(
    websocket,
    *,
    device_id: UUID,
    command_envelope: ProtocolEnvelope,
    command: AndroidActionCommand,
) -> None:
    acknowledgement = ProtocolEnvelope.create(
        message_type="device.action_command_ack",
        device_id=device_id,
        correlation_id=command_envelope.message_id,
        payload=DeviceActionCommandAckPayload(
            command_id=command.command_id,
            action_id=command.action_id,
            status="accepted",
            received_at_ms=int(time.time() * 1000),
        ),
    )
    websocket.send_text(acknowledgement.model_dump_json())

    heartbeat = ProtocolEnvelope.create(
        message_type="device.heartbeat",
        device_id=device_id,
        payload=DeviceHeartbeatPayload(sequence=1, app_uptime_ms=100),
    )
    websocket.send_text(heartbeat.model_dump_json())
    heartbeat_ack_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert heartbeat_ack_envelope.type == "device.heartbeat_ack"
    heartbeat_ack = DeviceHeartbeatAckPayload.model_validate(
        heartbeat_ack_envelope.payload
    )
    assert heartbeat_ack.sequence == 1


def _success_result(
    *,
    command: AndroidActionCommand,
    before: DeviceObservationPayload,
    after: DeviceObservationPayload,
) -> AndroidActionResult:
    now_ms = int(time.time() * 1000)
    return AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.SUCCEEDED,
        failure_code=ActionFailureCode.NONE,
        started_at_ms=now_ms,
        finished_at_ms=now_ms + 1,
        attempts=1,
        before_observation=_reference(before),
        after_observation=_reference(after),
        predicates=[
            PredicateEvidence(
                kind="active_package_equals",
                outcome=PredicateOutcome.SATISFIED,
                detail=f"active package={TARGET_PACKAGE} expected={TARGET_PACKAGE}",
            )
        ],
        detail="verified fixture launch",
    )


def _send_result(
    websocket,
    *,
    device_id: UUID,
    command_envelope: ProtocolEnvelope,
    result: AndroidActionResult,
) -> DeviceActionResultAckPayload:
    result_envelope = ProtocolEnvelope.create(
        message_type="device.action_result",
        device_id=device_id,
        correlation_id=command_envelope.message_id,
        payload=result,
    )
    websocket.send_text(result_envelope.model_dump_json())
    acknowledgement_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert acknowledgement_envelope.type == "device.action_result_ack"
    assert acknowledgement_envelope.correlation_id == result_envelope.message_id
    return DeviceActionResultAckPayload.model_validate(acknowledgement_envelope.payload)


def test_valid_result_survives_a_newer_observation_arriving_first(
    client: TestClient,
) -> None:
    device_id = uuid4()
    stream_id = uuid4()
    base_time = int(time.time() * 1000)

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)

        before_envelope, before = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=0,
            active_package=SOURCE_PACKAGE,
            captured_at_ms=base_time,
        )
        _send_observation(websocket, before_envelope)

        command = _command(before)
        _dispatch(client, device_id, command)
        command_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        assert command_envelope.type == "device.action_command"
        _accept_command(
            websocket,
            device_id=device_id,
            command_envelope=command_envelope,
            command=command,
        )

        after_envelope, after = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=1,
            active_package=TARGET_PACKAGE,
            captured_at_ms=base_time + 100,
        )
        _send_observation(websocket, after_envelope)

        later_envelope, _ = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=2,
            active_package=LATER_PACKAGE,
            captured_at_ms=base_time + 200,
        )
        _send_observation(websocket, later_envelope)

        acknowledgement = _send_result(
            websocket,
            device_id=device_id,
            command_envelope=command_envelope,
            result=_success_result(command=command, before=before, after=after),
        )
        assert acknowledgement.status == "accepted"

        status_response = client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert status_response.status_code == 200
        assert status_response.json()["phase"] == "completed"


def test_result_with_forged_after_reference_is_rejected(
    client: TestClient,
) -> None:
    device_id = uuid4()
    stream_id = uuid4()
    base_time = int(time.time() * 1000)

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)

        before_envelope, before = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=0,
            active_package=SOURCE_PACKAGE,
            captured_at_ms=base_time,
        )
        _send_observation(websocket, before_envelope)

        command = _command(before)
        _dispatch(client, device_id, command)
        command_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        _accept_command(
            websocket,
            device_id=device_id,
            command_envelope=command_envelope,
            command=command,
        )

        after_envelope, after = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=1,
            active_package=TARGET_PACKAGE,
            captured_at_ms=base_time + 100,
        )
        _send_observation(websocket, after_envelope)

        result = _success_result(command=command, before=before, after=after)
        forged_after = require_not_none(result.after_observation).model_copy(
            update={"snapshot_id": uuid4()}
        )
        result = result.model_copy(update={"after_observation": forged_after})

        acknowledgement = _send_result(
            websocket,
            device_id=device_id,
            command_envelope=command_envelope,
            result=result,
        )
        assert acknowledgement.status == "rejected"
        assert "after observation is not in Core acknowledged history" in acknowledgement.detail

        status_response = client.get(
            f"/v1/devices/{device_id}/actions/{command.action_id}",
            headers=OPERATOR_HEADERS,
        )
        assert status_response.status_code == 200
        assert status_response.json()["phase"] == "accepted"
        assert status_response.json()["result"] is None


def require_not_none(value: ObservationReference | None) -> ObservationReference:
    assert value is not None
    return value
