from __future__ import annotations

import time
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL_VERSION: Literal["1.0"] = "1.0"

MessageType = Literal[
    "device.register",
    "device.registered",
    "device.heartbeat",
    "device.heartbeat_ack",
    "device.observation",
    "device.observation_ack",
    "device.error",
]
ObservationAckStatus = Literal["accepted", "duplicate", "stale"]


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


class ScreenBoundsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: int
    top: int
    right: int
    bottom: int

    @model_validator(mode="after")
    def validate_edges(self) -> ScreenBoundsPayload:
        if self.right < self.left or self.bottom < self.top:
            raise ValueError("screen bounds must have non-negative width and height")
        return self


class AccessibilityActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    label: str | None = Field(default=None, max_length=512)


class AccessibilityNodePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    parent_node_id: str | None = Field(default=None, max_length=128)
    path: str = Field(min_length=1, max_length=512)
    depth: int = Field(ge=0, le=40)
    window_id: int
    package_name: str | None = Field(default=None, max_length=512)
    class_name: str | None = Field(default=None, max_length=512)
    view_id: str | None = Field(default=None, max_length=512)
    text: str | None = Field(default=None, max_length=512)
    content_description: str | None = Field(default=None, max_length=512)
    hint_text: str | None = Field(default=None, max_length=512)
    state_description: str | None = Field(default=None, max_length=512)
    bounds: ScreenBoundsPayload
    semantic_fingerprint: str = Field(min_length=1, max_length=128)
    child_count: int = Field(ge=0)
    input_type: int
    clickable: bool
    long_clickable: bool
    focusable: bool
    focused: bool
    editable: bool
    scrollable: bool
    enabled: bool
    selected: bool
    checkable: bool
    checked: bool
    visible_to_user: bool
    accessibility_focused: bool
    password: bool
    heading: bool
    actions: list[AccessibilityActionPayload] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def validate_password_redaction(self) -> AccessibilityNodePayload:
        if self.password and any(
            value is not None
            for value in (
                self.text,
                self.content_description,
                self.hint_text,
                self.state_description,
            )
        ):
            raise ValueError("password node semantic text must be redacted")
        return self


class AccessibilityWindowPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    type: int
    layer: int
    active: bool
    focused: bool
    accessibility_focused: bool
    title: str | None = Field(default=None, max_length=512)
    bounds: ScreenBoundsPayload
    display_id: int | None = None


class AccessibilitySnapshotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    snapshot_id: UUID
    captured_at_ms: int = Field(ge=0)
    triggering_event_type: int | None = None
    active_package: str | None = Field(default=None, max_length=512)
    active_window_id: int | None = None
    root_node_id: str | None = Field(default=None, max_length=128)
    windows: list[AccessibilityWindowPayload] = Field(default_factory=list, max_length=100)
    nodes: list[AccessibilityNodePayload] = Field(default_factory=list, max_length=500)
    truncated: bool
    truncation_reasons: list[str] = Field(default_factory=list, max_length=8)
    max_depth_observed: int = Field(ge=0, le=40)

    @model_validator(mode="after")
    def validate_tree_links(self) -> AccessibilitySnapshotPayload:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node_id values must be unique within a snapshot")

        known_ids = set(node_ids)
        for node in self.nodes:
            if node.parent_node_id is not None and node.parent_node_id not in known_ids:
                raise ValueError("parent_node_id must reference a node in the same snapshot")

        if self.root_node_id is not None and self.root_node_id not in known_ids:
            raise ValueError("root_node_id must reference a node in the same snapshot")
        if not self.nodes and self.root_node_id is not None:
            raise ValueError("empty snapshot cannot declare root_node_id")
        if self.nodes and self.root_node_id is None:
            raise ValueError("non-empty snapshot requires root_node_id")
        return self


class DeviceObservationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_fingerprint: str = Field(min_length=1, max_length=128)
    snapshot: AccessibilitySnapshotPayload


class DeviceObservationAckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    status: ObservationAckStatus
    received_at_ms: int = Field(ge=0)


class DeviceErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1_000)
