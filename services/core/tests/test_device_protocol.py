from uuid import uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.devices.protocol import (
    AccessibilityNodePayload,
    AccessibilitySnapshotPayload,
    DeviceObservationPayload,
    ScreenBoundsPayload,
    calculate_accessibility_state_fingerprint,
)

ROOT_ID = "1" * 24
SEMANTIC_ID = "2" * 24


def _node(**overrides: object) -> AccessibilityNodePayload:
    values: dict[str, object] = {
        "node_id": ROOT_ID,
        "path": "0",
        "depth": 0,
        "window_id": 1,
        "package_name": "com.example",
        "class_name": "android.widget.CheckBox",
        "text": "گزینه",
        "bounds": ScreenBoundsPayload(left=0, top=0, right=100, bottom=100),
        "semantic_fingerprint": SEMANTIC_ID,
        "child_count": 0,
        "input_type": 0,
        "clickable": True,
        "long_clickable": False,
        "focusable": True,
        "focused": False,
        "editable": False,
        "scrollable": False,
        "enabled": True,
        "selected": False,
        "checkable": True,
        "checked": False,
        "visible_to_user": True,
        "accessibility_focused": False,
        "password": False,
        "heading": False,
        "actions": [],
    }
    values.update(overrides)
    return AccessibilityNodePayload.model_validate(values)


def _snapshot(**overrides: object) -> AccessibilitySnapshotPayload:
    values: dict[str, object] = {
        "snapshot_id": uuid4(),
        "captured_at_ms": 1_000,
        "active_package": "com.example",
        "active_window_id": 1,
        "root_node_id": ROOT_ID,
        "windows": [],
        "nodes": [_node()],
        "truncated": False,
        "truncation_reasons": [],
        "max_depth_observed": 0,
    }
    values.update(overrides)
    return AccessibilitySnapshotPayload.model_validate(values)


def test_password_node_rejects_semantic_text() -> None:
    with pytest.raises(ValidationError, match="password node semantic text must be redacted"):
        _node(password=True, text="123456")


def test_snapshot_rejects_unknown_parent() -> None:
    child = _node(
        node_id="3" * 24,
        path="0.0",
        depth=1,
        parent_node_id="4" * 24,
    )

    with pytest.raises(ValidationError, match="parent_node_id"):
        _snapshot(nodes=[_node(child_count=1), child], max_depth_observed=1)


def test_snapshot_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValidationError, match="node_id values must be unique"):
        _snapshot(nodes=[_node(), _node()])


def test_snapshot_rejects_inconsistent_truncation_metadata() -> None:
    with pytest.raises(ValidationError, match="truncated must match"):
        _snapshot(truncated=True, truncation_reasons=[])


def test_snapshot_rejects_incorrect_observed_depth() -> None:
    child = _node(
        node_id="3" * 24,
        parent_node_id=ROOT_ID,
        path="0.0",
        depth=1,
    )
    root = _node(child_count=1)

    with pytest.raises(ValidationError, match="max_depth_observed"):
        _snapshot(nodes=[root, child], max_depth_observed=0)


def test_canonical_fingerprint_matches_android_golden_vector() -> None:
    snapshot = _snapshot()

    assert calculate_accessibility_state_fingerprint(snapshot) == (
        "dc012d2ab21c3ad4308036eeddbe2522be4ab900f2b54eb24771341d2c79a056"
    )


def test_observation_rejects_noncanonical_fingerprint() -> None:
    with pytest.raises(ValidationError, match="state_fingerprint"):
        DeviceObservationPayload(
            stream_id=uuid4(),
            sequence=0,
            state_fingerprint="0" * 64,
            snapshot=_snapshot(),
        )


def test_observation_accepts_canonical_fingerprint() -> None:
    snapshot = _snapshot()
    fingerprint = calculate_accessibility_state_fingerprint(snapshot)

    observation = DeviceObservationPayload(
        stream_id=uuid4(),
        sequence=0,
        state_fingerprint=fingerprint,
        snapshot=snapshot,
    )

    assert observation.state_fingerprint == fingerprint
