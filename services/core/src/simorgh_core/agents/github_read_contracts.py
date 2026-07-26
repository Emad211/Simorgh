from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from simorgh_core.agents.invocations import canonical_fingerprint, canonical_size_bytes
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
)

GITHUB_READ_CONTRACT_VERSION: Literal["1.0"] = "1.0"
GITHUB_CONNECTOR_ID: Literal["github"] = "github"
GITHUB_SEARCH_TOOL_ID: Literal["github.search"] = "github.search"
GITHUB_FETCH_FILE_TOOL_ID: Literal["github.fetch-file"] = "github.fetch-file"
GITHUB_FETCH_ISSUE_TOOL_ID: Literal["github.fetch-issue"] = "github.fetch-issue"
GITHUB_FETCH_PR_TOOL_ID: Literal["github.fetch-pr"] = "github.fetch-pr"
MAX_GITHUB_PROJECTION_BYTES = 512_000
_REPOSITORY_PATTERN = r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$"
_REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$"
_SHA_PATTERN = r"^[0-9a-f]{40,64}$"


class GitHubReadContractError(RuntimeError):
    pass


class GitHubReadPolicyError(GitHubReadContractError):
    pass


class GitHubProjectionError(GitHubReadContractError):
    pass


class GitHubReadOperation(StrEnum):
    SEARCH = GITHUB_SEARCH_TOOL_ID
    FETCH_FILE = GITHUB_FETCH_FILE_TOOL_ID
    FETCH_ISSUE = GITHUB_FETCH_ISSUE_TOOL_ID
    FETCH_PR = GITHUB_FETCH_PR_TOOL_ID


class GitHubVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"


class GitHubTextDisposition(StrEnum):
    COMPLETE = "complete"
    TRUNCATED = "truncated"
    METADATA_ONLY = "metadata_only"
    BINARY_REJECTED = "binary_rejected"


