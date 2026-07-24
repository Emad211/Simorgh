from __future__ import annotations

import time
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION: Literal["1.0"] = "1.0"

MessageType = Literal[
    "device.register",
    "device.registered",
    "device.heartbeat",
    "device.heartbeat_ack",
    "device.error",
]


class ProtocolEnvelope(BaseModel):
    """Versioned message envelope shared by Simorgh Core and Android clients."""

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"] = PROTOCOL_VERSION
    message_id: UUID = Field(default_factory=uuid4)
    type: MessageType
    sent_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), ge=0)
    device_id: UUID | None = None
    correlation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        message_type: MessageType,
        device_id: UUID | None,
        payload: BaseModel | dict[str, Any] | None = None,
        correlation_id: UUID | None = None,
    ) -> ProtocolEnvelope:
        if isinstance(payload, BaseModel):
            payload_data = payload.model_dump(mode="json")
        else:
            payload_data = payload or {}
        return cls(
            type=message_type,
            device_id=device_id,
            correlation_id=correlation_id,
            payload=payload_data,
        )


class DeviceRegistrationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_version: str = Field(min_length=1, max_length=64)
    sdk_int: int = Field(ge=24, le=10_000)
    android_release: str = Field(min_length=1, max_length=64)
    manufacturer: str = Field(max_length=128)
    model: str = Field(max_length=128)
    build_fingerprint: str = Field(max_length=512)
    support_tier: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=256)


class DeviceRegisteredPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    server_time_ms: int = Field(ge=0)
    heartbeat_interval_seconds: int = Field(ge=5, le=300)


class DeviceHeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=0)
    app_uptime_ms: int = Field(ge=0)


class DeviceHeartbeatAckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=0)
    server_time_ms: int = Field(ge=0)


class DeviceErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1_000)
