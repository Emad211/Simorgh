from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
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
OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SIMORGH_OPERATOR_TOKEN", "test-operator-token")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _command(*, predicates: list[object]) -> AndroidActionCommand:
    now_ms = int(time.time() * 1000)
    return AndroidActionCommand(
        action_id=uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 30_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(predicates=predicates),
    )


def test_open_app_accepts_target_package_proof_with_additional_predicates() -> None:
    command = _command(
        predicates=[
            ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE),
            NodeExistsPredicate(
                selector=AndroidNodeSelector(
                    package_name=TARGET_PACKAGE,
                    view_id="com.example.target:id/home",
                )
            ),
        ]
    )

    assert validate_dispatch_semantics(command) is command


@pytest.mark.parametrize(
    "predicates, expected_message",
    [
        (
            [
                NodeExistsPredicate(
                    selector=AndroidNodeSelector(
                        package_name=TARGET_PACKAGE,
                        view_id="com.example.target:id/home",
                    )
                )
            ],
            "requires active_package_equals",
        ),
        (
            [ActivePackageEqualsPredicate(package_name=OTHER_PACKAGE)],
            "must match operation package_name",
        ),
    ],
)
def test_open_app_rejects_missing_or_conflicting_package_proof(
    predicates: list[object],
    expected_message: str,
) -> None:
    command = _command(predicates=predicates)

    with pytest.raises(AndroidActionSemanticError, match=expected_message):
        validate_dispatch_semantics(command)


def test_operator_api_rejects_semantically_invalid_open_app_before_broker(
    client: TestClient,
) -> None:
    command = _command(
        predicates=[ActivePackageEqualsPredicate(package_name=OTHER_PACKAGE)]
    )

    response = client.post(
        f"/v1/devices/{uuid4()}/actions",
        headers=OPERATOR_HEADERS,
        json=command.model_dump(mode="json"),
    )

    assert response.status_code == 400
    assert "must match operation package_name" in response.json()["detail"]
