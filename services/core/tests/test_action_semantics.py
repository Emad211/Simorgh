from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from simorgh_core.app import app
from simorgh_core.config import get_settings
from simorgh_core.devices.action_semantics import (
    AndroidActionSemanticError,
    validate_dispatch_semantics,
    validate_result_semantics,
)
from simorgh_core.devices.actions import (
    ActionFailureCode,
    ActionOutcome,
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidActionResult,
    AndroidNodeSelector,
    AndroidVerificationPolicy,
    NodeExistsPredicate,
    ObservationPrecondition,
    ObservationReference,
    OpenAppOperation,
    PredicateEvidence,
    PredicateOutcome,
)
from simorgh_core.devices.protocol import (
    AccessibilitySnapshotPayload,
    DeviceObservationPayload,
    calculate_accessibility_state_fingerprint,
)
from simorgh_core.devices.registry import StoredObservationEvidence

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
        verification=AndroidVerificationPolicy(predicates=predicates),  # type: ignore[arg-type]
    )


def _observation(
    *,
    active_package: str = TARGET_PACKAGE,
    stream_id: UUID | None = None,
    sequence: int = 7,
    captured_at_ms: int = 2_000,
) -> DeviceObservationPayload:
    snapshot = AccessibilitySnapshotPayload(
        snapshot_id=uuid4(),
        captured_at_ms=captured_at_ms,
        active_package=active_package,
        active_window_id=None,
        root_node_id=None,
        windows=[],
        nodes=[],
        truncated=False,
        truncation_reasons=[],
        max_depth_observed=0,
    )
    return DeviceObservationPayload(
        stream_id=stream_id or uuid4(),
        sequence=sequence,
        state_fingerprint=calculate_accessibility_state_fingerprint(snapshot),
        snapshot=snapshot,
    )


def _reference(observation: DeviceObservationPayload) -> ObservationReference:
    return ObservationReference(
        stream_id=observation.stream_id,
        sequence=observation.sequence,
        snapshot_id=observation.snapshot.snapshot_id,
        state_fingerprint=observation.state_fingerprint,
        captured_at_ms=observation.snapshot.captured_at_ms,
        active_package=observation.snapshot.active_package,
    )


def _evidence(
    observation: DeviceObservationPayload,
    *,
    received_at_ms: int | None = None,
) -> StoredObservationEvidence:
    snapshot = observation.snapshot
    return StoredObservationEvidence(
        message_id=uuid4(),
        session_id=uuid4(),
        received_at_ms=received_at_ms or snapshot.captured_at_ms + 10,
        stream_id=observation.stream_id,
        sequence=observation.sequence,
        snapshot_id=snapshot.snapshot_id,
        state_fingerprint=observation.state_fingerprint,
        captured_at_ms=snapshot.captured_at_ms,
        active_package=snapshot.active_package,
    )


def _success_result(
    *,
    command: AndroidActionCommand,
    before: ObservationReference,
    after: ObservationReference,
    attempts: int = 0,
) -> AndroidActionResult:
    return AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.SUCCEEDED,
        failure_code=ActionFailureCode.NONE,
        started_at_ms=2_000,
        finished_at_ms=2_010,
        attempts=attempts,
        before_observation=before,
        after_observation=after,
        predicates=[
            PredicateEvidence(
                kind="active_package_equals",
                outcome=PredicateOutcome.SATISFIED,
                detail=f"active package={TARGET_PACKAGE} expected={TARGET_PACKAGE}",
            )
        ],
        detail="fixture success",
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


def test_zero_attempt_success_matches_known_core_observation() -> None:
    command = _command(
        predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
    )
    observation = _observation()
    reference = _reference(observation)
    evidence = _evidence(observation)
    result = _success_result(
        command=command,
        before=reference,
        after=reference,
        attempts=0,
    )

    assert validate_result_semantics(
        command=command,
        result=result,
        before_evidence=evidence,
        after_evidence=evidence,
    ) is result


