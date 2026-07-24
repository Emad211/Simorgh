from __future__ import annotations

import hashlib
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
ObservationAckStatus = Literal["accepted", "unchanged", "duplicate", "stale"]
TruncationReason = Literal["node_limit", "depth_limit", "child_limit"]


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

    node_id: str = Field(min_length=24, max_length=24, pattern=r"^[0-9a-f]{24}$")
    parent_node_id: str | None = Field(
        default=None,
        min_length=24,
        max_length=24,
        pattern=r"^[0-9a-f]{24}$",
    )
    path: str = Field(min_length=1, max_length=512, pattern=r"^0(?:\.[0-9]+)*$")
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
    semantic_fingerprint: str = Field(
        min_length=24,
        max_length=24,
        pattern=r"^[0-9a-f]{24}$",
    )
    child_count: int = Field(ge=0)
    input_type: int = Field(ge=0)
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
    root_node_id: str | None = Field(
        default=None,
        min_length=24,
        max_length=24,
        pattern=r"^[0-9a-f]{24}$",
    )
    windows: list[AccessibilityWindowPayload] = Field(default_factory=list, max_length=100)
    nodes: list[AccessibilityNodePayload] = Field(default_factory=list, max_length=500)
    truncated: bool
    truncation_reasons: list[TruncationReason] = Field(default_factory=list, max_length=8)
    max_depth_observed: int = Field(ge=0, le=40)

    @model_validator(mode="after")
    def validate_tree(self) -> AccessibilitySnapshotPayload:
        if self.truncated != bool(self.truncation_reasons):
            raise ValueError("truncated must match the presence of truncation_reasons")
        if len(self.truncation_reasons) != len(set(self.truncation_reasons)):
            raise ValueError("truncation_reasons must be unique")

        node_by_id = {node.node_id: node for node in self.nodes}
        if len(node_by_id) != len(self.nodes):
            raise ValueError("node_id values must be unique within a snapshot")

        if not self.nodes:
            if self.root_node_id is not None:
                raise ValueError("empty snapshot cannot declare root_node_id")
            if self.max_depth_observed != 0:
                raise ValueError("empty snapshot must report max_depth_observed as zero")
            return self

        if self.root_node_id is None:
            raise ValueError("non-empty snapshot requires root_node_id")
        root = node_by_id.get(self.root_node_id)
        if root is None:
            raise ValueError("root_node_id must reference a node in the same snapshot")
        if root.parent_node_id is not None or root.depth != 0 or root.path != "0":
            raise ValueError("root node must have no parent, depth zero, and path 0")

        for node in self.nodes:
            if node.node_id == self.root_node_id:
                continue
            if node.parent_node_id is None:
                raise ValueError("every non-root node requires parent_node_id")
            parent = node_by_id.get(node.parent_node_id)
            if parent is None:
                raise ValueError("parent_node_id must reference a node in the same snapshot")
            if node.depth != parent.depth + 1:
                raise ValueError("node depth must be exactly one greater than parent depth")
            if not node.path.startswith(f"{parent.path}."):
                raise ValueError("node path must be a direct descendant of parent path")
            if len(node.path.split(".")) != len(parent.path.split(".")) + 1:
                raise ValueError("node path must add exactly one child segment")

        observed_depth = max(node.depth for node in self.nodes)
        if self.max_depth_observed != observed_depth:
            raise ValueError("max_depth_observed must equal the deepest transmitted node")
        return self


class DeviceObservationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream_id: UUID
    sequence: int = Field(ge=0)
    state_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    snapshot: AccessibilitySnapshotPayload

    @model_validator(mode="after")
    def validate_state_fingerprint(self) -> DeviceObservationPayload:
        expected = calculate_accessibility_state_fingerprint(self.snapshot)
        if not secrets_equal(self.state_fingerprint, expected):
            raise ValueError("state_fingerprint does not match canonical snapshot state")
        return self


class DeviceObservationAckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream_id: UUID
    sequence: int = Field(ge=0)
    snapshot_id: UUID
    status: ObservationAckStatus
    received_at_ms: int = Field(ge=0)


class DeviceErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1_000)


class _CanonicalDigest:
    """Length-prefixed, cross-language SHA-256 input writer."""

    def __init__(self, prefix: str) -> None:
        self._digest = hashlib.sha256()
        self._digest.update(prefix.encode("ascii"))

    def add_string(self, name: str, value: str | None) -> None:
        self._add_name(name)
        if value is None:
            self._digest.update(b"N;")
            return
        encoded = value.encode("utf-8")
        self._digest.update(b"S")
        self._digest.update(str(len(encoded)).encode("ascii"))
        self._digest.update(b":")
        self._digest.update(encoded)
        self._digest.update(b";")

    def add_int(self, name: str, value: int | None) -> None:
        self._add_name(name)
        if value is None:
            self._digest.update(b"N;")
            return
        self._digest.update(b"I")
        self._digest.update(str(value).encode("ascii"))
        self._digest.update(b";")

    def add_bool(self, name: str, value: bool) -> None:
        self._add_name(name)
        self._digest.update(b"B1;" if value else b"B0;")

    def hexdigest(self) -> str:
        return self._digest.hexdigest()

    def _add_name(self, name: str) -> None:
        self._digest.update(name.encode("ascii"))
        self._digest.update(b"=")


