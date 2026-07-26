from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.result_contracts import (
    RESULT_SCHEMA_VERSION,
    ResultSchemaConflictError,
    UnknownResultSchemaError,
)
from simorgh_core.agents.specialist_results import (
    SPECIALIST_PLAN_OUTPUT_CONTRACT,
    SpecialistPlanPayload,
)

_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"


class ResultSchemaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    contract_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    schema_version: str = Field(pattern=r"^[0-9]+\.[0-9]+$", max_length=32)
    family: Literal["plan"]


class ResultSchemaRegistry:
    """Immutable exact-contract registry for authoritative result payloads."""

    def __init__(
        self,
        definitions: Iterable[ResultSchemaDefinition] = (),
    ) -> None:
        supplied = tuple(definitions) or (
            ResultSchemaDefinition(
                contract_id=SPECIALIST_PLAN_OUTPUT_CONTRACT,
                schema_version=RESULT_SCHEMA_VERSION,
                family="plan",
            ),
        )
        compiled: dict[tuple[str, str], ResultSchemaDefinition] = {}
        for definition in supplied:
            identity = (definition.contract_id, definition.schema_version)
            if identity in compiled:
                raise ResultSchemaConflictError(
                    f"result schema {identity!r} was registered more than once"
                )
            compiled[identity] = definition
        self._definitions = compiled

    def get(self, *, contract_id: str, schema_version: str) -> ResultSchemaDefinition:
        definition = self._definitions.get((contract_id, schema_version))
        if definition is None:
            raise UnknownResultSchemaError(
                f"result schema {(contract_id, schema_version)!r} is not registered"
            )
        return definition

    def validate_payload(
        self,
        *,
        contract_id: str,
        schema_version: str,
        payload: object,
    ) -> SpecialistPlanPayload:
        definition = self.get(contract_id=contract_id, schema_version=schema_version)
        if definition.family != "plan":
            raise UnknownResultSchemaError("result family is not implemented")
        return SpecialistPlanPayload.model_validate(payload)
