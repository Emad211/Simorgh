from uuid import uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.devices.protocol import (
    AccessibilityNodePayload,
    AccessibilitySnapshotPayload,
    ScreenBoundsPayload,
)


def _node(**overrides: object) -> AccessibilityNodePayload:
    values: dict[str, object] = {
        "node_id": "root",
        "path": "0",
        "depth": 0,
        "window_id": 1,
        "bounds": ScreenBoundsPayload(left=0, top=0, right=100, bottom=100),
        "semantic_fingerprint": "fingerprint",
        "child_count": 0,
        "input_type": 0,
        "clickable": False,
        "long_clickable": False,
        "focusable": False,
        "focused": False,
        "editable": False,
        "scrollable": False,
        "enabled": True,
        "selected": False,
        "checkable": False,
        "checked": False,
        "visible_to_user": True,
        "accessibility_focused": False,
        "password": False,
        "heading": False,
        "actions": [],
    }
    values.update(overrides)
    return AccessibilityNodePayload.model_validate(values)


def test_password_node_rejects_semantic_text() -> None:
    with pytest.raises(ValidationError, match="password node semantic text must be redacted"):
        _node(password=True, text="123456")


def test_snapshot_rejects_unknown_parent() -> None:
    with pytest.raises(ValidationError, match="parent_node_id"):
        AccessibilitySnapshotPayload(
            snapshot_id=uuid4(),
            captured_at_ms=1,
            root_node_id="child",
            windows=[],
            nodes=[
                _node(
                    node_id="child",
                    path="0",
                    parent_node_id="missing",
                )
            ],
            truncated=False,
            truncation_reasons=[],
            max_depth_observed=0,
        )


def test_snapshot_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValidationError, match="node_id values must be unique"):
        AccessibilitySnapshotPayload(
            snapshot_id=uuid4(),
            captured_at_ms=1,
            root_node_id="root",
            windows=[],
            nodes=[
                _node(),
                _node(path="0.0"),
            ],
            truncated=False,
            truncation_reasons=[],
            max_depth_observed=1,
        )
