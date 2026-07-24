from __future__ import annotations

from collections import Counter

from simorgh_core.devices.actions import (
    ActionOutcome,
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidActionResult,
    NodeAbsentPredicate,
    NodeCheckedEqualsPredicate,
    NodeEnabledEqualsPredicate,
    NodeExistsPredicate,
    NodeTextEqualsPredicate,
    ObservationReference,
    OpenAppOperation,
    PredicateOutcome,
)
from simorgh_core.devices.registry import StoredObservationEvidence


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

    destination_predicates = [
        predicate
        for predicate in command.verification.predicates
        if isinstance(
            predicate,
            (
                NodeExistsPredicate,
                NodeAbsentPredicate,
                NodeTextEqualsPredicate,
                NodeCheckedEqualsPredicate,
                NodeEnabledEqualsPredicate,
            ),
        )
    ]
    if any(
        predicate.selector.package_name != operation.package_name
        for predicate in destination_predicates
    ):
        raise AndroidActionSemanticError(
            "open_app node predicates must target operation package_name"
        )
    if operation.uri is not None and not destination_predicates:
        raise AndroidActionSemanticError(
            "open_app with uri requires a target-package node predicate proving the destination"
        )
    return command


def validate_result_semantics(
    *,
    command: AndroidActionCommand,
    result: AndroidActionResult,
    before_evidence: StoredObservationEvidence | None,
    after_evidence: StoredObservationEvidence | None,
) -> AndroidActionResult:
    """Verify device-reported result evidence against the command and Core ACK history."""

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
    if operation.uri is not None and result.attempts == 0:
        raise AndroidActionSemanticError(
            "successful open_app with uri requires one accepted launch attempt"
        )

    before = result.before_observation
    after = result.after_observation
    if before is None or after is None:
        raise AndroidActionSemanticError(
            "successful open_app result requires before and after observation evidence"
        )

    _validate_before_reference(command=command, before=before)
    _require_known_observation(
        label="before",
        reference=before,
        evidence=before_evidence,
    )

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

    _require_known_observation(
        label="after",
        reference=after,
        evidence=after_evidence,
    )

    if (
        result.attempts == 1
        and before_evidence is not None
        and after_evidence is not None
        and after_evidence.received_at_ms < before_evidence.received_at_ms
    ):
        raise AndroidActionSemanticError(
            "one-attempt open_app after observation was acknowledged before before observation"
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


def _require_known_observation(
    *,
    label: str,
    reference: ObservationReference,
    evidence: StoredObservationEvidence | None,
) -> None:
    if evidence is None:
        raise AndroidActionSemanticError(
            f"successful open_app {label} observation is not in Core acknowledged history"
        )

    mismatches: list[str] = []
    if reference.stream_id != evidence.stream_id:
        mismatches.append("stream_id")
    if reference.sequence != evidence.sequence:
        mismatches.append("sequence")
    if reference.snapshot_id != evidence.snapshot_id:
        mismatches.append("snapshot_id")
    if reference.state_fingerprint != evidence.state_fingerprint:
        mismatches.append("state_fingerprint")
    if reference.captured_at_ms != evidence.captured_at_ms:
        mismatches.append("captured_at_ms")
    if reference.active_package != evidence.active_package:
        mismatches.append("active_package")

    if mismatches:
        raise AndroidActionSemanticError(
            f"successful open_app {label} observation does not match Core evidence: "
            + ", ".join(mismatches)
        )
