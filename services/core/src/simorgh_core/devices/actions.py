from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.devices.protocol import ScreenBoundsPayload

ACTION_SCHEMA_VERSION: Literal["1.0"] = "1.0"


class TextMatchMode(StrEnum):
    EXACT = "exact"
    CONTAINS = "contains"


class SelectorField(StrEnum):
    VIEW_ID = "view_id"
    TEXT = "text"
    CONTENT_DESCRIPTION = "content_description"
    CLASS_NAME = "class_name"
    PATH = "path"
    SEMANTIC_FINGERPRINT = "semantic_fingerprint"
    BOUNDS = "bounds"


class NodeCapability(StrEnum):
    CLICKABLE = "clickable"
    LONG_CLICKABLE = "long_clickable"
    EDITABLE = "editable"
    SCROLLABLE = "scrollable"
    CHECKABLE = "checkable"
    FOCUSABLE = "focusable"


class ScrollDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    FORWARD = "forward"
    BACKWARD = "backward"


class GlobalActionName(StrEnum):
    BACK = "back"
    HOME = "home"
    RECENTS = "recents"


class ActionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class ActionFailureCode(StrEnum):
    NONE = "none"
    INVALID_COMMAND = "invalid_command"
    EXPIRED = "expired"
    PRECONDITION_FAILED = "precondition_failed"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_AMBIGUOUS = "target_ambiguous"
    ACTION_REJECTED = "action_rejected"
    POSTCONDITION_FAILED = "postcondition_failed"
    OBSERVATION_TIMEOUT = "observation_timeout"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class PredicateOutcome(StrEnum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    INDETERMINATE = "indeterminate"


class TextCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=512)
    mode: TextMatchMode = TextMatchMode.EXACT
    case_sensitive: bool = False


class AndroidNodeSelector(BaseModel):
    """Deterministic selector evaluated against a fresh Accessibility snapshot."""

    model_config = ConfigDict(extra="forbid")

    package_name: str = Field(min_length=1, max_length=512)
    view_id: str | None = Field(default=None, min_length=1, max_length=512)
    text: TextCriterion | None = None
    content_description: TextCriterion | None = None
    class_name: str | None = Field(default=None, min_length=1, max_length=512)
    path: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        pattern=r"^0(?:\.[0-9]+)*$",
    )
    semantic_fingerprint: str | None = Field(
        default=None,
        min_length=24,
        max_length=24,
        pattern=r"^[0-9a-f]{24}$",
    )
    bounds: ScreenBoundsPayload | None = None
    required_fields: set[SelectorField] = Field(default_factory=set, max_length=7)
    required_capabilities: set[NodeCapability] = Field(default_factory=set, max_length=6)
    minimum_score: int = Field(default=80, ge=1, le=500)
    minimum_margin: int = Field(default=20, ge=0, le=500)

    @model_validator(mode="after")
    def validate_selector(self) -> AndroidNodeSelector:
        present_fields = {
            field
            for field, value in (
                (SelectorField.VIEW_ID, self.view_id),
                (SelectorField.TEXT, self.text),
                (SelectorField.CONTENT_DESCRIPTION, self.content_description),
                (SelectorField.CLASS_NAME, self.class_name),
                (SelectorField.PATH, self.path),
                (SelectorField.SEMANTIC_FINGERPRINT, self.semantic_fingerprint),
                (SelectorField.BOUNDS, self.bounds),
            )
            if value is not None
        }
        if not present_fields:
            raise ValueError("selector requires at least one identity field")
        missing_required = self.required_fields - present_fields
        if missing_required:
            raise ValueError(
                "required_fields reference selector fields without values: "
                + ", ".join(sorted(field.value for field in missing_required))
            )
        if not self.required_fields:
            strongest_available = next(
                (
                    field
                    for field in (
                        SelectorField.VIEW_ID,
                        SelectorField.SEMANTIC_FINGERPRINT,
                        SelectorField.TEXT,
                        SelectorField.CONTENT_DESCRIPTION,
                        SelectorField.PATH,
                        SelectorField.CLASS_NAME,
                        SelectorField.BOUNDS,
                    )
                    if field in present_fields
                ),
                None,
            )
            if strongest_available is not None:
                self.required_fields.add(strongest_available)
        return self


class ObservationPrecondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_stream_id: UUID | None = None
    minimum_sequence: int | None = Field(default=None, ge=0)
    expected_state_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_active_package: str | None = Field(default=None, min_length=1, max_length=512)
    maximum_age_ms: int = Field(default=2_000, ge=100, le=30_000)


class AndroidOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str


class OpenAppOperation(AndroidOperation):
    kind: Literal["open_app"] = "open_app"
    package_name: str = Field(min_length=1, max_length=512)
    uri: str | None = Field(default=None, min_length=1, max_length=4_096)


class ClickNodeOperation(AndroidOperation):
    kind: Literal["click_node"] = "click_node"
    selectors: list[AndroidNodeSelector] = Field(min_length=1, max_length=5)
    allow_gesture_fallback: bool = True


class SetTextOperation(AndroidOperation):
    kind: Literal["set_text"] = "set_text"
    selectors: list[AndroidNodeSelector] = Field(min_length=1, max_length=5)
    text: str = Field(max_length=10_000)


