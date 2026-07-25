from __future__ import annotations

import pytest

from simorgh_core.devices.action_capabilities import (
    CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
    OPEN_APP_EXECUTION_CAPABILITY,
    UnsupportedAndroidOperationError,
    missing_capabilities,
    requirement_for_operation,
)
from simorgh_core.devices.actions import OpenAppOperation, WaitOperation


def test_open_app_maps_to_executor_and_bounded_clock_capabilities() -> None:
    requirement = requirement_for_operation(
        OpenAppOperation(package_name="com.example.target")
    )

    assert requirement.operation_kind == "open_app"
    assert requirement.required_capabilities == frozenset(
        {
            OPEN_APP_EXECUTION_CAPABILITY,
            CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
        }
    )
    assert missing_capabilities(requirement, []) == tuple(
        sorted(
            {
                OPEN_APP_EXECUTION_CAPABILITY,
                CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
            }
        )
    )
    assert missing_capabilities(
        requirement,
        [
            OPEN_APP_EXECUTION_CAPABILITY,
            CORE_CLOCK_BOUNDED_ESTIMATE_CAPABILITY,
            "unrelated.capability.v1",
        ],
    ) == ()


def test_schema_operation_without_live_executor_has_no_dispatch_mapping() -> None:
    with pytest.raises(UnsupportedAndroidOperationError, match="no enabled execution"):
        requirement_for_operation(WaitOperation(duration_ms=250))
