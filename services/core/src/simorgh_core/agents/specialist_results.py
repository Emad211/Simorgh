from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPECIALIST_PLAN_OUTPUT_CONTRACT: Literal[
    "simorgh.typed-plan.v1"
] = "simorgh.typed-plan.v1"
REPOSITORY_REPORT_OUTPUT_CONTRACT: Literal[
    "simorgh.repository-report.v1"
] = "simorgh.repository-report.v1"


class SpecialistPlanPayload(BaseModel):
    """Concrete Phase 1.3 proposal payload.

    Arbitrary dictionaries and raw model text are intentionally excluded.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["plan"] = "plan"
    summary: str = Field(min_length=1, max_length=4_000)
    steps: tuple[str, ...] = Field(default=(), max_length=256)
    unresolved_risks: tuple[str, ...] = Field(default=(), max_length=128)
    verification_requirements: tuple[str, ...] = Field(default=(), max_length=128)

    @field_validator(
        "summary",
        "steps",
        "unresolved_risks",
        "verification_requirements",
    )
    @classmethod
    def normalize_text(
        cls,
        value: str | tuple[str, ...],
    ) -> str | tuple[str, ...]:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("specialist plan summary cannot be empty")
            return normalized
        normalized_items = tuple(item.strip() for item in value)
        if any(not item or len(item) > 2_000 for item in normalized_items):
            raise ValueError("specialist plan items must be in 1..2000 characters")
        return normalized_items

    @model_validator(mode="after")
    def validate_unique_items(self) -> Self:
        for field_name in (
            "steps",
            "unresolved_risks",
            "verification_requirements",
        ):
            values = getattr(self, field_name)
            if len(set(values)) != len(values):
                raise ValueError(f"specialist plan {field_name} must be unique")
        return self


class RepositoryReportFinding(BaseModel):
    """One bounded, evidence-linked future repository-report finding."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    finding_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=4_000)
    evidence_references: tuple[str, ...] = Field(default=(), max_length=128)

    @field_validator("title", "summary")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("repository report text cannot be empty")
        return normalized

    @field_validator("evidence_references")
    @classmethod
    def validate_evidence_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item or len(item) > 2_048 for item in normalized):
            raise ValueError("repository report evidence references must be bounded")
        if len(set(normalized)) != len(normalized):
            raise ValueError("repository report evidence references must be unique")
        return normalized


class RepositoryReportPayload(BaseModel):
    """Strict schema authority for the later complete GitHub report workflow.

    Phase 1.7 registers this contract only so ``github.read`` context can carry an
    exact required output schema. No report executor, terminalizer, model workflow,
    or presentation surface is added before Phase 1.10.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["repository_report"] = "repository_report"
    repository: str = Field(
        min_length=3,
        max_length=201,
        pattern=r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$",
    )
    ref: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$",
    )
    executive_summary: str = Field(min_length=1, max_length=8_000)
    findings: tuple[RepositoryReportFinding, ...] = Field(default=(), max_length=128)
    unresolved_risks: tuple[str, ...] = Field(default=(), max_length=128)
    verification_requirements: tuple[str, ...] = Field(default=(), max_length=128)

    @field_validator(
        "executive_summary",
        "unresolved_risks",
        "verification_requirements",
    )
    @classmethod
    def normalize_report_text(
        cls,
        value: str | tuple[str, ...],
    ) -> str | tuple[str, ...]:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("repository report summary cannot be empty")
            return normalized
        normalized_items = tuple(item.strip() for item in value)
        if any(not item or len(item) > 2_000 for item in normalized_items):
            raise ValueError("repository report items must be in 1..2000 characters")
        if len(set(normalized_items)) != len(normalized_items):
            raise ValueError("repository report items must be unique")
        return normalized_items

    @model_validator(mode="after")
    def validate_findings(self) -> Self:
        finding_ids = tuple(item.finding_id for item in self.findings)
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("repository report finding IDs must be unique")
        return self
