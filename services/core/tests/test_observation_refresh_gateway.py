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
    AndroidVerificationPolicy,
    ObservationPrecondition,
    OpenAppOperation,
)
from simorgh_core.devices.observation_refresh_protocol import (
    OBSERVATION_REFRESH_CAPABILITY,
    DeviceObservationRefreshAckEnvelope,
    DeviceObservationRefreshAckPayload,
    DeviceObservationRefreshEnvelope,
    DeviceObservationRefreshPayload,
)
from simorgh_core.devices.protocol import (
    AccessibilitySnapshotPayload,
    DeviceActionCommandAckPayload,
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
ACTIVE_PACKAGE = "com.example.stable"


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
            build_fingerprint="samsung/a53/refresh-gateway-test",
            support_tier="FULL",
            capabilities=[
                "device.identity",
                "android.accessibility.observe.platform",
                "android.open_app.execution.v1",
                OBSERVATION_REFRESH_CAPABILITY,
            ],
        ),
    )


def _register(websocket, device_id: UUID) -> DeviceRegisteredPayload:
    websocket.send_text(_registration(device_id).model_dump_json())
    envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert envelope.type == "device.registered"
    return DeviceRegisteredPayload.model_validate(envelope.payload)


def _snapshot(*, snapshot_id: UUID, captured_at_ms: int) -> AccessibilitySnapshotPayload:
    return AccessibilitySnapshotPayload(
        snapshot_id=snapshot_id,
        captured_at_ms=captured_at_ms,
        active_package=ACTIVE_PACKAGE,
        active_window_id=None,
        root_node_id=None,
        windows=[],
        nodes=[],
        truncated=False,
        truncation_reasons=[],
        max_depth_observed=0,
    )


def _observation(
    *,
    device_id: UUID,
    stream_id: UUID,
    sequence: int,
    snapshot_id: UUID,
    captured_at_ms: int,
    refresh_request_id: UUID | None = None,
) -> tuple[ProtocolEnvelope, DeviceObservationPayload]:
    snapshot = _snapshot(
        snapshot_id=snapshot_id,
        captured_at_ms=captured_at_ms,
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
            correlation_id=refresh_request_id,
            payload=payload,
        ),
        payload,
    )


def _send_observation(websocket, envelope: ProtocolEnvelope) -> DeviceObservationAckPayload:
    websocket.send_text(envelope.model_dump_json())
    acknowledgement_envelope = ProtocolEnvelope.model_validate_json(
        websocket.receive_text()
    )
    assert acknowledgement_envelope.type == "device.observation_ack"
    assert acknowledgement_envelope.correlation_id == envelope.message_id
    return DeviceObservationAckPayload.model_validate(
        acknowledgement_envelope.payload
    )


def _send_refresh_ack(
    websocket,
    *,
    device_id: UUID,
    request_id: UUID,
    status: str = "accepted",
) -> None:
    acknowledgement = DeviceObservationRefreshAckPayload(
        request_id=request_id,
        status=status,  # type: ignore[arg-type]
        received_at_ms=int(time.time() * 1000),
        detail=f"fixture {status}",
    )
    envelope = DeviceObservationRefreshAckEnvelope.create(
        device_id=device_id,
        request_envelope_id=request_id,
        payload=acknowledgement,
    )
    websocket.send_text(envelope.model_dump_json())
    _round_trip_heartbeat(websocket, device_id)


def _round_trip_heartbeat(websocket, device_id: UUID) -> None:
    heartbeat = ProtocolEnvelope.create(
        message_type="device.heartbeat",
        device_id=device_id,
        payload=DeviceHeartbeatPayload(sequence=1, app_uptime_ms=100),
    )
    websocket.send_text(heartbeat.model_dump_json())
    envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert envelope.type == "device.heartbeat_ack"
    acknowledgement = DeviceHeartbeatAckPayload.model_validate(envelope.payload)
    assert acknowledgement.sequence == 1


def _create_refresh(
    client: TestClient,
    *,
    device_id: UUID,
    expected_fingerprint: str,
) -> dict[str, object]:
    response = client.post(
        f"/v1/devices/{device_id}/observation-refreshes",
        headers=OPERATOR_HEADERS,
        json={
            "timeout_ms": 5_000,
            "expected_state_fingerprint": expected_fingerprint,
            "expected_active_package": ACTIVE_PACKAGE,
            "reason": "test unchanged state refresh",
        },
    )
    assert response.status_code == 202
    return response.json()


