from __future__ import annotations

from dataclasses import dataclass

from simorgh_core.devices.actions import AndroidOperation, OpenAppOperation

OPEN_APP_EXECUTION_CAPABILITY = "android.open_app.execution.v1"


class UnsupportedAndroidOperationError(ValueError):
    """Raised when Core has no live execution-capability mapping for an operation."""

    def __init__(self, operation_kind: str) -> None:
        self.operation_kind = operation_kind
        super().__init__(
            f"Android operation {operation_kind!r} has no enabled execution capability"
        )


@dataclass(frozen=True, slots=True)
class AndroidActionCapabilityRequirement:
    operation_kind: str
    required_capabilities: frozenset[str]


def requirement_for_operation(
    operation: AndroidOperation,
) -> AndroidActionCapabilityRequirement:
    """Return the explicit versioned capability required for one live operation.

    This mapping is intentionally exhaustive only for operations whose side-effect executor is
    enabled. A contract type existing in the schema does not imply that Core may dispatch it.
    """

    if isinstance(operation, OpenAppOperation):
        return AndroidActionCapabilityRequirement(
            operation_kind=operation.kind,
            required_capabilities=frozenset({OPEN_APP_EXECUTION_CAPABILITY}),
        )

    raise UnsupportedAndroidOperationError(operation.kind)


def missing_capabilities(
    requirement: AndroidActionCapabilityRequirement,
    available_capabilities: set[str] | frozenset[str] | list[str],
) -> tuple[str, ...]:
    available = frozenset(available_capabilities)
    return tuple(sorted(requirement.required_capabilities - available))
