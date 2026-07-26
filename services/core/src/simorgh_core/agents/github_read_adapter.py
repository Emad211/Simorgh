from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.github_read_contracts import (
    GITHUB_CONNECTOR_ID,
    GITHUB_FETCH_FILE_TOOL_ID,
    GITHUB_FETCH_ISSUE_TOOL_ID,
    GITHUB_FETCH_PR_TOOL_ID,
    GITHUB_READ_CONTRACT_VERSION,
    GITHUB_SEARCH_TOOL_ID,
    GitHubFileProjection,
    GitHubIssueProjection,
    GitHubObjectKind,
    GitHubPullRequestProjection,
    GitHubReadContractError,
    GitHubReadOperation,
    GitHubReadProjectionEnvelope,
    GitHubSearchProjection,
    GovernedGitHubReadRequest,
)
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.read_tool_contracts import GovernedReadAdapter


class GitHubReadAdapterError(RuntimeError):
    """Sanitized adapter-boundary failure."""


class GitHubFixtureNotFoundError(GitHubReadAdapterError):
    pass


class GitHubResponseLimitError(GitHubReadAdapterError):
    pass


class GitHubReadToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    tool_id: str = Field(min_length=1, max_length=128)
    operation: GitHubReadOperation
    input_contract: str = Field(min_length=1, max_length=128)
    output_contract: str = Field(min_length=1, max_length=128)
    read_only: bool = True

    @model_validator(mode="after")
    def validate_definition(self) -> GitHubReadToolDefinition:
        if self.tool_id != self.operation.value:
            raise ValueError("GitHub tool ID must equal exact operation identity")
        if not self.read_only:
            raise ValueError("GitHub read manifest cannot contain mutation tools")
        return self


class GitHubReadConnectorManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    connector_id: str = Field(default=GITHUB_CONNECTOR_ID, min_length=1, max_length=128)
    connector_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    contract_version: str = Field(default=GITHUB_READ_CONTRACT_VERSION, max_length=16)
    tools: tuple[GitHubReadToolDefinition, ...] = Field(min_length=1, max_length=32)
    maximum_request_bytes: int = Field(default=128_000, ge=1, le=256_000)
    maximum_response_bytes: int = Field(default=512_000, ge=1, le=2_000_000)
    maximum_text_characters: int = Field(default=250_000, ge=0, le=250_000)
    maximum_items: int = Field(default=100, ge=1, le=1_000)
    maximum_pages: Literal[1] = 1
    maximum_timeout_ms: int = Field(default=120_000, ge=1, le=86_400_000)
    allowed_hosts: tuple[str, ...] = (
        "api.github.com",
        "github.com",
        "raw.githubusercontent.com",
    )
    require_explicit_ref: Literal[True] = True
    supports_freshness: Literal[True] = True
    supports_cache_policy: Literal[True] = True
    supports_cancellation: Literal[True] = True
    follow_symlinks: Literal[False] = False
    traverse_submodules: Literal[False] = False
    download_lfs_objects: Literal[False] = False
    extract_archives: Literal[False] = False
    return_binary_content: Literal[False] = False
    credential_mode: Literal["adapter_owned_reference_only"] = "adapter_owned_reference_only"
    trace_body_allowed: Literal[False] = False
    private_repositories_allowed: bool = False

    @model_validator(mode="after")
    def validate_manifest(self) -> GitHubReadConnectorManifest:
        if self.connector_id != GITHUB_CONNECTOR_ID:
            raise ValueError("GitHub read manifest must use the reviewed connector identity")
        identities = [tool.tool_id for tool in self.tools]
        if len(set(identities)) != len(identities):
            raise ValueError("GitHub read manifest contains duplicate tool IDs")
        if self.allowed_hosts != tuple(sorted(set(self.allowed_hosts))):
            raise ValueError("GitHub manifest hosts must be unique and canonically sorted")
        if any(not host or "/" in host or ":" in host for host in self.allowed_hosts):
            raise ValueError("GitHub manifest hosts must be bounded host names")
        return self

    def require_tool(self, tool_id: str) -> GitHubReadToolDefinition:
        for tool in self.tools:
            if tool.tool_id == tool_id:
                return tool
        raise GitHubReadAdapterError("GitHub read tool is not present in reviewed manifest")


class GitHubReadAdapter(
    GovernedReadAdapter[GovernedGitHubReadRequest, GitHubReadProjectionEnvelope],
    Protocol,
):
    """GitHub specialization of the connector-neutral governed read boundary."""


