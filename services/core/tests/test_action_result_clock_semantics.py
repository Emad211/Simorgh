from __future__ import annotations

from uuid import UUID

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
    AndroidVerificationPolicy,
    ObservationPrecondition,
    ObservationReference,
    OpenAppOperation,
    PredicateEvidence,
    PredicateOutcome,
)
from simorgh_core.devices.registry import StoredObservationEvidence

DEVICE_ID = UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = UUID("22222222-2222-2222-2222-222222222222")
STREAM_ID = UUID("33333333-3333-3333-3333-333333333333")
BEFORE_SNAPSHOT_ID = UUID("44444444-4444-4444-4444-444444444444")
AFTER_SNAPSHOT_ID = UUID("55555555-5555-5555-5555-555555555555")
COMMAND_ID = UUID("66666666-6666-6666-6666-666666666666")
ACTION_ID = UUID("77777777-7777-7777-7777-777777777777")
BEFORE_MESSAGE_ID = UUID("88888888-8888-8888-8888-888888888888")
AFTER_MESSAGE_ID = UUID("99999999-9999-9999-9999-999999999999")
SOURCE_PACKAGE = "com.example.source"
TARGET_PACKAGE = "com.example.target"
BEFORE_FINGERPRINT = "a" * 64
AFTER_FINGERPRINT = "b" * 64


def _command() -> AndroidActionCommand:
    return AndroidActionCommand(
        command_id=COMMAND_ID,
        action_id=ACTION_ID,
        issued_at_ms=1_000,
        deadline_at_ms=61_000,
        precondition=ObservationPrecondition(
            expected_stream_id=STREAM_ID,
            minimum_sequence=1,
            expected_state_fingerprint=BEFORE_FINGERPRINT,
            expected_active_package=SOURCE_PACKAGE,
            maximum_age_ms=30_000,
        ),
        operation=OpenAppOperation(package_name=TARGET_PACKAGE),
        verification=AndroidVerificationPolicy(
            predicates=[ActivePackageEqualsPredicate(package_name=TARGET_PACKAGE)],
            timeout_ms=10_000,
            stable_samples=1,
        ),
    )


def _reference(
    *,
    sequence: int,
    snapshot_id: UUID,
    fingerprint: str,
    captured_at_ms: int,
    active_package: str,
) -> ObservationReference:
    return ObservationReference(
        stream_id=STREAM_ID,
        sequence=sequence,
        snapshot_id=snapshot_id,
        state_fingerprint=fingerprint,
        captured_at_ms=captured_at_ms,
        active_package=active_package,
    )


def _evidence(
    *,
    message_id: UUID,
    sequence: int,
    snapshot_id: UUID,
    fingerprint: str,
    captured_at_ms: int,
    active_package: str,
    received_at_ms: int,
) -> StoredObservationEvidence:
    return StoredObservationEvidence(
        message_id=message_id,
        session_id=SESSION_ID,
        received_at_ms=received_at_ms,
        stream_id=STREAM_ID,
        sequence=sequence,
        snapshot_id=snapshot_id,
        state_fingerprint=fingerprint,
        captured_at_ms=captured_at_ms,
        active_package=active_package,
    )


def _result() -> AndroidActionResult:
    before = _reference(
        sequence=1,
        snapshot_id=BEFORE_SNAPSHOT_ID,
        fingerprint=BEFORE_FINGERPRINT,
        captured_at_ms=900_000,
        active_package=SOURCE_PACKAGE,
    )
    # The phone wall clock moved backwards after launch. Sequence and Core receive time still prove
    # this is the newer observation; captured_at_ms remains exact audit metadata only.
    after = _reference(
        sequence=2,
        snapshot_id=AFTER_SNAPSHOT_ID,
        fingerprint=AFTER_FINGERPRINT,
        captured_at_ms=10,
        active_package=TARGET_PACKAGE,
    )
    return AndroidActionResult(
        command_id=COMMAND_ID,
        action_id=ACTION_ID,
        outcome=ActionOutcome.SUCCEEDED,
        failure_code=ActionFailureCode.NONE,
        started_at_ms=2_000,
        finished_at_ms=2_100,
        attempts=1,
        before_observation=before,
        after_observation=after,
        predicates=[
            PredicateEvidence(
                kind="active_package_equals",
                outcome=PredicateOutcome.SATISFIED,
                detail=f"active package={TARGET_PACKAGE} expected={TARGET_PACKAGE}",
            )
        ],
        detail="verified despite Android wall-clock rollback",
    )


def test_wall_clock_rollback_does_not_invalidate_newer_core_acknowledged_evidence() -> None:
    result = _result()
    before_evidence = _evidence(
        message_id=BEFORE_MESSAGE_ID,
        sequence=1,
        snapshot_id=BEFORE_SNAPSHOT_ID,
        fingerprint=BEFORE_FINGERPRINT,
        captured_at_ms=900_000,
        active_package=SOURCE_PACKAGE,
        received_at_ms=10_000,
    )
    after_evidence = _evidence(
        message_id=AFTER_MESSAGE_ID,
        sequence=2,
        snapshot_id=AFTER_SNAPSHOT_ID,
        fingerprint=AFTER_FINGERPRINT,
        captured_at_ms=10,
        active_package=TARGET_PACKAGE,
        received_at_ms=10_100,
    )

    assert validate_result_semantics(
        command=_command(),
        result=result,
        before_evidence=before_evidence,
        after_evidence=after_evidence,
    ) == result


def test_core_receive_order_still_rejects_after_evidence_that_arrived_first() -> None:
    result = _result()
    before_evidence = _evidence(
        message_id=BEFORE_MESSAGE_ID,
        sequence=1,
        snapshot_id=BEFORE_SNAPSHOT_ID,
        fingerprint=BEFORE_FINGERPRINT,
        captured_at_ms=900_000,
        active_package=SOURCE_PACKAGE,
        received_at_ms=10_100,
    )
    after_evidence = _evidence(
        message_id=AFTER_MESSAGE_ID,
        sequence=2,
        snapshot_id=AFTER_SNAPSHOT_ID,
        fingerprint=AFTER_FINGERPRINT,
        captured_at_ms=10,
        active_package=TARGET_PACKAGE,
        received_at_ms=10_000,
    )

    with pytest.raises(
        AndroidActionSemanticError,
        match="after observation was acknowledged before before observation",
    ):
        validate_result_semantics(
            command=_command(),
            result=result,
            before_evidence=before_evidence,
            after_evidence=after_evidence,
        )
