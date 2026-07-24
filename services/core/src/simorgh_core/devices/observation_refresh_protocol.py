from __future__ import annotations

import time
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.devices.protocol import PROTOCOL_VERSION

OBSERVATION_REFRESH_CAPABILITY: Literal[
    "android.observation.refresh.v1"
] = "android.observation.refresh.v1"
OBSERVATION_REFRESH_REQUEST_TYPE: Literal[
    "device.observation_refresh"
] = "device.observation_refresh"
OBSERVATION_REFRESH_ACK_TYPE: Literal[
    "device.observation_refresh_ack"
] = "device.observation_refresh_ack"

ObservationRefreshAckStatus = Literal[
    "accepted",
    "duplicate",
    "busy",
    "expired",
    "observer_unavailable",
    "rejected",
]


class DeviceObservationRefreshPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    timeout_ms: int = Field(ge=250, le=10_000)
    expected_state_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_active_package: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    reason: str = Field(default="operator requested fresh observation", max_length=1_000)


class DeviceObservationRefreshAckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: ObservationRefreshAckStatus
    received_at_ms: int = Field(ge=0)
    detail: str = Field(default="", max_length=1_000)


class _ObservationRefreshEnvelopeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"] = PROTOCOL_VERSION
    message_id: UUID = Field(default_factory=uuid4)
    sent_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), ge=0)
    device_id: UUID
    correlation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class DeviceObservationRefreshEnvelope(_ObservationRefreshEnvelopeBase):
    type: Literal["device.observation_refresh"] = OBSERVATION_REFRESH_REQUEST_TYPE

    @classmethod
    def create(
        cls,
        *,
        device_id: UUID,
        payload: DeviceObservationRefreshPayload,
        message_id: UUID | None = None,
    ) -> DeviceObservationRefreshEnvelope:
        request_id = message_id or payload.request_id
        if payload.request_id != request_id:
            raise ValueError("refresh payload request_id must equal envelope message_id")
        return cls(
            message_id=request_id,
            device_id=device_id,
            payload=payload.model_dump(mode="json"),
        )

    @model_validator(mode="after")
    def validate_request_identity(self) -> DeviceObservationRefreshEnvelope:
        payload = DeviceObservationRefreshPayload.model_validate(self.payload)
        if payload.request_id != self.message_id:
            raise ValueError("refresh request_id must equal envelope message_id")
        if self.correlation_id is not None:
            raise ValueError("refresh request envelope cannot declare correlation_id")
        return self


class DeviceObservationRefreshAckEnvelope(_ObservationRefreshEnvelopeBase):
    type: Literal["device.observation_refresh_ack"] = OBSERVATION_REFRESH_ACK_TYPE

    @classmethod
    def create(
        cls,
        *,
        device_id: UUID,
        request_envelope_id: UUID,
        payload: DeviceObservationRefreshAckPayload,
    ) -> DeviceObservationRefreshAckEnvelope:
        if payload.request_id != request_envelope_id:
            raise ValueError("refresh ACK request_id must equal correlation_id")
        return cls(
            device_id=device_id,
            correlation_id=request_envelope_id,
            payload=payload.model_dump(mode="json"),
        )

    @model_validator(mode="after")
    def validate_ack_identity(self) -> DeviceObservationRefreshAckEnvelope:
        payload = DeviceObservationRefreshAckPayload.model_validate(self.payload)
        if self.correlation_id is None:
            raise ValueError("refresh ACK requires correlation_id")
        if payload.request_id != self.correlation_id:
            raise ValueError("refresh ACK request_id must equal correlation_id")
        return self