@pytest.mark.parametrize(
    "mutation, expected_message",
    [
        ("missing_after", "requires before and after"),
        ("wrong_package", "must show the target package"),
        ("missing_predicates", "does not match the verification policy"),
        ("unsatisfied", "every predicate outcome"),
        ("unknown_before", "before observation is not in Core acknowledged history"),
        ("unknown_after", "after observation is not in Core acknowledged history"),
        ("mismatched_after", "after observation does not match Core evidence"),
    ],
)
def test_successful_open_app_result_rejects_unverifiable_evidence(
    mutation: str,
    expected_message: str,
) -> None:
    command = _command(
        predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
    )
    observation = _observation()
    reference = _reference(observation)
    evidence = _evidence(observation)
    result = _success_result(
        command=command,
        before=reference,
        after=reference,
        attempts=0,
    )
    before_evidence: StoredObservationEvidence | None = evidence
    after_evidence: StoredObservationEvidence | None = evidence

    if mutation == "missing_after":
        result = result.model_copy(update={"after_observation": None})
        after_evidence = None
    elif mutation == "wrong_package":
        result = result.model_copy(
            update={
                "after_observation": reference.model_copy(
                    update={"active_package": OTHER_PACKAGE}
                )
            }
        )
    elif mutation == "missing_predicates":
        result = result.model_copy(update={"predicates": []})
    elif mutation == "unsatisfied":
        result = result.model_copy(
            update={
                "predicates": [
                    result.predicates[0].model_copy(
                        update={"outcome": PredicateOutcome.UNSATISFIED}
                    )
                ]
            }
        )
    elif mutation == "unknown_before":
        before_evidence = None
    elif mutation == "unknown_after":
        after_evidence = None
    elif mutation == "mismatched_after":
        after_evidence = _evidence(_observation(active_package=TARGET_PACKAGE))

    with pytest.raises(AndroidActionSemanticError, match=expected_message):
        validate_result_semantics(
            command=command,
            result=result,
            before_evidence=before_evidence,
            after_evidence=after_evidence,
        )


def test_one_attempt_open_app_success_requires_newer_after_evidence() -> None:
    command = _command(
        predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
    )
    observation = _observation()
    reference = _reference(observation)
    evidence = _evidence(observation)
    result = _success_result(
        command=command,
        before=reference,
        after=reference,
        attempts=1,
    )

    with pytest.raises(AndroidActionSemanticError, match="newer after-observation"):
        validate_result_semantics(
            command=command,
            result=result,
            before_evidence=evidence,
            after_evidence=evidence,
        )


def test_one_attempt_success_accepts_exact_older_history_entries() -> None:
    command = _command(
        predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
    )
    stream_id = uuid4()
    before_observation = _observation(
        active_package=OTHER_PACKAGE,
        stream_id=stream_id,
        sequence=7,
        captured_at_ms=2_000,
    )
    after_observation = _observation(
        active_package=TARGET_PACKAGE,
        stream_id=stream_id,
        sequence=8,
        captured_at_ms=2_100,
    )
    before = _reference(before_observation)
    after = _reference(after_observation)
    result = _success_result(
        command=command,
        before=before,
        after=after,
        attempts=1,
    )

    assert validate_result_semantics(
        command=command,
        result=result,
        before_evidence=_evidence(before_observation, received_at_ms=2_010),
        after_evidence=_evidence(after_observation, received_at_ms=2_110),
    ) is result


def test_one_attempt_success_rejects_reversed_core_ack_order() -> None:
    command = _command(
        predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
    )
    stream_id = uuid4()
    before_observation = _observation(
        active_package=OTHER_PACKAGE,
        stream_id=stream_id,
        sequence=7,
        captured_at_ms=2_000,
    )
    after_observation = _observation(
        active_package=TARGET_PACKAGE,
        stream_id=stream_id,
        sequence=8,
        captured_at_ms=2_100,
    )
    result = _success_result(
        command=command,
        before=_reference(before_observation),
        after=_reference(after_observation),
        attempts=1,
    )

    with pytest.raises(AndroidActionSemanticError, match="acknowledged before before"):
        validate_result_semantics(
            command=command,
            result=result,
            before_evidence=_evidence(before_observation, received_at_ms=3_000),
            after_evidence=_evidence(after_observation, received_at_ms=2_500),
        )


def test_non_successful_open_app_result_does_not_require_success_evidence() -> None:
    command = _command(
        predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
    )
    result = AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.BLOCKED,
        failure_code=ActionFailureCode.PRECONDITION_FAILED,
        started_at_ms=2_000,
        finished_at_ms=2_001,
        attempts=0,
        detail="precondition changed",
    )

    assert validate_result_semantics(
        command=command,
        result=result,
        before_evidence=None,
        after_evidence=None,
    ) is result
