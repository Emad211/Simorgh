from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPECIALIST_PLAN_OUTPUT_CONTRACT = "simorgh.typed-plan.v1"


class SpecialistPlanPayload(BaseModel):
    """Concrete Phase 1.3 proposal payload.

    Additional result families are introduced as an explicit discriminated union in
    Phase 1.4. Arbitrary dictionaries and raw model text are intentionally excluded.
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
