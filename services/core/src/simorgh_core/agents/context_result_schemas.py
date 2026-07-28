from __future__ import annotations

from simorgh_core.agents.result_authority import (
    ResultSchemaRegistry,
    SpecialistPlanResultSchema,
)
from simorgh_core.agents.specialist_results import (
    REPOSITORY_REPORT_OUTPUT_CONTRACT,
    RepositoryReportPayload,
)

REPOSITORY_REPORT_RESULT_SCHEMA_ID = "simorgh.repository-report-result"
REPOSITORY_REPORT_RESULT_SCHEMA_VERSION = "1.0"


class RepositoryReportResultSchema:
    """Schema-only authority used by Phase 1.7 context compilation.

    The complete GitHub report executor, authoritative terminalization, and Persian
    presentation remain Phase 1.10 responsibilities.
    """

    @property
    def schema_id(self) -> str:
        return REPOSITORY_REPORT_RESULT_SCHEMA_ID

    @property
    def schema_version(self) -> str:
        return REPOSITORY_REPORT_RESULT_SCHEMA_VERSION

    @property
    def output_contract(self) -> str:
        return REPOSITORY_REPORT_OUTPUT_CONTRACT

    @property
    def family(self) -> str:
        return "repository_report"

    def validate_payload(self, payload: object) -> RepositoryReportPayload:
        return RepositoryReportPayload.model_validate(payload)


def default_context_result_schema_registry() -> ResultSchemaRegistry:
    """Return exact schema authority available to the Context Compiler."""

    return ResultSchemaRegistry(
        (SpecialistPlanResultSchema(), RepositoryReportResultSchema())
    )


__all__ = [
    "REPOSITORY_REPORT_RESULT_SCHEMA_ID",
    "REPOSITORY_REPORT_RESULT_SCHEMA_VERSION",
    "RepositoryReportResultSchema",
    "default_context_result_schema_registry",
]
