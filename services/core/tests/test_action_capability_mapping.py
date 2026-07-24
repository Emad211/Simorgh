from __future__ import annotations

import pytest

from simorgh_core.devices.action_capabilities import (
    OPEN_APP_EXECUTION_CAPABILITY,
    UnsupportedAndroidOperationError,
    missing_capabilities,
    requirement_for_operation,
)
from simorgh_core.devices.actions import OpenAppOperation, WaitOperation


def test_open_app_maps_to_one_versioned_execution_capability() -> None:
    requirement = requirement_for_operation(
        OpenAppOperation(package_name="com.example.target")
    )

    assert requirement.operation_kind == "open_app"
    assert requirement.required_capabilities == frozenset(
        {OPEN_APP_EXECUTION_CAPABILITY}
    )
    assert missing_capabilities(requirement, []) == (
        OPEN_APP_EXECUTION_CAPABILITY,
    )
    assert missing_capabilities(
        requirement,
        [OPEN_APP_EXECUTION_CAPABILITY, "unrelated.capability.v1"],
    ) == ()


def test_schema_operation_without_live_executor_has_no_dispatch_mapping() -> None:
    with pytest.raises(UnsupportedAndroidOperationError, match="no enabled execution"):
        requirement_for_operation(WaitOperation(duration_ms=250))