def calculate_accessibility_state_fingerprint(snapshot: AccessibilitySnapshotPayload) -> str:
    """Return the canonical state hash shared with the Android implementation."""

    digest = _CanonicalDigest("simorgh-accessibility-state-v1\n")
    digest.add_string("schema_version", snapshot.schema_version)
    digest.add_string("active_package", snapshot.active_package)
    digest.add_int("active_window_id", snapshot.active_window_id)
    digest.add_string("root_node_id", snapshot.root_node_id)
    digest.add_bool("truncated", snapshot.truncated)
    digest.add_int("max_depth_observed", snapshot.max_depth_observed)

    reasons = sorted(snapshot.truncation_reasons)
    digest.add_int("truncation_reason_count", len(reasons))
    for index, reason in enumerate(reasons):
        digest.add_int("truncation_reason_index", index)
        digest.add_string("truncation_reason", reason)

    windows = sorted(snapshot.windows, key=lambda window: (window.id, window.layer))
    digest.add_int("window_count", len(windows))
    for index, window in enumerate(windows):
        digest.add_int("window_index", index)
        digest.add_int("window_id", window.id)
        digest.add_int("window_type", window.type)
        digest.add_int("window_layer", window.layer)
        digest.add_bool("window_active", window.active)
        digest.add_bool("window_focused", window.focused)
        digest.add_bool("window_accessibility_focused", window.accessibility_focused)
        digest.add_string("window_title", window.title)
        digest.add_int("window_bounds_left", window.bounds.left)
        digest.add_int("window_bounds_top", window.bounds.top)
        digest.add_int("window_bounds_right", window.bounds.right)
        digest.add_int("window_bounds_bottom", window.bounds.bottom)
        digest.add_int("window_display_id", window.display_id)

    nodes = sorted(snapshot.nodes, key=lambda node: node.path)
    digest.add_int("node_count", len(nodes))
    for index, node in enumerate(nodes):
        digest.add_int("node_index", index)
        digest.add_string("node_id", node.node_id)
        digest.add_string("node_parent_node_id", node.parent_node_id)
        digest.add_string("node_path", node.path)
        digest.add_int("node_depth", node.depth)
        digest.add_int("node_window_id", node.window_id)
        digest.add_string("node_package_name", node.package_name)
        digest.add_string("node_class_name", node.class_name)
        digest.add_string("node_view_id", node.view_id)
        digest.add_string("node_text", node.text)
        digest.add_string("node_content_description", node.content_description)
        digest.add_string("node_hint_text", node.hint_text)
        digest.add_string("node_state_description", node.state_description)
        digest.add_string("node_semantic_fingerprint", node.semantic_fingerprint)
        digest.add_int("node_bounds_left", node.bounds.left)
        digest.add_int("node_bounds_top", node.bounds.top)
        digest.add_int("node_bounds_right", node.bounds.right)
        digest.add_int("node_bounds_bottom", node.bounds.bottom)
        digest.add_int("node_child_count", node.child_count)
        digest.add_int("node_input_type", node.input_type)
        digest.add_bool("node_clickable", node.clickable)
        digest.add_bool("node_long_clickable", node.long_clickable)
        digest.add_bool("node_focusable", node.focusable)
        digest.add_bool("node_focused", node.focused)
        digest.add_bool("node_editable", node.editable)
        digest.add_bool("node_scrollable", node.scrollable)
        digest.add_bool("node_enabled", node.enabled)
        digest.add_bool("node_selected", node.selected)
        digest.add_bool("node_checkable", node.checkable)
        digest.add_bool("node_checked", node.checked)
        digest.add_bool("node_visible_to_user", node.visible_to_user)
        digest.add_bool("node_accessibility_focused", node.accessibility_focused)
        digest.add_bool("node_password", node.password)
        digest.add_bool("node_heading", node.heading)

        actions = sorted(node.actions, key=lambda action: (action.id, action.label or ""))
        digest.add_int("node_action_count", len(actions))
        for action_index, action in enumerate(actions):
            digest.add_int("action_index", action_index)
            digest.add_int("action_id", action.id)
            digest.add_string("action_label", action.label)

    return digest.hexdigest()


def secrets_equal(left: str, right: str) -> bool:
    """Compare fixed-size lowercase hashes without data-dependent early exit."""

    return len(left) == len(right) and hashlib.sha256(left.encode()).digest() == hashlib.sha256(
        right.encode()
    ).digest()
