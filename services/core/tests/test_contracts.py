from simorgh_core.contracts import (
    Action,
    ActionKind,
    ActionPlan,
    Postcondition,
    VerificationStrategy,
)


def test_action_plan_serializes_with_versioned_contract() -> None:
    plan = ActionPlan(
        objective="باز کردن اسلک",
        actions=[
            Action(
                kind=ActionKind.ANDROID_OPEN_APP,
                target="com.Slack",
                postconditions=[
                    Postcondition(
                        description="Slack is the foreground application",
                        strategy=VerificationStrategy.UI_TREE,
                        expected={"package": "com.Slack"},
                    )
                ],
            )
        ],
    )

    payload = plan.model_dump(mode="json")

    assert payload["schema_version"] == "1.0"
    assert payload["locale"] == "fa-IR"
    assert payload["actions"][0]["kind"] == "android.open_app"
    assert payload["actions"][0]["postconditions"][0]["strategy"] == "ui_tree"