def default_github_read_manifest() -> GitHubReadConnectorManifest:
    return GitHubReadConnectorManifest(
        connector_version="1.0.0",
        tools=(
            GitHubReadToolDefinition(
                tool_id=GITHUB_SEARCH_TOOL_ID,
                operation=GitHubReadOperation.SEARCH,
                input_contract="github.search-request.v1",
                output_contract="github.search-projection.v1",
            ),
            GitHubReadToolDefinition(
                tool_id=GITHUB_FETCH_FILE_TOOL_ID,
                operation=GitHubReadOperation.FETCH_FILE,
                input_contract="github.file-request.v1",
                output_contract="github.file-projection.v1",
            ),
            GitHubReadToolDefinition(
                tool_id=GITHUB_FETCH_ISSUE_TOOL_ID,
                operation=GitHubReadOperation.FETCH_ISSUE,
                input_contract="github.issue-request.v1",
                output_contract="github.issue-projection.v1",
            ),
            GitHubReadToolDefinition(
                tool_id=GITHUB_FETCH_PR_TOOL_ID,
                operation=GitHubReadOperation.FETCH_PR,
                input_contract="github.pr-request.v1",
                output_contract="github.pr-projection.v1",
            ),
        ),
    )


def github_fixture_key(request: GovernedGitHubReadRequest) -> str:
    return canonical_fingerprint(
        {
            "operation": request.operation.value,
            "arguments": request.arguments.model_dump(mode="json"),
        }
    )


class FakeGitHubReadAdapter:
    """Deterministic zero-network adapter used by ordinary CI."""

    def __init__(
        self,
        *,
        fixtures: Mapping[str, GitHubReadProjectionEnvelope],
        connector_version: str = "1.0.0",
    ) -> None:
        self._fixtures = {
            key: GitHubReadProjectionEnvelope.model_validate(value.model_dump(mode="json"))
            for key, value in fixtures.items()
        }
        self._connector_version = connector_version
        self.calls = 0

    @property
    def connector_id(self) -> str:
        return GITHUB_CONNECTOR_ID

    @property
    def connector_version(self) -> str:
        return self._connector_version

    async def invoke(
        self,
        request: GovernedGitHubReadRequest,
    ) -> GitHubReadProjectionEnvelope:
        self.calls += 1
        fixture = self._fixtures.get(github_fixture_key(request))
        if fixture is None:
            raise GitHubFixtureNotFoundError("fake GitHub fixture is not registered")
        validated = GitHubReadProjectionEnvelope.model_validate(fixture.model_dump(mode="json"))
        enforce_github_projection_limits(request=request, envelope=validated)
        return validated


def enforce_github_projection_limits(
    *,
    request: GovernedGitHubReadRequest,
    envelope: GitHubReadProjectionEnvelope,
) -> None:
    limits = request.limits
    if envelope.tool_id != request.tool_id:
        raise GitHubReadContractError("GitHub adapter returned a projection for another tool")
    if envelope.response_bytes > limits.max_response_bytes:
        raise GitHubResponseLimitError("GitHub projection exceeds response-byte limit")
    projection = envelope.projection
    if isinstance(projection, GitHubSearchProjection):
        if len(projection.items) > limits.max_items:
            raise GitHubResponseLimitError("GitHub search projection exceeds item limit")
    elif isinstance(projection, GitHubFileProjection):
        if projection.text is not None and len(projection.text) > limits.max_text_characters:
            raise GitHubResponseLimitError("GitHub file projection exceeds text limit")
        if projection.object_kind == GitHubObjectKind.BINARY and projection.text is not None:
            raise GitHubResponseLimitError("GitHub binary projection cannot contain raw content")
        if projection.object_kind != GitHubObjectKind.REGULAR and projection.text is not None:
            raise GitHubResponseLimitError("GitHub non-regular object cannot be traversed")
    elif isinstance(projection, GitHubIssueProjection):
        if projection.body is not None and len(projection.body) > limits.max_text_characters:
            raise GitHubResponseLimitError("GitHub issue projection exceeds text limit")
    elif isinstance(projection, GitHubPullRequestProjection):
        if projection.body is not None and len(projection.body) > limits.max_text_characters:
            raise GitHubResponseLimitError("GitHub PR projection exceeds text limit")
    else:
        raise GitHubReadContractError("unknown GitHub projection type")


__all__ = [
    "FakeGitHubReadAdapter",
    "GitHubFixtureNotFoundError",
    "GitHubReadAdapter",
    "GitHubReadAdapterError",
    "GitHubReadConnectorManifest",
    "GitHubReadToolDefinition",
    "GitHubResponseLimitError",
    "default_github_read_manifest",
    "enforce_github_projection_limits",
    "github_fixture_key",
]
