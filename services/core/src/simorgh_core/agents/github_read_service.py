from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, ValidationError

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import (
    FreshnessClass,
    RoutingDecision,
    RoutingState,
    TaskEnvelope,
)
from simorgh_core.agents.github_read_adapter import (
    GitHubReadAdapter,
    GitHubReadAdapterError,
    GitHubReadConnectorManifest,
    GitHubResponseLimitError,
    enforce_github_projection_limits,
)
from simorgh_core.agents.github_read_contracts import (
    GITHUB_CONNECTOR_ID,
    GitHubCachePolicy,
    GitHubReadArguments,
    GitHubReadContractError,
    GitHubReadLimits,
    GitHubReadPolicyError,
    GitHubReadProjectionEnvelope,
    GitHubSearchProjection,
    GitHubVisibility,
    GovernedGitHubReadRequest,
)
from simorgh_core.agents.invocations import canonical_size_bytes
from simorgh_core.agents.registry import SpecialistRegistry
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    EvidenceReference,
    PrivacyClassification,
)
from simorgh_core.agents.specialist_execution import SpecialistCancellation
from simorgh_core.agents.tool_gateway import (
    BudgetedToolGateway,
    ToolCallRequest,
    ToolCallResult,
    ToolEffect,
    ToolInvoker,
    ToolResultRejectedError,
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
        request = GovernedGitHubReadRequest.model_validate(arguments[_GOVERNED_REQUEST_KEY])
        if request.tool_id != tool_id:
            raise GitHubReadAdapterError("GitHub tool ID does not match governed request")
        definition = self._manifest.require_tool(tool_id)
        if definition.operation != request.operation:
            raise GitHubReadAdapterError("GitHub operation does not match reviewed manifest")
        _require_manifest_limits(request=request, manifest=self._manifest)
        try:
            envelope = await self._adapter.invoke(request)
            enforce_github_projection_limits(request=request, envelope=envelope)
            _require_projection_policy(request=request, envelope=envelope, manifest=self._manifest)
        except (GitHubReadContractError, GitHubResponseLimitError, ValidationError):
            raise ToolResultRejectedError(
                "GitHub adapter returned a rejected typed projection"
            ) from None
        return envelope.model_dump(mode="json")


class GitHubReadRequestCompiler:
    """Compile one exact GitHub read request from durable route and policy."""

    def __init__(
        self,
        *,
        registry: SpecialistRegistry,
        manifest: GitHubReadConnectorManifest,
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        self._registry = registry
        self._manifest = manifest
        self._wall_clock_millis = wall_clock_millis or (lambda: int(time.time() * 1_000))

    def compile(
        self,
        *,
        task: TaskEnvelope,
        routing: RoutingDecision,
        arguments: GitHubReadArguments,
        invocation_id: UUID,
        cancellation_owner_id: UUID,
        parent_invocation_id: UUID | None = None,
    ) -> GovernedGitHubReadRequest:
        if routing.request_id != task.request_id or routing.state != RoutingState.ROUTED:
            raise GitHubReadPolicyError("GitHub request requires the exact routed task")
        if routing.selected_agent_id != "github.read":
            raise GitHubReadPolicyError("routed specialist is not github.read")
        definition = self._registry.get("github.read")
        if routing.selected_agent_version != definition.version:
            raise GitHubReadPolicyError("routed GitHub specialist version is not active")
        if (
            task.explicit_task_kind is not None
            and task.explicit_task_kind not in definition.task_kinds
        ):
            raise GitHubReadPolicyError("task kind is outside GitHub specialist policy")
        tool_id = arguments.operation.value
        if tool_id not in definition.tool_allowlist:
            raise GitHubReadPolicyError("GitHub operation is outside specialist policy")
        try:
            self._manifest.require_tool(tool_id)
        except GitHubReadAdapterError:
            raise GitHubReadPolicyError(
                "GitHub operation is outside reviewed connector policy"
            ) from None
        effective_sources = (
            task.allowed_data_sources
            & definition.connector_allowlist
            & frozenset({self._manifest.connector_id})
        )
        if effective_sources != frozenset({GITHUB_CONNECTOR_ID}):
            raise GitHubReadPolicyError("task has no effective GitHub read authority")
        effective_budget = self._registry.effective_budget(
            agent_id=definition.agent_id,
            request_budget=task.budget,
        )
        now_ms = max(0, int(self._wall_clock_millis()))
        deadline_at_ms = now_ms + effective_budget.max_elapsed_ms
        if task.deadline_at_ms is not None:
            deadline_at_ms = min(deadline_at_ms, task.deadline_at_ms)
        if deadline_at_ms <= now_ms:
            raise GitHubReadPolicyError("GitHub read deadline has already expired")
        if task.freshness in {FreshnessClass.CURRENT, FreshnessClass.EXECUTION_BOUND}:
            cache_policy = GitHubCachePolicy.LIVE_ONLY
            minimum_fresh_until_ms: int | None = now_ms
        else:
            cache_policy = GitHubCachePolicy.CACHE_ALLOWED
            minimum_fresh_until_ms = None
        request = GovernedGitHubReadRequest(
            request_id=task.request_id,
            invocation_id=invocation_id,
            parent_invocation_id=parent_invocation_id,
            agent_version=definition.version,
            allowed_data_sources=effective_sources,
            arguments=arguments,
            limits=GitHubReadLimits(
                max_response_bytes=min(128_000, self._manifest.maximum_response_bytes),
                max_text_characters=min(32_000, self._manifest.maximum_text_characters),
                max_items=min(25, self._manifest.maximum_items),
            ),
            cache_policy=cache_policy,
            minimum_fresh_until_ms=minimum_fresh_until_ms,
            privacy_ceiling=PrivacyClassification.INTERNAL,
            deadline_at_ms=deadline_at_ms,
            monotonic_timeout_ms=effective_budget.max_elapsed_ms,
            cancellation_owner_id=cancellation_owner_id,
        )
        _require_manifest_limits(request=request, manifest=self._manifest)
        return request


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
        self._wall_clock_millis = wall_clock_millis or (lambda: int(time.time() * 1_000))

    async def execute(
        self,
        *,
        task: TaskEnvelope,
        request: GovernedGitHubReadRequest,
        budget: BudgetAccount,
        cancellation: SpecialistCancellation | None = None,
    ) -> GitHubReadResult:
        self._require_authority(
            task=task,
            request=request,
            budget=budget,
            cancellation=cancellation,
        )
        tool_result = await self._gateway.invoke(
            request=ToolCallRequest(
                invocation_id=request.invocation_id,
                request_id=request.request_id,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                tool_id=request.tool_id,
                connector_id=request.connector_id,
                allowed_data_sources=request.allowed_data_sources,
                cancellation_owner_id=request.cancellation_owner_id,
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
        cancellation: SpecialistCancellation | None,
    ) -> None:
        if task.request_id != request.request_id:
            raise GitHubReadPolicyError("GitHub read request does not belong to task")
        definition = self._registry.get(request.agent_id)
        effective_budget = self._registry.effective_budget(
            agent_id=definition.agent_id,
            request_budget=task.budget,
        )
        if budget.request_id != request.request_id or budget.limits != effective_budget:
            raise GitHubReadPolicyError("GitHub read budget does not match effective authority")
        effective_sources = (
            task.allowed_data_sources
            & definition.connector_allowlist
            & frozenset({self._manifest.connector_id})
        )
        if request.allowed_data_sources != effective_sources:
            raise GitHubReadPolicyError(
                "task does not allow the GitHub connector or request exceeds policy intersection"
            )
        if effective_sources != frozenset({GITHUB_CONNECTOR_ID}):
            raise GitHubReadPolicyError("task does not allow the GitHub connector")
        if definition.version != request.agent_version:
            raise GitHubReadPolicyError("GitHub specialist version does not match policy")
        if request.connector_id not in definition.connector_allowlist:
            raise GitHubReadPolicyError("GitHub connector is outside specialist policy")
        if request.tool_id not in definition.tool_allowlist:
            raise GitHubReadPolicyError("GitHub tool is outside specialist policy")
        try:
            self._manifest.require_tool(request.tool_id)
        except GitHubReadAdapterError:
            raise GitHubReadPolicyError(
                "GitHub tool is outside reviewed connector policy"
            ) from None
        _require_manifest_limits(request=request, manifest=self._manifest)
        if task.deadline_at_ms is not None and (
            request.deadline_at_ms is None or request.deadline_at_ms > task.deadline_at_ms
        ):
            raise GitHubReadPolicyError("GitHub read deadline exceeds task authority")
        if request.deadline_at_ms is not None and self._now_ms() >= request.deadline_at_ms:
            raise GitHubReadPolicyError("GitHub read deadline has expired")
        if request.monotonic_timeout_ms > budget.limits.max_elapsed_ms:
            raise GitHubReadPolicyError("GitHub read monotonic timeout exceeds task budget")
        if cancellation is not None:
            cancellation.require_owner(request.cancellation_owner_id)
            cancellation.raise_if_cancelled()
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
        except ValidationError:
            raise GitHubReadServiceError(
                "GitHub tool result failed typed projection validation"
            ) from None
        if envelope.tool_id != request.tool_id:
            raise GitHubReadServiceError("GitHub projection tool identity is inconsistent")
        enforce_github_projection_limits(request=request, envelope=envelope)
        _require_projection_policy(request=request, envelope=envelope, manifest=self._manifest)
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


def _evidence_id(envelope: GitHubReadProjectionEnvelope) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "simorgh-github-evidence:"
        f"{envelope.tool_id}:{envelope.projection_sha256}:"
        f"{envelope.observed_at_ms}:{envelope.citation_reference}",
    )


def _require_projection_policy(
    *,
    request: GovernedGitHubReadRequest,
    envelope: GitHubReadProjectionEnvelope,
    manifest: GitHubReadConnectorManifest,
) -> None:
    required_privacy = _required_projection_privacy(envelope)
    if _PRIVACY_RANK[envelope.privacy] < _PRIVACY_RANK[required_privacy]:
        raise GitHubReadPolicyError(
            "GitHub projection privacy under-classifies repository visibility"
        )
    if (
        required_privacy != PrivacyClassification.PUBLIC
        and not manifest.private_repositories_allowed
    ):
        raise GitHubReadPolicyError(
            "reviewed GitHub manifest does not allow non-public projections"
        )
    if _PRIVACY_RANK[envelope.privacy] > _PRIVACY_RANK[request.privacy_ceiling]:
        raise GitHubReadPolicyError("GitHub projection exceeds approved privacy ceiling")
    if request.cache_policy == GitHubCachePolicy.LIVE_ONLY and envelope.cache_disposition not in {
        EvidenceCacheDisposition.LIVE,
        EvidenceCacheDisposition.CACHE_MISS,
    }:
        raise GitHubReadPolicyError("GitHub projection does not satisfy live-only policy")
    if (
        request.cache_policy == GitHubCachePolicy.CACHE_ONLY
        and envelope.cache_disposition != EvidenceCacheDisposition.CACHE_HIT
    ):
        raise GitHubReadPolicyError("GitHub projection does not satisfy cache-only policy")
    if request.minimum_fresh_until_ms is not None and (
        envelope.fresh_until_ms is None
        or envelope.fresh_until_ms < request.minimum_fresh_until_ms
        or envelope.cache_disposition == EvidenceCacheDisposition.STALE
    ):
        raise GitHubReadPolicyError("GitHub projection does not satisfy freshness policy")
    if (
        _PRIVACY_RANK[envelope.privacy] > _PRIVACY_RANK[PrivacyClassification.INTERNAL]
        and not manifest.private_repositories_allowed
    ):
        raise GitHubReadPolicyError("reviewed GitHub manifest does not allow private projections")


def _required_projection_privacy(
    envelope: GitHubReadProjectionEnvelope,
) -> PrivacyClassification:
    projection = envelope.projection
    if isinstance(projection, GitHubSearchProjection):
        visibilities = tuple(item.visibility for item in projection.items)
    else:
        visibilities = (projection.visibility,)
    required = PrivacyClassification.PUBLIC
    for visibility in visibilities:
        candidate = {
            GitHubVisibility.PUBLIC: PrivacyClassification.PUBLIC,
            GitHubVisibility.INTERNAL: PrivacyClassification.INTERNAL,
            GitHubVisibility.PRIVATE: PrivacyClassification.PRIVATE,
        }[visibility]
        if _PRIVACY_RANK[candidate] > _PRIVACY_RANK[required]:
            required = candidate
    return required


def _require_manifest_limits(
    *,
    request: GovernedGitHubReadRequest,
    manifest: GitHubReadConnectorManifest,
) -> None:
    if canonical_size_bytes(request) > manifest.maximum_request_bytes:
        raise GitHubReadPolicyError("GitHub request exceeds manifest request-byte limit")
    if request.limits.max_response_bytes > manifest.maximum_response_bytes:
        raise GitHubReadPolicyError("GitHub request exceeds manifest response limit")
    if request.limits.max_text_characters > manifest.maximum_text_characters:
        raise GitHubReadPolicyError("GitHub request exceeds manifest text limit")
    if request.limits.max_items > manifest.maximum_items:
        raise GitHubReadPolicyError("GitHub request exceeds manifest item limit")
    if request.limits.max_pages > manifest.maximum_pages:
        raise GitHubReadPolicyError("GitHub request exceeds manifest page limit")
    if request.monotonic_timeout_ms > manifest.maximum_timeout_ms:
        raise GitHubReadPolicyError("GitHub request exceeds manifest timeout limit")
    if request.cache_policy and not manifest.supports_cache_policy:
        raise GitHubReadPolicyError("GitHub manifest does not support cache policy")
    if request.minimum_fresh_until_ms is not None and not manifest.supports_freshness:
        raise GitHubReadPolicyError("GitHub manifest does not support freshness policy")


__all__ = [
    "GitHubReadRequestCompiler",
    "GitHubReadResult",
    "GitHubReadServiceError",
    "GitHubReadToolInvoker",
    "GovernedGitHubReadService",
    "github_projection_to_evidence",
]
