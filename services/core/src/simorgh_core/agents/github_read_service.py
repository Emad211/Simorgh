from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import TaskEnvelope
from simorgh_core.agents.github_read_adapter import (
    GitHubReadAdapter,
    GitHubReadAdapterError,
    GitHubReadConnectorManifest,
)
from simorgh_core.agents.github_read_contracts import (
    GITHUB_CONNECTOR_ID,
    GitHubReadProjectionEnvelope,
    GitHubReadPolicyError,
    GovernedGitHubReadRequest,
)
from simorgh_core.agents.registry import SpecialistRegistry
from simorgh_core.agents.result_authority import (
    EvidenceReference,
    PrivacyClassification,
)
from simorgh_core.agents.tool_gateway import (
    BudgetedToolGateway,
    ToolCallRequest,
    ToolCallResult,
    ToolEffect,
    ToolInvoker,
)

_GOVERNED_REQUEST_KEY = "governed_github_read_request"
_PRIVACY_RANK = {
    PrivacyClassification.PUBLIC: 0,
    PrivacyClassification.INTERNAL: 1,
    PrivacyClassification.PRIVATE: 2,
    PrivacyClassification.SENSITIVE: 3,
    PrivacyClassification.RESTRICTED: 4,
}


class GitHubReadServiceError(RuntimeError):
    pass


class GitHubReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    projection: GitHubReadProjectionEnvelope
    evidence: EvidenceReference
    replayed: bool


class GitHubReadToolInvoker(ToolInvoker):
    """Bridge reviewed GitHub read contracts into the existing tool gateway."""

    def __init__(
        self,
        *,
        manifest: GitHubReadConnectorManifest,
        adapter: GitHubReadAdapter,
    ) -> None:
        if adapter.connector_id != manifest.connector_id:
            raise GitHubReadPolicyError("GitHub adapter connector identity does not match manifest")
        if adapter.connector_version != manifest.connector_version:
            raise GitHubReadPolicyError("GitHub adapter version does not match reviewed manifest")
        self._manifest = manifest
        self._adapter = adapter

    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if set(arguments) != {_GOVERNED_REQUEST_KEY}:
            raise GitHubReadAdapterError("GitHub tool arguments are not a governed request")
        request = GovernedGitHubReadRequest.model_validate(
            arguments[_GOVERNED_REQUEST_KEY]
        )
        if request.tool_id != tool_id:
            raise GitHubReadAdapterError("GitHub tool ID does not match governed request")
        definition = self._manifest.require_tool(tool_id)
        if definition.operation != request.operation:
            raise GitHubReadAdapterError("GitHub operation does not match reviewed manifest")
        _require_manifest_limits(request=request, manifest=self._manifest)
        envelope = await self._adapter.invoke(request)
        return envelope.model_dump(mode="json")


