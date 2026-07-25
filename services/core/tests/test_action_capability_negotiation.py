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
    WaitOperation,
)
from simorgh_core.devices.protocol import (
    DeviceActionCommandAckPayload,
    DeviceHeartbeatPayload,
    DeviceRegistrationPayload,
    ProtocolEnvelope,
)

DEVICE_HEADERS = {"Authorization": "Bearer test-device-token"}
OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}
TARGET_PACKAGE = "com.example.target"
REQUIRED_OPEN_APP_CAPABILITIES = sorted(
    {
        OPEN_APP_EXECUTION_CAPABILITY,
        CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
    }
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SIMORGH_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _registration(
    device_id: UUID,
    *,
    capabilities: list[str],
    fingerprint_suffix: str,
) -> ProtocolEnvelope:
    return ProtocolEnvelope.create(
        message_type="device.register",
        device_id=device_id,
        payload=DeviceRegistrationPayload(
            app_version="0.1.0",
            sdk_int=31,
            android_release="12",
            manufacturer="Samsung",
            model="SM-A536B",
            build_fingerprint=f"samsung/a53/capability-{fingerprint_suffix}",
            support_tier="FULL",
            capabilities=capabilities,
        ),
    )


def _register(
    websocket,
    device_id: UUID,
    *,
    capabilities: list[str],
    fingerprint_suffix: str,
) -> None:
    websocket.send_text(
        _registration(
            device_id,
            capabilities=capabilities,
            fingerprint_suffix=fingerprint_suffix,
        ).model_dump_json()
    )
    registered = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert registered.type == "device.registered"


def _open_app_command() -> AndroidActionCommand:
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


def _wait_command() -> AndroidActionCommand:
    now_ms = int(time.time() * 1000)
    return AndroidActionCommand(
        command_id=uuid4(),
        action_id=uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 60_000,
        precondition=ObservationPrecondition(),
        operation=WaitOperation(duration_ms=250),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
        ),
    )


def _dispatch(client: TestClient, device_id: UUID, command: AndroidActionCommand):
    return client.post(
        f"/v1/devices/{device_id}/actions",
        headers=OPERATOR_HEADERS,
        json=command.model_dump(mode="json"),
    )


def _get_action(client: TestClient, device_id: UUID, action_id: UUID):
    return client.get(
        f"/v1/devices/{device_id}/actions/{action_id}",
        headers=OPERATOR_HEADERS,
    )


def _assert_only_heartbeat_ack(websocket, device_id: UUID, sequence: int) -> None:
    heartbeat = ProtocolEnvelope.create(
        message_type="device.heartbeat",
        device_id=device_id,
        payload=DeviceHeartbeatPayload(sequence=sequence, app_uptime_ms=sequence * 100),
    )
    websocket.send_text(heartbeat.model_dump_json())
    received = ProtocolEnvelope.model_validate_json(websocket.receive_text())
    assert received.type == "device.heartbeat_ack"
    assert received.correlation_id == heartbeat.message_id


def _accept_command(
    websocket,
    *,
    device_id: UUID,
    command: AndroidActionCommand,
    command_envelope: ProtocolEnvelope,
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
            detail="capability fixture accepted",
        ),
    )
    websocket.send_text(acknowledgement.model_dump_json())
    _assert_only_heartbeat_ack(websocket, device_id, sequence=90)


def test_disconnected_device_fails_before_action_identity_is_reserved(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _open_app_command()

    response = _dispatch(client, device_id, command)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "device_not_connected",
        "message": "device is not connected",
        "operation_kind": "open_app",
        "required_capabilities": [],
        "missing_capabilities": [],
        "available_capabilities": [],
    }
    assert _get_action(client, device_id, command.action_id).status_code == 404