class ScrollNodeOperation(AndroidOperation):
    kind: Literal["scroll_node"] = "scroll_node"
    selectors: list[AndroidNodeSelector] = Field(min_length=1, max_length=5)
    direction: ScrollDirection
    amount: float = Field(default=0.7, gt=0, le=1)
    allow_gesture_fallback: bool = True


class GlobalActionOperation(AndroidOperation):
    kind: Literal["global_action"] = "global_action"
    action: GlobalActionName


class WaitOperation(AndroidOperation):
    kind: Literal["wait"] = "wait"
    duration_ms: int = Field(ge=50, le=10_000)


AndroidOperationPayload = Annotated[
    OpenAppOperation
    | ClickNodeOperation
    | SetTextOperation
    | ScrollNodeOperation
    | GlobalActionOperation
    | WaitOperation,
    Field(discriminator="kind"),
]


class UiPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str


class ActivePackageEqualsPredicate(UiPredicate):
    kind: Literal["active_package_equals"] = "active_package_equals"
    package_name: str = Field(min_length=1, max_length=512)


class NodeExistsPredicate(UiPredicate):
    kind: Literal["node_exists"] = "node_exists"
    selector: AndroidNodeSelector


class NodeAbsentPredicate(UiPredicate):
    kind: Literal["node_absent"] = "node_absent"
    selector: AndroidNodeSelector


class NodeTextEqualsPredicate(UiPredicate):
    kind: Literal["node_text_equals"] = "node_text_equals"
    selector: AndroidNodeSelector
    expected_text: str = Field(max_length=512)
    case_sensitive: bool = False


class NodeCheckedEqualsPredicate(UiPredicate):
    kind: Literal["node_checked_equals"] = "node_checked_equals"
    selector: AndroidNodeSelector
    expected_checked: bool


class NodeEnabledEqualsPredicate(UiPredicate):
    kind: Literal["node_enabled_equals"] = "node_enabled_equals"
    selector: AndroidNodeSelector
    expected_enabled: bool


UiPredicatePayload = Annotated[
    ActivePackageEqualsPredicate
    | NodeExistsPredicate
    | NodeAbsentPredicate
    | NodeTextEqualsPredicate
    | NodeCheckedEqualsPredicate
    | NodeEnabledEqualsPredicate,
    Field(discriminator="kind"),
]


class AndroidVerificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predicates: list[UiPredicatePayload] = Field(min_length=1, max_length=10)
    timeout_ms: int = Field(default=10_000, ge=250, le=30_000)
    stable_samples: int = Field(default=1, ge=1, le=3)


class AndroidActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = ACTION_SCHEMA_VERSION
    command_id: UUID = Field(default_factory=uuid4)
    action_id: UUID
    issued_at_ms: int = Field(ge=0)
    deadline_at_ms: int = Field(ge=0)
    precondition: ObservationPrecondition
    operation: AndroidOperationPayload
    verification: AndroidVerificationPolicy

    @model_validator(mode="after")
    def validate_deadline(self) -> AndroidActionCommand:
        if self.deadline_at_ms <= self.issued_at_ms:
            raise ValueError("deadline_at_ms must be greater than issued_at_ms")
        if self.deadline_at_ms - self.issued_at_ms > 120_000:
            raise ValueError("Android action command lifetime cannot exceed 120 seconds")
        return self


class ObservationReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream_id: UUID
    sequence: int = Field(ge=0)
    snapshot_id: UUID
    state_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    captured_at_ms: int = Field(ge=0)
    active_package: str | None = Field(default=None, max_length=512)


class SelectorCandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=24, max_length=24, pattern=r"^[0-9a-f]{24}$")
    path: str = Field(min_length=1, max_length=512)
    score: int = Field(ge=0)
    matched_signals: list[str] = Field(default_factory=list, max_length=32)


class SelectorResolutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["resolved", "not_found", "ambiguous", "invalid_selector"]
    selected_node_id: str | None = Field(
        default=None,
        min_length=24,
        max_length=24,
        pattern=r"^[0-9a-f]{24}$",
    )
    selected_path: str | None = Field(default=None, max_length=512)
    selected_score: int | None = Field(default=None, ge=0)
    score_margin: int | None = Field(default=None, ge=0)
    candidates: list[SelectorCandidateEvidence] = Field(default_factory=list, max_length=5)


class PredicateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=128)
    outcome: PredicateOutcome
    detail: str = Field(max_length=1_000)
    resolution: SelectorResolutionEvidence | None = None


class AndroidActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = ACTION_SCHEMA_VERSION
    command_id: UUID
    action_id: UUID
    outcome: ActionOutcome
    failure_code: ActionFailureCode = ActionFailureCode.NONE
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)
    attempts: int = Field(default=1, ge=0, le=5)
    before_observation: ObservationReference | None = None
    after_observation: ObservationReference | None = None
    resolution: SelectorResolutionEvidence | None = None
    predicates: list[PredicateEvidence] = Field(default_factory=list, max_length=10)
    detail: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_result(self) -> AndroidActionResult:
        if self.finished_at_ms < self.started_at_ms:
            raise ValueError("finished_at_ms cannot precede started_at_ms")
        if self.outcome == ActionOutcome.SUCCEEDED and self.failure_code != ActionFailureCode.NONE:
            raise ValueError("successful result cannot contain a failure code")
        if self.outcome != ActionOutcome.SUCCEEDED and self.failure_code == ActionFailureCode.NONE:
            raise ValueError("non-successful result requires a failure code")
        return self
