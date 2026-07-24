from __future__ import annotations

import time
from uuid import uuid4

import pytest

from simorgh_core.devices.action_semantics import (
    AndroidActionSemanticError,
    validate_dispatch_semantics,
)
from simorgh_core.devices.actions import (
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidNodeSelector,
    AndroidVerificationPolicy,
    NodeExistsPredicate,
    ObservationPrecondition,
    OpenAppOperation,
)

TARGET_PACKAGE = "com.example.target"
OTHER_PACKAGE = "com.example.other"
TARGET_URI = "example://items/42"


def _command(
    *,
    uri: str | None,
    include_node: bool,
    node_package: str = TARGET_PACKAGE,
) -> AndroidActionCommand:
    now_ms = int(time.time() * 1000)
    predicates: list[object] = [
        ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)
    ]
    if include_node:
        predicates.append(
            NodeExistsPredicate(
                selector=AndroidNodeSelector(
                    package_name=node_package,
                    view_id=f"{node_package}:id/item_42",
                )
            )
        )
    return AndroidActionCommand(
        action_id=uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 30_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE, uri=uri),
        verification=AndroidVerificationPolicy(
            predicates=predicates,  # type: ignore[arg-type]
        ),
    )


def test_front_door_open_can_use_target_package_as_the_complete_goal() -> None:
    command = _command(uri=None, include_node=False)

    assert validate_dispatch_semantics(command) is command


def test_deep_link_requires_a_target_package_destination_predicate() -> None:
    command = _command(uri=TARGET_URI, include_node=False)

    with pytest.raises(AndroidActionSemanticError, match="requires a target-package node"):
        validate_dispatch_semantics(command)


def test_deep_link_accepts_explicit_target_destination_proof() -> None:
    command = _command(uri=TARGET_URI, include_node=True)

    assert validate_dispatch_semantics(command) is command


def test_open_app_rejects_node_proof_from_another_package() -> None:
    command = _command(
        uri=TARGET_URI,
        include_node=True,
        node_package=OTHER_PACKAGE,
    )

    with pytest.raises(AndroidActionSemanticError, match="must target operation package_name"):
        validate_dispatch_semantics(command)