def test_missing_execution_capability_returns_typed_error_and_sends_no_command(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _open_app_command()
    capabilities = [
        "device.action_transport.v1",
        "android.action.contract.v1",
        CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
    ]

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(
            websocket,
            device_id,
            capabilities=capabilities,
            fingerprint_suffix="missing-open-app",
        )
        response = _dispatch(client, device_id, command)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "unsupported_device_capability"
        assert detail["operation_kind"] == "open_app"
        assert detail["required_capabilities"] == REQUIRED_OPEN_APP_CAPABILITIES
        assert detail["missing_capabilities"] == [OPEN_APP_EXECUTION_CAPABILITY]
        assert detail["available_capabilities"] == sorted(capabilities)
        _assert_only_heartbeat_ack(websocket, device_id, sequence=1)

    assert _get_action(client, device_id, command.action_id).status_code == 404


def test_missing_bounded_clock_capability_returns_typed_error_and_sends_no_command(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _open_app_command()
    capabilities = [
        "device.action_transport.v1",
        "android.action.contract.v1",
        OPEN_APP_EXECUTION_CAPABILITY,
    ]

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(
            websocket,
            device_id,
            capabilities=capabilities,
            fingerprint_suffix="missing-bounded-clock",
        )
        response = _dispatch(client, device_id, command)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "unsupported_device_capability"
        assert detail["operation_kind"] == "open_app"
        assert detail["required_capabilities"] == REQUIRED_OPEN_APP_CAPABILITIES
        assert detail["missing_capabilities"] == [
            CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY
        ]
        assert detail["available_capabilities"] == sorted(capabilities)
        _assert_only_heartbeat_ack(websocket, device_id, sequence=7)

    assert _get_action(client, device_id, command.action_id).status_code == 404


def test_same_identifiers_can_dispatch_after_device_registers_compatible_session(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _open_app_command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as incompatible:
        _register(
            incompatible,
            device_id,
            capabilities=["device.action_transport.v1"],
            fingerprint_suffix="incompatible",
        )
        assert _dispatch(client, device_id, command).status_code == 409
        _assert_only_heartbeat_ack(incompatible, device_id, sequence=2)

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as compatible:
        _register(
            compatible,
            device_id,
            capabilities=[
                "device.action_transport.v1",
                *REQUIRED_OPEN_APP_CAPABILITIES,
            ],
            fingerprint_suffix="compatible",
        )
        response = _dispatch(client, device_id, command)
        assert response.status_code == 202
        assert response.json()["phase"] == "delivered"
        envelope = ProtocolEnvelope.model_validate_json(compatible.receive_text())
        assert envelope.type == "device.action_command"
        assert envelope.payload == command.model_dump(mode="json")


def test_latest_replacement_session_capabilities_are_authoritative(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _open_app_command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as old_socket:
        _register(
            old_socket,
            device_id,
            capabilities=REQUIRED_OPEN_APP_CAPABILITIES,
            fingerprint_suffix="old-compatible",
        )

        with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as current_socket:
            _register(
                current_socket,
                device_id,
                capabilities=["device.action_transport.v1"],
                fingerprint_suffix="new-incompatible",
            )
            response = _dispatch(client, device_id, command)

            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "unsupported_device_capability"
            _assert_only_heartbeat_ack(current_socket, device_id, sequence=3)

    assert _get_action(client, device_id, command.action_id).status_code == 404


def test_pending_command_is_not_redelivered_to_downgraded_session(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _open_app_command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as first_socket:
        _register(
            first_socket,
            device_id,
            capabilities=REQUIRED_OPEN_APP_CAPABILITIES,
            fingerprint_suffix="before-downgrade",
        )
        response = _dispatch(client, device_id, command)
        assert response.status_code == 202
        first_envelope = ProtocolEnvelope.model_validate_json(first_socket.receive_text())
        assert first_envelope.type == "device.action_command"

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as downgraded:
        _register(
            downgraded,
            device_id,
            capabilities=["device.action_transport.v1"],
            fingerprint_suffix="after-downgrade",
        )
        _assert_only_heartbeat_ack(downgraded, device_id, sequence=4)

        current = _get_action(client, device_id, command.action_id)
        assert current.status_code == 200
        assert current.json()["phase"] == "delivered"
        assert current.json()["delivery_count"] == 1
        assert "was not redelivered" in current.json()["detail"]


def test_accepted_action_is_not_reexecuted_after_capability_downgrade(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _open_app_command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as first_socket:
        _register(
            first_socket,
            device_id,
            capabilities=REQUIRED_OPEN_APP_CAPABILITIES,
            fingerprint_suffix="accepted-before-downgrade",
        )
        assert _dispatch(client, device_id, command).status_code == 202
        command_envelope = ProtocolEnvelope.model_validate_json(first_socket.receive_text())
        _accept_command(
            first_socket,
            device_id=device_id,
            command=command,
            command_envelope=command_envelope,
        )

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as downgraded:
        _register(
            downgraded,
            device_id,
            capabilities=["device.action_transport.v1"],
            fingerprint_suffix="accepted-after-downgrade",
        )
        _assert_only_heartbeat_ack(downgraded, device_id, sequence=5)

        current = _get_action(client, device_id, command.action_id)
        assert current.status_code == 200
        assert current.json()["phase"] == "accepted"
        assert current.json()["delivery_count"] == 1
        assert "was not redelivered" in current.json()["detail"]


def test_schema_operation_without_live_executor_returns_typed_422(
    client: TestClient,
) -> None:
    device_id = uuid4()
    command = _wait_command()

    with client.websocket_connect("/v1/devices/ws", headers=DEVICE_HEADERS) as websocket:
        _register(
            websocket,
            device_id,
            capabilities=REQUIRED_OPEN_APP_CAPABILITIES,
            fingerprint_suffix="unsupported-operation",
        )
        response = _dispatch(client, device_id, command)

        assert response.status_code == 422
        assert response.json()["detail"] == {
            "code": "unsupported_operation",
            "message": "Android operation 'wait' is not enabled for Core dispatch",
            "operation_kind": "wait",
            "required_capabilities": [],
            "missing_capabilities": [],
            "available_capabilities": [],
        }
        _assert_only_heartbeat_ack(websocket, device_id, sequence=6)

    assert _get_action(client, device_id, command.action_id).status_code == 404
