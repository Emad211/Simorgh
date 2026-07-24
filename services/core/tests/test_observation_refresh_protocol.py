from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.devices.observation_refresh_protocol import (
    OBSERVATION_REFRESH_ACK_TYPE,
    OBSERVATION_REFRESH_REQUEST_TYPE,
    DeviceObservationRefreshAckEnvelope,
    DeviceObservationRefreshAckPayload,
    DeviceObservationRefreshEnvelope,
    DeviceObservationRefreshPayload,
)


def test_request_envelope_round_trip_preserves_stable_identity() -> None:
    device_id = uuid4()
    request_id = uuid4()
    payload = DeviceObservationRefreshPayload(
        request_id=request_id,
        timeout_ms=5_000,
        expected_state_fingerprint="a" * 64,
        expected_active_package="com.example",
        reason="fixture refresh",
    )

    envelope = DeviceObservationRefreshEnvelope.create(
        device_id=device_id,
        payload=payload,
        message_id=request_id,
    )
    decoded = DeviceObservationRefreshEnvelope.model_validate_json(
        envelope.model_dump_json()
    )

    assert decoded.type == OBSERVATION_REFRESH_REQUEST_TYPE
    assert decoded.message_id == request_id
    assert decoded.device_id == device_id
    assert decoded.correlation_id is None
    assert DeviceObservationRefreshPayload.model_validate(decoded.payload) == payload


def test_request_rejects_payload_id_different_from_message_id() -> None:
    payload = DeviceObservationRefreshPayload(
        request_id=uuid4(),
        timeout_ms=5_000,
    )

    with pytest.raises(ValueError, match="must equal envelope message_id"):
        DeviceObservationRefreshEnvelope.create(
            device_id=uuid4(),
            payload=payload,
            message_id=uuid4(),
        )


def test_request_rejects_correlation_and_extra_payload_fields() -> None:
    device_id = uuid4()
    request_id = uuid4()
    raw = {
        "protocol_version": "1.0",
        "message_id": str(request_id),
        "type": OBSERVATION_REFRESH_REQUEST_TYPE,
        "sent_at_ms": 1_000,
        "device_id": str(device_id),
        "correlation_id": str(uuid4()),
        "payload": {
            "request_id": str(request_id),
            "timeout_ms": 5_000,
            "unknown": True,
        },
    }

    with pytest.raises(ValidationError):
        DeviceObservationRefreshEnvelope.model_validate(raw)


def test_ack_round_trip_is_correlated_to_request() -> None:
    device_id = uuid4()
    request_id = uuid4()
    payload = DeviceObservationRefreshAckPayload(
        request_id=request_id,
        status="accepted",
        received_at_ms=2_000,
        detail="capture accepted",
    )

    envelope = DeviceObservationRefreshAckEnvelope.create(
        device_id=device_id,
        request_envelope_id=request_id,
        payload=payload,
    )
    decoded = DeviceObservationRefreshAckEnvelope.model_validate_json(
        envelope.model_dump_json()
    )

    assert decoded.type == OBSERVATION_REFRESH_ACK_TYPE
    assert decoded.correlation_id == request_id
    assert DeviceObservationRefreshAckPayload.model_validate(decoded.payload) == payload


def test_ack_rejects_request_id_different_from_correlation() -> None:
    payload = DeviceObservationRefreshAckPayload(
        request_id=uuid4(),
        status="rejected",
        received_at_ms=2_000,
    )

    with pytest.raises(ValueError, match="must equal correlation_id"):
        DeviceObservationRefreshAckEnvelope.create(
            device_id=uuid4(),
            request_envelope_id=uuid4(),
            payload=payload,
        )


def test_timeout_and_expected_state_fields_are_strictly_bounded() -> None:
    request_id = uuid4()

    with pytest.raises(ValidationError):
        DeviceObservationRefreshPayload(
            request_id=request_id,
            timeout_ms=10_001,
        )
    with pytest.raises(ValidationError):
        DeviceObservationRefreshPayload(
            request_id=request_id,
            timeout_ms=5_000,
            expected_state_fingerprint="A" * 64,
        )
    with pytest.raises(ValidationError):
        DeviceObservationRefreshPayload(
            request_id=request_id,
            timeout_ms=5_000,
            expected_active_package="",
        )