class GitHubPullRequestState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class GitHubIssueState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class GitHubCheckState(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class GitHubCachePolicy(StrEnum):
    LIVE_ONLY = "live_only"
    CACHE_ALLOWED = "cache_allowed"
    CACHE_ONLY = "cache_only"


class GitHubObjectKind(StrEnum):
    REGULAR = "regular"
    BINARY = "binary"
    SYMLINK = "symlink"
    SUBMODULE = "submodule"
    LFS_POINTER = "lfs_pointer"


class GitHubReadLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    max_response_bytes: int = Field(default=128_000, ge=1, le=MAX_GITHUB_PROJECTION_BYTES)
    max_text_characters: int = Field(default=32_000, ge=0, le=250_000)
    max_items: int = Field(default=25, ge=1, le=100)
    max_pages: Literal[1] = 1


class GitHubSearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    operation: Literal[GitHubReadOperation.SEARCH] = GitHubReadOperation.SEARCH
    query: str = Field(min_length=1, max_length=1_000)
    repository: str | None = Field(default=None, pattern=_REPOSITORY_PATTERN)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("GitHub search query cannot be empty")
        return normalized


class GitHubFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    operation: Literal[GitHubReadOperation.FETCH_FILE] = GitHubReadOperation.FETCH_FILE
    repository: str = Field(pattern=_REPOSITORY_PATTERN)
    ref: str = Field(pattern=_REF_PATTERN, max_length=255)
    path: str = Field(min_length=1, max_length=1_024)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        parts = normalized.split("/")
        if (
            not normalized
            or normalized.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or "\x00" in normalized
        ):
            raise ValueError("GitHub file path is unsafe")
        return normalized


class GitHubIssueArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    operation: Literal[GitHubReadOperation.FETCH_ISSUE] = GitHubReadOperation.FETCH_ISSUE
    repository: str = Field(pattern=_REPOSITORY_PATTERN)
    issue_number: int = Field(ge=1, le=2_147_483_647)


class GitHubPullRequestArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    operation: Literal[GitHubReadOperation.FETCH_PR] = GitHubReadOperation.FETCH_PR
    repository: str = Field(pattern=_REPOSITORY_PATTERN)
    pull_request_number: int = Field(ge=1, le=2_147_483_647)


type GitHubReadArguments = Annotated[
    GitHubSearchArguments | GitHubFileArguments | GitHubIssueArguments | GitHubPullRequestArguments,
    Field(discriminator="operation"),
]
_ARGUMENT_ADAPTER: TypeAdapter[GitHubReadArguments] = TypeAdapter(GitHubReadArguments)


class GovernedGitHubReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = GITHUB_READ_CONTRACT_VERSION
    request_id: UUID
    invocation_id: UUID
    parent_invocation_id: UUID | None = None
    agent_id: Literal["github.read"] = "github.read"
    agent_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    connector_id: Literal["github"] = GITHUB_CONNECTOR_ID
    allowed_data_sources: frozenset[str] = Field(
        default_factory=lambda: frozenset({GITHUB_CONNECTOR_ID}),
        min_length=1,
        max_length=8,
    )
    arguments: GitHubReadArguments
    limits: GitHubReadLimits = Field(default_factory=GitHubReadLimits)
    cache_policy: GitHubCachePolicy = GitHubCachePolicy.CACHE_ALLOWED
    minimum_fresh_until_ms: int | None = Field(default=None, ge=0)
    privacy_ceiling: PrivacyClassification = PrivacyClassification.INTERNAL
    deadline_at_ms: int | None = Field(default=None, ge=0)
    monotonic_timeout_ms: int = Field(ge=1, le=86_400_000)
    cancellation_owner_id: UUID

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.parent_invocation_id == self.invocation_id:
            raise ValueError("GitHub tool invocation cannot parent itself")
        if self.allowed_data_sources != frozenset({GITHUB_CONNECTOR_ID}):
            raise ValueError("GitHub read request must bind the exact effective data source")
        return self

    @property
    def operation(self) -> GitHubReadOperation:
        return self.arguments.operation

    @property
    def tool_id(self) -> str:
        return self.operation.value


class GitHubSearchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    repository: str = Field(pattern=_REPOSITORY_PATTERN)
    default_branch: str | None = Field(default=None, pattern=_REF_PATTERN, max_length=255)
    visibility: GitHubVisibility = GitHubVisibility.PUBLIC
    description: str | None = Field(default=None, max_length=2_000)
    topics: tuple[str, ...] = Field(default=(), max_length=100)
    path: str | None = Field(default=None, max_length=1_024)
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = Field(default=None, max_length=2_000)
    match_count: int = Field(default=1, ge=1, le=10_000)
    source_reference: str = Field(min_length=1, max_length=2_048)

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("GitHub topics must be unique and canonically sorted")
        return value


class GitHubSearchProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: Literal["search"] = "search"
    query: str = Field(min_length=1, max_length=1_000)
    items: tuple[GitHubSearchItem, ...] = Field(max_length=100)
    total_count_lower_bound: int = Field(ge=0)
    truncated: bool
    truncation_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_search_shape(self) -> Self:
        if self.total_count_lower_bound < len(self.items):
            raise ValueError("GitHub search count cannot be smaller than projected items")
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("GitHub search truncation requires an explicit reason")
        references = tuple(item.source_reference for item in self.items)
        if len(references) != len(set(references)):
            raise ValueError("GitHub search projection contains duplicate source references")
        return self


class GitHubFileProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: Literal["file"] = "file"
    repository: str = Field(pattern=_REPOSITORY_PATTERN)
    visibility: GitHubVisibility = GitHubVisibility.PUBLIC
    ref: str = Field(pattern=_REF_PATTERN, max_length=255)
    resolved_ref_sha: str | None = Field(default=None, pattern=_SHA_PATTERN, max_length=64)
    path: str = Field(min_length=1, max_length=1_024)
    object_kind: GitHubObjectKind = GitHubObjectKind.REGULAR
    blob_sha: str = Field(pattern=_SHA_PATTERN, max_length=64)
    byte_count: int = Field(ge=0)
    text: str | None = Field(default=None, max_length=250_000)
    text_disposition: GitHubTextDisposition
    truncation_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_text_shape(self) -> Self:
        if self.text_disposition == GitHubTextDisposition.COMPLETE:
            if (
                self.object_kind != GitHubObjectKind.REGULAR
                or self.text is None
                or self.truncation_reason is not None
            ):
                raise ValueError("non-regular GitHub objects require metadata-only handling")
            if len(self.text.encode("utf-8")) != self.byte_count:
                raise ValueError("complete GitHub file byte count must match UTF-8 text")
        elif self.text_disposition == GitHubTextDisposition.TRUNCATED:
            if (
                self.object_kind != GitHubObjectKind.REGULAR
                or self.text is None
                or self.truncation_reason is None
            ):
                raise ValueError(
                    "truncated GitHub file projection requires regular text and reason"
                )
            if len(self.text.encode("utf-8")) > self.byte_count:
                raise ValueError("truncated GitHub text cannot exceed source byte count")
        elif self.text is not None or self.truncation_reason is None:
            raise ValueError("metadata-only or binary GitHub file requires no text and a reason")
        if (
            self.object_kind == GitHubObjectKind.BINARY
            and self.text_disposition != GitHubTextDisposition.BINARY_REJECTED
        ):
            raise ValueError("binary GitHub object must use binary_rejected disposition")
        if (
            self.object_kind
            in {
                GitHubObjectKind.SYMLINK,
                GitHubObjectKind.SUBMODULE,
                GitHubObjectKind.LFS_POINTER,
            }
            and self.text_disposition != GitHubTextDisposition.METADATA_ONLY
        ):
            raise ValueError("non-regular GitHub object must remain metadata-only")
        return self


class GitHubIssueProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: Literal["issue"] = "issue"
    repository: str = Field(pattern=_REPOSITORY_PATTERN)
    visibility: GitHubVisibility = GitHubVisibility.PUBLIC
    issue_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    state: GitHubIssueState
    body: str | None = Field(default=None, max_length=250_000)
    labels: tuple[str, ...] = Field(default=(), max_length=100)
    author: str | None = Field(default=None, max_length=100)
    updated_at_ms: int = Field(ge=0)
    truncated: bool
    truncation_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_issue_shape(self) -> Self:
        if self.labels != tuple(sorted(set(self.labels))):
            raise ValueError("GitHub issue labels must be unique and canonically sorted")
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("GitHub issue truncation requires an explicit reason")
        return self


class GitHubReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    approvals: int = Field(default=0, ge=0)
    changes_requested: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    unresolved_threads: int = Field(default=0, ge=0)


class GitHubPullRequestProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: Literal["pull_request"] = "pull_request"
    repository: str = Field(pattern=_REPOSITORY_PATTERN)
    visibility: GitHubVisibility = GitHubVisibility.PUBLIC
    pull_request_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    state: GitHubPullRequestState
    draft: bool
    head_ref: str = Field(pattern=_REF_PATTERN, max_length=255)
    base_ref: str = Field(pattern=_REF_PATTERN, max_length=255)
    body: str | None = Field(default=None, max_length=250_000)
    check_state: GitHubCheckState
    review_summary: GitHubReviewSummary = Field(default_factory=GitHubReviewSummary)
    updated_at_ms: int = Field(ge=0)
    truncated: bool
    truncation_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_pull_request_shape(self) -> Self:
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("GitHub pull-request truncation requires an explicit reason")
        return self


type GitHubReadProjection = Annotated[
    GitHubSearchProjection
    | GitHubFileProjection
    | GitHubIssueProjection
    | GitHubPullRequestProjection,
    Field(discriminator="kind"),
]
_PROJECTION_ADAPTER: TypeAdapter[GitHubReadProjection] = TypeAdapter(GitHubReadProjection)


class GitHubReadProjectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = GITHUB_READ_CONTRACT_VERSION
    connector_id: Literal["github"] = GITHUB_CONNECTOR_ID
    tool_id: str = Field(min_length=1, max_length=128)
    projection: GitHubReadProjection
    projection_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    response_bytes: int = Field(ge=0, le=MAX_GITHUB_PROJECTION_BYTES)
    observed_at_ms: int = Field(ge=0)
    fresh_until_ms: int | None = Field(default=None, ge=0)
    cache_disposition: EvidenceCacheDisposition
    untrusted_source: Literal[True] = True
    tainted: Literal[True] = True
    citation_reference: str = Field(min_length=1, max_length=2_048)
    privacy: PrivacyClassification

    @field_validator("citation_reference")
    @classmethod
    def validate_citation_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("GitHub citation reference must be one bounded line")
        return normalized

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.tool_id not in {operation.value for operation in GitHubReadOperation}:
            raise ValueError("unknown GitHub read tool ID")
        if self.tool_id != _tool_id_for_projection(self.projection):
            raise ValueError("GitHub projection kind does not match tool ID")
        if self.fresh_until_ms is not None and self.fresh_until_ms < self.observed_at_ms:
            raise ValueError("GitHub freshness cannot precede observation time")
        if canonical_fingerprint(self.projection) != self.projection_sha256:
            raise ValueError("GitHub projection hash does not match typed projection")
        actual_bytes = canonical_size_bytes(self.projection)
        if actual_bytes != self.response_bytes:
            raise ValueError("GitHub projection byte count does not match typed projection")
        return self


def parse_github_arguments(payload: object) -> GitHubReadArguments:
    return _ARGUMENT_ADAPTER.validate_python(payload)


def parse_github_projection(payload: object) -> GitHubReadProjection:
    return _PROJECTION_ADAPTER.validate_python(payload)


def _tool_id_for_projection(projection: GitHubReadProjection) -> str:
    return {
        "search": GITHUB_SEARCH_TOOL_ID,
        "file": GITHUB_FETCH_FILE_TOOL_ID,
        "issue": GITHUB_FETCH_ISSUE_TOOL_ID,
        "pull_request": GITHUB_FETCH_PR_TOOL_ID,
    }[projection.kind]
