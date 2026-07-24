from __future__ import annotations

from collections import Counter

from simorgh_core.devices.actions import (
    ActionOutcome,
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidActionResult,
    ObservationReference,
    OpenAppOperation,
    PredicateOutcome,
)
from simorgh_core.devices.protocol import DeviceObservationPayload


class AndroidActionSemanticError(ValueError):
    """Raised when individually valid action fields form an unsafe command or result."""


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


def validate_result_semantics(
    *,
    command: AndroidActionCommand,
    result: AndroidActionResult,
    latest_observation: DeviceObservationPayload | None,
) -> AndroidActionResult:
    """Verify device-reported result evidence against the original command and Core state."""

    if result.command_id != command.command_id:
        raise AndroidActionSemanticError("result command_id does not match the original command")
    if result.action_id != command.action_id:
        raise AndroidActionSemanticError("result action_id does not match the original action")

    operation = command.operation
    if not isinstance(operation, OpenAppOperation):
        return result

    if result.attempts not in {0, 1}:
        raise AndroidActionSemanticError("open_app result attempts must be zero or one")
    if result.outcome != ActionOutcome.SUCCEEDED:
        return result

    before = result.before_observation
    after = result.after_observation
    if before is None or after is None:
        raise AndroidActionSemanticError(
            "successful open_app result requires before and after observation evidence"
        )

    _validate_before_reference(command=command, before=before)

    if after.active_package != operation.package_name:
        raise AndroidActionSemanticError(
            "successful open_app after observation must show the target package"
        )

    expected_kinds = Counter(predicate.kind for predicate in command.verification.predicates)
    actual_kinds = Counter(evidence.kind for evidence in result.predicates)
    if actual_kinds != expected_kinds:
        raise AndroidActionSemanticError(
            "successful open_app predicate evidence does not match the verification policy"
        )
    if any(
        evidence.outcome != PredicateOutcome.SATISFIED
        for evidence in result.predicates
    ):
        raise AndroidActionSemanticError(
            "successful open_app requires every predicate outcome to be satisfied"
        )

    package_evidence_count = actual_kinds["active_package_equals"]
    if package_evidence_count < 1:
        raise AndroidActionSemanticError(
            "successful open_app result lacks satisfied target-package evidence"
        )

    if result.attempts == 0:
        if before != after:
            raise AndroidActionSemanticError(
                "zero-attempt open_app success requires identical before and after evidence"
            )
    else:
        _require_newer_after_reference(before=before, after=after)

    if latest_observation is None:
        raise AndroidActionSemanticError(
            "Core has no current observation to verify the successful open_app result"
        )
    _require_reference_matches_observation(
        reference=after,
        observation=latest_observation,
    )
    return result


def _validate_before_reference(
    *,
    command: AndroidActionCommand,
    before: ObservationReference,
) -> None:
    precondition = command.precondition
    if (
        precondition.expected_stream_id is not None
        and before.stream_id != precondition.expected_stream_id
    ):
        raise AndroidActionSemanticError(
            "result before observation violates expected_stream_id"
        )
    if (
        precondition.minimum_sequence is not None
        and before.sequence < precondition.minimum_sequence
    ):
        raise AndroidActionSemanticError(
            "result before observation violates minimum_sequence"
        )
    if (
        precondition.expected_state_fingerprint is not None
        and before.state_fingerprint != precondition.expected_state_fingerprint
    ):
        raise AndroidActionSemanticError(
            "result before observation violates expected_state_fingerprint"
        )
    if (
        precondition.expected_active_package is not None
        and before.active_package != precondition.expected_active_package
    ):
        raise AndroidActionSemanticError(
            "result before observation violates expected_active_package"
        )


def _require_newer_after_reference(
    *,
    before: ObservationReference,
    after: ObservationReference,
) -> None:
    if after.captured_at_ms < before.captured_at_ms:
        raise AndroidActionSemanticError(
            "one-attempt open_app after observation cannot predate before observation"
        )
    if after.stream_id == before.stream_id and after.sequence <= before.sequence:
        raise AndroidActionSemanticError(
            "one-attempt open_app requires a newer after-observation sequence"
        )
    if after == before:
        raise AndroidActionSemanticError(
            "one-attempt open_app requires distinct after observation evidence"
        )


def _require_reference_matches_observation(
    *,
    reference: ObservationReference,
    observation: DeviceObservationPayload,
) -> None:
    snapshot = observation.snapshot
    mismatches: list[str] = []
    if reference.stream_id != observation.stream_id:
        mismatches.append("stream_id")
    if reference.sequence != observation.sequence:
        mismatches.append("sequence")
    if reference.snapshot_id != snapshot.snapshot_id:
        mismatches.append("snapshot_id")
    if reference.state_fingerprint != observation.state_fingerprint:
        mismatches.append("state_fingerprint")
    if reference.captured_at_ms != snapshot.captured_at_ms:
        mismatches.append("captured_at_ms")
    if reference.active_package != snapshot.active_package:
        mismatches.append("active_package")

    if mismatches:
        raise AndroidActionSemanticError(
            "successful open_app after observation does not match Core state: "
            + ", ".join(mismatches)
        )
