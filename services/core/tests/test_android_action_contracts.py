from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from simorgh_core.devices.actions import (
    ActionFailureCode,
    ActionOutcome,
    ActivePackageEqualsPredicate,
    AndroidActionCommand,
    AndroidActionResult,
    AndroidNodeSelector,
    AndroidOperationPayload,
    AndroidVerificationPolicy,
    ClickNodeOperation,
    NodeCapability,
    NodeExistsPredicate,
    ObservationPrecondition,
    OpenAppOperation,
    SelectorField,
    TextCriterion,
)


def _selector(**overrides: object) -> AndroidNodeSelector:
    values: dict[str, object] = {
        "package_name": "com.example",
        "view_id": "com.example:id/continue_button",
        "class_name": "android.widget.Button",
        "required_capabilities": [NodeCapability.CLICKABLE],
    }
    values.update(overrides)
    return AndroidNodeSelector.model_validate(values)


def _command(operation: AndroidOperationPayload) -> AndroidActionCommand:
    return AndroidActionCommand(
        action_id=uuid4(),
        issued_at_ms=1_000,
        deadline_at_ms=11_000,
        precondition=ObservationPrecondition(
            expected_active_package="com.example",
            maximum_age_ms=2_000,
        ),
        operation=operation,
        verification=AndroidVerificationPolicy(
            predicates=[
                ActivePackageEqualsPredicate(package_name="com.example"),
            ]
        ),
    )


def test_selector_requires_identity_signal() -> None:
    with pytest.raises(ValidationError, match="identity field"):
        AndroidNodeSelector(package_name="com.example")


def test_selector_rejects_required_field_without_value() -> None:
    with pytest.raises(ValidationError, match="required_fields"):
        _selector(required_fields=[SelectorField.TEXT])


def test_selector_promotes_the_strongest_available_signal_to_required() -> None:
    selector = _selector(required_fields=[])

    assert selector.required_fields == {SelectorField.VIEW_ID}


def test_discriminated_operation_round_trip() -> None:
    operation = ClickNodeOperation(
        selectors=[_selector()],
        allow_gesture_fallback=True,
    )
    adapter = TypeAdapter(AndroidOperationPayload)

    encoded = adapter.dump_json(operation)
    decoded = adapter.validate_json(encoded)

    assert isinstance(decoded, ClickNodeOperation)
    assert decoded.selectors[0].view_id == "com.example:id/continue_button"


def test_open_app_command_is_schema_valid() -> None:
    command = _command(OpenAppOperation(package_name="com.slack"))

    assert command.schema_version == "1.0"
    assert command.operation.kind == "open_app"
    assert command.verification.predicates[0].kind == "active_package_equals"


def test_command_rejects_nonpositive_or_excessive_lifetime() -> None:
    operation = OpenAppOperation(package_name="com.example")
    verification = AndroidVerificationPolicy(
        predicates=[ActivePackageEqualsPredicate(package_name="com.example")]
    )

    with pytest.raises(ValidationError, match="greater than"):
        AndroidActionCommand(
            action_id=uuid4(),
            issued_at_ms=2_000,
            deadline_at_ms=2_000,
            precondition=ObservationPrecondition(),
            operation=operation,
            verification=verification,
        )

    with pytest.raises(ValidationError, match="120 seconds"):
        AndroidActionCommand(
            action_id=uuid4(),
            issued_at_ms=0,
            deadline_at_ms=120_001,
            precondition=ObservationPrecondition(),
            operation=operation,
            verification=verification,
        )


def test_text_and_node_predicate_are_bounded_and_typed() -> None:
    selector = _selector(
        text=TextCriterion(value="ادامه بده"),
        required_fields=[SelectorField.VIEW_ID],
    )
    policy = AndroidVerificationPolicy(
        predicates=[NodeExistsPredicate(selector=selector)],
        timeout_ms=5_000,
        stable_samples=2,
    )

    assert policy.predicates[0].kind == "node_exists"
    assert policy.stable_samples == 2


def test_action_result_enforces_failure_code_consistency() -> None:
    command_id = uuid4()
    action_id = uuid4()

    succeeded = AndroidActionResult(
        command_id=command_id,
        action_id=action_id,
        outcome=ActionOutcome.SUCCEEDED,
        started_at_ms=1,
        finished_at_ms=2,
    )
    assert succeeded.failure_code == ActionFailureCode.NONE

    with pytest.raises(ValidationError, match="requires a failure code"):
        AndroidActionResult(
            command_id=command_id,
            action_id=action_id,
            outcome=ActionOutcome.BLOCKED,
            started_at_ms=1,
            finished_at_ms=2,
        )

    blocked = AndroidActionResult(
        command_id=command_id,
        action_id=action_id,
        outcome=ActionOutcome.BLOCKED,
        failure_code=ActionFailureCode.TARGET_AMBIGUOUS,
        started_at_ms=1,
        finished_at_ms=2,
    )
    assert blocked.failure_code == ActionFailureCode.TARGET_AMBIGUOUS