class GovernedGitHubReadService:
    """Execute one Core-authored GitHub read through BudgetedToolGateway."""

    def __init__(
        self,
        *,
        registry: SpecialistRegistry,
        gateway: BudgetedToolGateway,
        manifest: GitHubReadConnectorManifest,
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        self._registry = registry
        self._gateway = gateway
        self._manifest = manifest
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )

    async def execute(
        self,
        *,
        task: TaskEnvelope,
        request: GovernedGitHubReadRequest,
        budget: BudgetAccount,
    ) -> GitHubReadResult:
        self._require_authority(task=task, request=request, budget=budget)
        tool_result = await self._gateway.invoke(
            request=ToolCallRequest(
                invocation_id=request.invocation_id,
                request_id=request.request_id,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                tool_id=request.tool_id,
                connector_id=request.connector_id,
                allowed_data_sources=task.allowed_data_sources,
                effect=ToolEffect.READ_ONLY,
                arguments={
                    _GOVERNED_REQUEST_KEY: request.model_dump(mode="json"),
                },
            ),
            budget=budget,
        )
        envelope = self._validate_tool_result(
            request=request,
            tool_result=tool_result,
        )
        return GitHubReadResult(
            projection=envelope,
            evidence=github_projection_to_evidence(envelope),
            replayed=tool_result.replayed,
        )

    def _require_authority(
        self,
        *,
        task: TaskEnvelope,
        request: GovernedGitHubReadRequest,
        budget: BudgetAccount,
    ) -> None:
        if task.request_id != request.request_id:
            raise GitHubReadPolicyError("GitHub read request does not belong to task")
        if budget.request_id != request.request_id or budget.limits != task.budget:
            raise GitHubReadPolicyError("GitHub read budget does not match task authority")
        if GITHUB_CONNECTOR_ID not in task.allowed_data_sources:
            raise GitHubReadPolicyError("task does not allow the GitHub connector")
        definition = self._registry.get(request.agent_id)
        if definition.version != request.agent_version:
            raise GitHubReadPolicyError("GitHub specialist version does not match policy")
        if request.connector_id not in definition.connector_allowlist:
            raise GitHubReadPolicyError("GitHub connector is outside specialist policy")
        if request.tool_id not in definition.tool_allowlist:
            raise GitHubReadPolicyError("GitHub tool is outside specialist policy")
        self._manifest.require_tool(request.tool_id)
        _require_manifest_limits(request=request, manifest=self._manifest)
        if request.deadline_at_ms is not None and self._now_ms() >= request.deadline_at_ms:
            raise GitHubReadPolicyError("GitHub read deadline has expired")
        snapshot = budget.snapshot()
        if snapshot.cancelled:
            raise GitHubReadPolicyError("cancelled task cannot execute GitHub read")
        if snapshot.exhausted_dimension is not None:
            raise GitHubReadPolicyError("exhausted task cannot execute GitHub read")
        if snapshot.elapsed_ms > request.monotonic_timeout_ms:
            raise GitHubReadPolicyError("GitHub read monotonic timeout has expired")

    def _validate_tool_result(
        self,
        *,
        request: GovernedGitHubReadRequest,
        tool_result: ToolCallResult,
    ) -> GitHubReadProjectionEnvelope:
        identity = (
            tool_result.invocation_id,
            tool_result.tool_id,
            tool_result.connector_id,
        )
        expected = (
            request.invocation_id,
            request.tool_id,
            request.connector_id,
        )
        if identity != expected:
            raise GitHubReadServiceError("GitHub tool result identity is inconsistent")
        try:
            envelope = GitHubReadProjectionEnvelope.model_validate(tool_result.payload)
        except ValueError:
            raise GitHubReadServiceError(
                "GitHub tool result failed typed projection validation"
            ) from None
        if envelope.tool_id != request.tool_id:
            raise GitHubReadServiceError("GitHub projection tool identity is inconsistent")
        if _PRIVACY_RANK[envelope.privacy] > _PRIVACY_RANK[request.privacy_ceiling]:
            raise GitHubReadServiceError(
                "GitHub projection exceeds approved privacy ceiling"
            )
        if (
            envelope.privacy != PrivacyClassification.PUBLIC
            and not self._manifest.private_repositories_allowed
        ):
            raise GitHubReadServiceError(
                "reviewed GitHub manifest does not allow private projections"
            )
        return envelope

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))


def github_projection_to_evidence(
    envelope: GitHubReadProjectionEnvelope,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=_evidence_id(envelope),
        source_id="github.projection",
        connector_id=envelope.connector_id,
        tool_id=envelope.tool_id,
        observed_at_ms=envelope.observed_at_ms,
        fresh_until_ms=envelope.fresh_until_ms,
        cache_disposition=envelope.cache_disposition,
        untrusted_source=True,
        tainted=True,
        projection_sha256=envelope.projection_sha256,
        citation_reference=envelope.citation_reference,
        privacy=envelope.privacy,
    )


def _evidence_id(envelope: GitHubReadProjectionEnvelope):
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(
        NAMESPACE_URL,
        "simorgh-github-evidence:"
        f"{envelope.tool_id}:{envelope.projection_sha256}:"
        f"{envelope.observed_at_ms}:{envelope.citation_reference}",
    )


def _require_manifest_limits(
    *,
    request: GovernedGitHubReadRequest,
    manifest: GitHubReadConnectorManifest,
) -> None:
    if request.limits.max_response_bytes > manifest.maximum_response_bytes:
        raise GitHubReadPolicyError("GitHub request exceeds manifest response limit")
    if request.limits.max_items > manifest.maximum_items:
        raise GitHubReadPolicyError("GitHub request exceeds manifest item limit")
    if request.limits.max_pages > manifest.maximum_pages:
        raise GitHubReadPolicyError("GitHub request exceeds manifest page limit")


__all__ = [
    "GitHubReadResult",
    "GitHubReadServiceError",
    "GitHubReadToolInvoker",
    "GovernedGitHubReadService",
    "github_projection_to_evidence",
]
