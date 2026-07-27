from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from simorgh_core.agents.context_contracts import (
    CONTEXT_CONTRACT_VERSION,
    ContextOutputSchemaProjection,
    ContextToolSchemaProjection,
)
from simorgh_core.agents.github_read_adapter import GitHubReadConnectorManifest
from simorgh_core.agents.github_read_contracts import (
    GitHubFileArguments,
    GitHubFileProjection,
    GitHubIssueArguments,
    GitHubIssueProjection,
    GitHubPullRequestArguments,
    GitHubPullRequestProjection,
    GitHubReadOperation,
    GitHubSearchArguments,
    GitHubSearchProjection,
)
from simorgh_core.agents.invocations import InvocationEffect, canonical_fingerprint
from simorgh_core.agents.result_authority import (
    SPECIALIST_PLAN_RESULT_SCHEMA_ID,
    SPECIALIST_PLAN_RESULT_SCHEMA_VERSION,
    ResultSchemaRegistry,
)
from simorgh_core.agents.specialist_results import (
    SPECIALIST_PLAN_OUTPUT_CONTRACT,
    SpecialistPlanPayload,
)


class ContextProjectionError(RuntimeError):
    """Reviewed schema projection could not be derived exactly."""


_GITHUB_INPUT_MODELS: dict[GitHubReadOperation, type[BaseModel]] = {
    GitHubReadOperation.SEARCH: GitHubSearchArguments,
    GitHubReadOperation.FETCH_FILE: GitHubFileArguments,
    GitHubReadOperation.FETCH_ISSUE: GitHubIssueArguments,
    GitHubReadOperation.FETCH_PR: GitHubPullRequestArguments,
}
_GITHUB_OUTPUT_MODELS: dict[GitHubReadOperation, type[BaseModel]] = {
    GitHubReadOperation.SEARCH: GitHubSearchProjection,
    GitHubReadOperation.FETCH_FILE: GitHubFileProjection,
    GitHubReadOperation.FETCH_ISSUE: GitHubIssueProjection,
    GitHubReadOperation.FETCH_PR: GitHubPullRequestProjection,
}
_GITHUB_DESCRIPTIONS: dict[GitHubReadOperation, str] = {
    GitHubReadOperation.SEARCH: "Search bounded GitHub repository content and metadata.",
    GitHubReadOperation.FETCH_FILE: (
        "Fetch one bounded UTF-8 GitHub file projection at an explicit ref."
    ),
    GitHubReadOperation.FETCH_ISSUE: "Fetch one bounded GitHub issue projection.",
    GitHubReadOperation.FETCH_PR: "Fetch one bounded GitHub pull-request projection.",
}


def build_github_context_tool_schemas(
    *,
    manifest: GitHubReadConnectorManifest,
    tool_ids: Iterable[str],
) -> tuple[ContextToolSchemaProjection, ...]:
    requested = tuple(sorted(set(tool_ids)))
    projections: list[ContextToolSchemaProjection] = []
    for tool_id in requested:
        definition = manifest.require_tool(tool_id)
        operation = definition.operation
        payload = {
            "schema_version": CONTEXT_CONTRACT_VERSION,
            "tool_id": definition.tool_id,
            "connector_id": manifest.connector_id,
            "effect": InvocationEffect.READ_ONLY.value,
            "input_contract": definition.input_contract,
            "output_contract": definition.output_contract,
            "description": _GITHUB_DESCRIPTIONS[operation],
            "input_schema": _GITHUB_INPUT_MODELS[operation].model_json_schema(
                mode="validation"
            ),
            "output_schema": _GITHUB_OUTPUT_MODELS[operation].model_json_schema(
                mode="validation"
            ),
        }
        projections.append(
            ContextToolSchemaProjection(
                schema_version=CONTEXT_CONTRACT_VERSION,
                tool_id=definition.tool_id,
                connector_id=manifest.connector_id,
                effect=InvocationEffect.READ_ONLY,
                input_contract=definition.input_contract,
                output_contract=definition.output_contract,
                description=_GITHUB_DESCRIPTIONS[operation],
                input_schema=_GITHUB_INPUT_MODELS[operation].model_json_schema(
                    mode="validation"
                ),
                output_schema=_GITHUB_OUTPUT_MODELS[operation].model_json_schema(
                    mode="validation"
                ),
                canonical_sha256=canonical_fingerprint(payload),
            )
        )
    return tuple(projections)


def build_specialist_plan_context_output_schema(
    *,
    registry: ResultSchemaRegistry,
    output_contract: str,
) -> ContextOutputSchemaProjection:
    if output_contract != SPECIALIST_PLAN_OUTPUT_CONTRACT:
        raise ContextProjectionError(
            "context output projection supports the registered typed-plan family only"
        )
    handler = registry.require(
        schema_id=SPECIALIST_PLAN_RESULT_SCHEMA_ID,
        schema_version=SPECIALIST_PLAN_RESULT_SCHEMA_VERSION,
        output_contract=output_contract,
        family="specialist_plan",
    )
    payload = {
        "schema_version": CONTEXT_CONTRACT_VERSION,
        "output_contract": handler.output_contract,
        "result_schema_id": handler.schema_id,
        "result_schema_version": handler.schema_version,
        "family": handler.family,
        "json_schema": SpecialistPlanPayload.model_json_schema(mode="validation"),
    }
    return ContextOutputSchemaProjection(
        schema_version=CONTEXT_CONTRACT_VERSION,
        output_contract=handler.output_contract,
        result_schema_id=handler.schema_id,
        result_schema_version=handler.schema_version,
        family=handler.family,
        json_schema=SpecialistPlanPayload.model_json_schema(mode="validation"),
        canonical_sha256=canonical_fingerprint(payload),
    )


__all__ = [
    "ContextProjectionError",
    "build_github_context_tool_schemas",
    "build_specialist_plan_context_output_schema",
]
