from __future__ import annotations

import time
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
    NodeExistsPredicate,
    ObservationPrecondition,
    ObservationReference,
    OpenAppOperation,
    PredicateEvidence,
    PredicateOutcome,
)
from simorgh_core.devices.registry import StoredObservationEvidence

TARGET_PACKAGE = "com.example.target"
TARGET_URI = "example://items/42"
STREAM_ID = UUID("11111111-1111-1111-1111-111111111111")
SNAPSHOT_ID = UUID("22222222-2222-2222-2222-222222222222")
FINGERPRINT = "a" * 64


def test_successful_deep_link_cannot_claim_zero_launch_attempts() -> None:
    now_ms = int(time.time() * 1000)
    command = AndroidActionCommand(
        action_id=uuid4(),
        issued_at_ms=now_ms,
        deadline_at_ms=now_ms + 30_000,
        precondition=ObservationPrecondition(),
        operation=OpenAppOperation(
            package_name=TARGET_PACKAGE,
            uri=TARGET_URI,
        ),
        verification=AndroidVerificationPolicy(
            predicates=[
                ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE),
                NodeExistsPredicate(
                    selector=AndroidNodeSelector(
                        package_name=TARGET_PACKAGE,
                        view_id=f"{TARGET_PACKAGE}:id/item_42",
                    )
                ),
            ]
        ),
    )
    reference = ObservationReference(
        stream_id=STREAM_ID,
        sequence=7,
        snapshot_id=SNAPSHOT_ID,
        state_fingerprint=FINGERPRINT,
        captured_at_ms=now_ms,
        active_package=TARGET_PACKAGE,
    )
    evidence = StoredObservationEvidence(
        message_id=uuid4(),
        session_id=uuid4(),
        received_at_ms=now_ms + 1,
        stream_id=reference.stream_id,
        sequence=reference.sequence,
        snapshot_id=reference.snapshot_id,
        state_fingerprint=reference.state_fingerprint,
        captured_at_ms=reference.captured_at_ms,
        active_package=reference.active_package,
    )
    result = AndroidActionResult(
        command_id=command.command_id,
        action_id=command.action_id,
        outcome=ActionOutcome.SUCCEEDED,
        failure_code=ActionFailureCode.NONE,
        started_at_ms=now_ms,
        finished_at_ms=now_ms + 1,
        attempts=0,
        before_observation=reference,
        after_observation=reference,
        predicates=[
            PredicateEvidence(
                kind="active_package_equals",
                outcome=PredicateOutcome.SATISFIED,
                detail="target package active",
            ),
            PredicateEvidence(
                kind="node_exists",
                outcome=PredicateOutcome.SATISFIED,
                detail="destination node exists",
            ),
        ],
    )

    with pytest.raises(AndroidActionSemanticError, match="requires one accepted launch"):
        validate_result_semantics(
            command=command,
            result=result,
            before_evidence=evidence,
            after_evidence=evidence,
        )
