from __future__ import annotations

from simorgh_core.devices.actions import (
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    OpenAppOperation,
)


class AndroidActionSemanticError(ValueError):
    """Raised when individually valid action fields form an unsafe command."""


def validate_dispatch_semantics(command: AndroidActionCommand) -> AndroidActionCommand:
    """Enforce cross-field invariants that must hold before broker ownership."""

    operation = command.operation
    if not isinstance(operation, OpenAppOperation):
        return command

    package_predicates = [
        predicate
        for predicate in command.verification.predicates
        if isinstance(predicate, ActivePackageEqualsPredicate)
    ]
    if not package_predicates:
        raise AndroidActionSemanticError(
            "open_app verification requires active_package_equals for the target package"
        )
    if any(
        predicate.package_name != operation.package_name
        for predicate in package_predicates
    ):
        raise AndroidActionSemanticError(
            "open_app active_package_equals predicates must match operation package_name"
        )
    return command