def test_unchanged_screen_refresh_returns_strict_action_evidence(
    client: TestClient,
) -> None:
    device_id = uuid4()
    stream_id = uuid4()
    now_ms = int(time.time() * 1000)

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)

        initial_envelope, initial = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=0,
            snapshot_id=uuid4(),
            captured_at_ms=now_ms,
        )
        initial_ack = _send_observation(websocket, initial_envelope)
        assert initial_ack.status == "accepted"

        created = _create_refresh(
            client,
            device_id=device_id,
            expected_fingerprint=initial.state_fingerprint,
        )
        assert created["phase"] == "delivered"
        request_id = UUID(str(created["request_id"]))

        request_envelope = DeviceObservationRefreshEnvelope.model_validate_json(
            websocket.receive_text()
        )
        request = DeviceObservationRefreshPayload.model_validate(
            request_envelope.payload
        )
        assert request_envelope.message_id == request_id
        assert request.request_id == request_id
        assert request.expected_state_fingerprint == initial.state_fingerprint
        assert request.expected_active_package == ACTIVE_PACKAGE

        _send_refresh_ack(
            websocket,
            device_id=device_id,
            request_id=request_id,
        )

        refreshed_envelope, refreshed = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=1,
            snapshot_id=uuid4(),
            captured_at_ms=now_ms + 100,
            refresh_request_id=request_id,
        )
        assert refreshed.state_fingerprint == initial.state_fingerprint
        refreshed_ack = _send_observation(websocket, refreshed_envelope)
        assert refreshed_ack.status == "unchanged"

        status_response = client.get(
            f"/v1/devices/{device_id}/observation-refreshes/{request_id}",
            headers=OPERATOR_HEADERS,
        )
        assert status_response.status_code == 200
        completed = status_response.json()
        assert completed["phase"] == "completed"
        evidence = completed["evidence"]
        assert evidence["stream_id"] == str(stream_id)
        assert evidence["sequence"] == 1
        assert evidence["snapshot_id"] == str(refreshed.snapshot.snapshot_id)
        assert evidence["state_fingerprint"] == refreshed.state_fingerprint
        assert evidence["active_package"] == ACTIVE_PACKAGE

        action_now_ms = int(time.time() * 1000)
        command = AndroidActionCommand(
            action_id=uuid4(),
            issued_at_ms=action_now_ms,
            deadline_at_ms=action_now_ms + 30_000,
            precondition=ObservationPrecondition(
                expected_stream_id=UUID(evidence["stream_id"]),
                minimum_sequence=evidence["sequence"],
                expected_state_fingerprint=evidence["state_fingerprint"],
                expected_active_package=evidence["active_package"],
                maximum_age_ms=2_000,
            ),
            operation=OpenAppOperation(package_name=ACTIVE_PACKAGE),
            verification=AndroidVerificationPolicy(
                predicates=[
                    ActivePackageEqualsPredicate(package_name=ACTIVE_PACKAGE)
                ]
            ),
        )
        dispatch = client.post(
            f"/v1/devices/{device_id}/actions",
            headers=OPERATOR_HEADERS,
            json=command.model_dump(mode="json"),
        )
        assert dispatch.status_code == 202
        action_envelope = ProtocolEnvelope.model_validate_json(websocket.receive_text())
        delivered_command = AndroidActionCommand.model_validate(action_envelope.payload)
        assert action_envelope.type == "device.action_command"
        assert delivered_command.precondition == command.precondition

        rejection = ProtocolEnvelope.create(
            message_type="device.action_command_ack",
            device_id=device_id,
            correlation_id=action_envelope.message_id,
            payload=DeviceActionCommandAckPayload(
                command_id=command.command_id,
                action_id=command.action_id,
                status="rejected",
                received_at_ms=int(time.time() * 1000),
                detail="test cleanup",
            ),
        )
        websocket.send_text(rejection.model_dump_json())
        _round_trip_heartbeat(websocket, device_id)


def test_cancelled_refresh_ignores_late_ack_and_observation(
    client: TestClient,
) -> None:
    device_id = uuid4()
    stream_id = uuid4()
    now_ms = int(time.time() * 1000)

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(websocket, device_id)
        initial_envelope, initial = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=0,
            snapshot_id=uuid4(),
            captured_at_ms=now_ms,
        )
        _send_observation(websocket, initial_envelope)

        created = _create_refresh(
            client,
            device_id=device_id,
            expected_fingerprint=initial.state_fingerprint,
        )
        request_id = UUID(str(created["request_id"]))
        DeviceObservationRefreshEnvelope.model_validate_json(websocket.receive_text())

        cancelled_response = client.post(
            f"/v1/devices/{device_id}/observation-refreshes/{request_id}/cancel",
            headers=OPERATOR_HEADERS,
            json={"reason": "fixture cancellation"},
        )
        assert cancelled_response.status_code == 202
        assert cancelled_response.json()["phase"] == "cancelled"

        _send_refresh_ack(
            websocket,
            device_id=device_id,
            request_id=request_id,
            status="accepted",
        )

        late_envelope, _ = _observation(
            device_id=device_id,
            stream_id=stream_id,
            sequence=1,
            snapshot_id=uuid4(),
            captured_at_ms=now_ms + 100,
            refresh_request_id=request_id,
        )
        late_ack = _send_observation(websocket, late_envelope)
        assert late_ack.status == "unchanged"

        final_response = client.get(
            f"/v1/devices/{device_id}/observation-refreshes/{request_id}",
            headers=OPERATOR_HEADERS,
        )
        assert final_response.status_code == 200
        final = final_response.json()
        assert final["phase"] == "cancelled"
        assert final["evidence"] is None
        assert final["detail"] == "fixture cancellation"
