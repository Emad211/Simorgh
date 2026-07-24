from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ActionKind(StrEnum):
    ANDROID_OPEN_APP = "android.open_app"
    ANDROID_TAP = "android.tap"
    ANDROID_TYPE_TEXT = "android.type_text"
    ANDROID_SWIPE = "android.swipe"
    ANDROID_BACK = "android.back"
    ANDROID_HOME = "android.home"
    ANDROID_WAIT = "android.wait"
    CONNECTOR_CALL = "connector.call"
    BROWSER_NAVIGATE = "browser.navigate"
    BROWSER_INTERACT = "browser.interact"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class VerificationStrategy(StrEnum):
    NONE = "none"
    UI_TREE = "ui_tree"
    SCREEN_VISION = "screen_vision"
    API_RESPONSE = "api_response"
    COMPOSITE = "composite"


class Postcondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    strategy: VerificationStrategy
    expected: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)


class Action(BaseModel):
    """A single versioned and auditable operation in an execution plan."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    kind: ActionKind
    target: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    idempotency_key: str | None = None
    postconditions: list[Postcondition] = Field(default_factory=list)
    max_attempts: int = Field(default=1, ge=1, le=5)


class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    schema_version: str = "1.0"
    objective: str
    locale: str = "fa-IR"
    actions: list[Action] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ui_tree: dict[str, Any] | None = None
    screenshot_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: UUID
    status: ExecutionStatus
    started_at: datetime
    finished_at: datetime | None = None
    attempts: int = Field(default=1, ge=1)
    observation: Observation | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class PlanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    status: ExecutionStatus
    actions: list[ActionResult]
    started_at: datetime
    finished_at: datetime | None = None
