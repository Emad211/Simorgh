from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from simorgh_core.devices.action_semantics import (
    AndroidActionSemanticError,
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
    NodeAbsentPredicate,
    NodeExistsPredicate,
    ObservationPrecondition,
    ObservationReference,
    OpenAppOperation,
    PredicateEvidence,
    PredicateOutcome,
    SelectorResolutionEvidence,
    UiPredicatePayload,
)
from simorgh_core.devices.registry import StoredObservationEvidence

TARGET_PACKAGE = "com.example.target"
STREAM_ID = UUID("11111111-1111-1111-1111-111111111111")
SNAPSHOT_ID = UUID("22222222-2222-2222-2222-222222222222")
NODE_ID = "a" * 24
STATE_FINGERPRINT = "b" * 64
CAPTURED_AT_MS = 10_000


def _reference() -> ObservationReference:
    return ObservationReference(
        stream_id=STREAM_ID,
        sequence=7,
        snapshot_id=SNAPSHOT_ID,
        state_fingerprint=STATE_FINGERPRINT,
        captured_at_ms=CAPTURED_AT_MS,
        active_package=TARGET_PACKAGE,
    )


def _stored_evidence() -> StoredObservationEvidence:
    reference = _reference()
    return StoredObservationEvidence(
        message_id=uuid4(),
        session_id=uuid4(),
        received_at_ms=CAPTURED_AT_MS + 10,
        stream_id=reference.stream_id,
        sequence=reference.sequence,
        snapshot_id=reference.snapshot_id,
        state_fingerprint=reference.state_fingerprint,
        captured_at_ms=reference.captured_at_ms,
        active_package=reference.active_package,
    )


def _selector() -> AndroidNodeSelector:
    return AndroidNodeSelector(
        package_name=TARGET_PACKAGE,
        view_id=f"{TARGET_PACKAGE}:id/item_42",
    )


def _command(predicates: list[UiPredicatePayload]) -> AndroidActionCommand:
    return AndroidActionCommand(
        action_id=uuid4(),
        issued_at_ms=9_000,
        deadline_at_ms=20_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(predicates=predicates),
    )


def _active_package_evidence() -> PredicateEvidence:
    return PredicateEvidence(
        kind="active_package_equals",
        outcome=PredicateOutcome.SATISFIED,
        detail=f"active package={TARGET_PACKAGE} expected={TARGET_PACKAGE}",
    )


def _resolved_node_evidence(kind: str) -> PredicateEvidence:
    return PredicateEvidence(
        kind=kind,
        outcome=PredicateOutcome.SATISFIED,
        detail="target node resolved",
        resolution=SelectorResolutionEvidence(
            outcome="resolved",
            selected_node_id=NODE_ID,
            selected_path="0.1",
            selected_score=240,
            score_margin=80,
        ),
    )


def _not_found_node_evidence() -> PredicateEvidence:
    return PredicateEvidence(
        kind="node_absent",
        outcome=PredicateOutcome.SATISFIED,
        detail="target node is absent",
        resolution=SelectorResolutionEvidence(outcome="not_found"),
    )


def _result(
    *,
    command: AndroidActionCommand,
    predicates: list[PredicateEvidence],
) -> AndroidActionResult:
    reference = _reference()
    return AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.SUCCEEDED,
        failure_code=ActionFailureCode.NONE,
        started_at_ms=10_000,
        finished_at_ms=10_001,
        attempts=0,
        before_observation=reference,
        after_observation=reference,
        predicates=predicates,
        detail="already satisfied fixture",
    )


def _validate(command: AndroidActionCommand, result: AndroidActionResult) -> AndroidActionResult:
    evidence = _stored_evidence()
    return validate_result_semantics(
        command=command,
        result=result,
        before_evidence=evidence,
        after_evidence=evidence,
    )


def test_successful_node_exists_requires_resolved_selected_node_evidence() -> None:
    command = _command(
        [
            ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE),
            NodeExistsPredicate(selector=_selector()),
        ]
    )
    result = _result(
        command=command,
        predicates=[
            _active_package_evidence(),
            _resolved_node_evidence("node_exists"),
        ],
    )

    assert _validate(command, result) is result


@pytest.mark.parametrize(
    "node_evidence, expected_message",
    [
        (
            PredicateEvidence(
                kind="node_exists",
                outcome=PredicateOutcome.SATISFIED,
                detail="claimed without selector resolution",
            ),
            "requires selector resolution",
        ),
        (
            PredicateEvidence(
                kind="node_exists",
                outcome=PredicateOutcome.SATISFIED,
                detail="resolved without selected identity",
                resolution=SelectorResolutionEvidence(outcome="resolved"),
            ),
            "requires selected node identity",
        ),
        (
            PredicateEvidence(
                kind="node_exists",
                outcome=PredicateOutcome.SATISFIED,
                detail="not found cannot prove existence",
                resolution=SelectorResolutionEvidence(outcome="not_found"),
            ),
            "requires resolved selector outcome",
        ),
    ],
)
def test_successful_node_exists_rejects_incomplete_resolution_evidence(
    node_evidence: PredicateEvidence,
    expected_message: str,
) -> None:
    command = _command(
        [
            ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE),
            NodeExistsPredicate(selector=_selector()),
        ]
    )
    result = _result(
        command=command,
        predicates=[_active_package_evidence(), node_evidence],
    )

    with pytest.raises(AndroidActionSemanticError, match=expected_message):
        _validate(command, result)


def test_predicate_evidence_order_must_match_command_policy() -> None:
    command = _command(
        [
            ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE),
            NodeExistsPredicate(selector=_selector()),
        ]
    )
    result = _result(
        command=command,
        predicates=[
            _resolved_node_evidence("node_exists"),
            _active_package_evidence(),
        ],
    )

    with pytest.raises(AndroidActionSemanticError, match="order does not match"):
        _validate(command, result)


def test_successful_node_absent_requires_not_found_resolution() -> None:
    command = _command(
        [
            ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE),
            NodeAbsentPredicate(selector=_selector()),
        ]
    )
    result = _result(
        command=command,
        predicates=[_active_package_evidence(), _not_found_node_evidence()],
    )

    assert _validate(command, result) is result


def test_successful_node_absent_rejects_resolved_node_identity() -> None:
    command = _command(
        [
            ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE),
            NodeAbsentPredicate(selector=_selector()),
        ]
    )
    result = _result(
        command=command,
        predicates=[
            _active_package_evidence(),
            PredicateEvidence(
                kind="node_absent",
                outcome=PredicateOutcome.SATISFIED,
                detail="contradictory resolved node",
                resolution=SelectorResolutionEvidence(
                    outcome="resolved",
                    selected_node_id=NODE_ID,
                    selected_path="0.1",
                    selected_score=240,
                    score_margin=80,
                ),
            ),
        ],
    )

    with pytest.raises(AndroidActionSemanticError, match="requires not_found resolution"):
        _validate(command, result)


def test_active_package_evidence_cannot_smuggle_selector_resolution() -> None:
    command = _command(
        [ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)]
    )
    result = _result(
        command=command,
        predicates=[
            PredicateEvidence(
                kind="active_package_equals",
                outcome=PredicateOutcome.SATISFIED,
                detail="package evidence with irrelevant node",
                resolution=SelectorResolutionEvidence(
                    outcome="resolved",
                    selected_node_id=NODE_ID,
                    selected_path="0.1",
                    selected_score=240,
                    score_margin=80,
                ),
            )
        ],
    )

    with pytest.raises(AndroidActionSemanticError, match="must not contain selector"):
        _validate(command, result)
