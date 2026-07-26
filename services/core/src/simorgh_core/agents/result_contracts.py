from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import canonical_fingerprint, canonical_size_bytes
from simorgh_core.agents.specialist_results import (
    SPECIALIST_PLAN_OUTPUT_CONTRACT,
    SpecialistPlanPayload,
)

RESULT_AUTHORITY_SCHEMA_VERSION: Literal[1] = 1
RESULT_SCHEMA_VERSION: Literal["1.0"] = "1.0"
MAX_AUTHORITATIVE_INLINE_RESULT_BYTES = 256_000
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
_MEDIA_TYPE_PATTERN = r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"


class ResultAuthorityError(RuntimeError):
    """Base class for deterministic result-authority failures."""


class ResultSchemaConflictError(ResultAuthorityError):
    pass


class UnknownResultSchemaError(ResultAuthorityError):
    pass


class ResultIdentityConflictError(ResultAuthorityError):
    pass


class ResultContractError(ResultAuthorityError):
    pass


class PrivacyClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"

    @property
    def rank(self) -> int:
        return list(PrivacyClassification).index(self)

    def require_at_least(self, minimum: PrivacyClassification) -> None:
        if self.rank < minimum.rank:
            raise ResultContractError("result privacy classification cannot be downgraded")

    @classmethod
    def strictest(cls, values: list[PrivacyClassification]) -> PrivacyClassification:
        return max(values, key=lambda value: value.rank, default=cls.PUBLIC)


class RetentionDisposition(StrEnum):
    TRANSIENT = "transient"
    SESSION = "session"
    PROJECT = "project"
    LONG_LIVED = "long_lived"
    LEGAL_HOLD = "legal_hold"


class ArtifactStorageDisposition(StrEnum):
    INLINE_BYTES = "inline_bytes"
    CORE_LOCAL_REFERENCE = "core_local_reference"
    PUBLIC_REFERENCE = "public_reference"


class EvidenceFreshness(StrEnum):
    CURRENT = "current"
    CACHED = "cached"
    STALE = "stale"
    UNKNOWN = "unknown"


class EvidenceCacheDisposition(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    MISS = "miss"
    HIT = "hit"
    BYPASSED_FRESHNESS = "bypassed_freshness"
    BYPASSED_POLICY = "bypassed_policy"


class EvidenceTaint(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    MIXED = "mixed"


class ResultReplayDisposition(StrEnum):
    FRESH = "fresh"
    REPLAYED = "replayed"


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1] = RESULT_AUTHORITY_SCHEMA_VERSION
    artifact_id: UUID
    sha256: str = Field(min_length=64, max_length=64, pattern=_HASH_PATTERN)
    media_type: str = Field(min_length=3, max_length=255, pattern=_MEDIA_TYPE_PATTERN)
    size_bytes: int = Field(ge=0, le=100_000_000)
    request_id: UUID
    invocation_id: UUID
    producer_agent_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    producer_agent_version: str = Field(
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32
    )
    privacy: PrivacyClassification
    retention: RetentionDisposition
    storage: ArtifactStorageDisposition
    storage_reference: str | None = Field(default=None, max_length=2_000)
    created_at_ms: int = Field(ge=0)
    expires_at_ms: int | None = Field(default=None, ge=0)
    encryption_key_reference: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_storage_shape(self) -> Self:
        if self.expires_at_ms is not None and self.expires_at_ms <= self.created_at_ms:
            raise ValueError("artifact expiry must be later than creation time")
        if self.storage == ArtifactStorageDisposition.INLINE_BYTES:
            if self.storage_reference is not None:
                raise ValueError("inline artifact cannot carry a storage reference")
        elif self.storage_reference is None or not self.storage_reference.strip():
            raise ValueError("referenced artifact requires a storage reference")
        if (
            self.storage == ArtifactStorageDisposition.PUBLIC_REFERENCE
            and self.privacy.rank > PrivacyClassification.INTERNAL.rank
        ):
            raise ValueError("private artifact cannot use a public storage disposition")
        if self.retention == RetentionDisposition.LEGAL_HOLD and self.expires_at_ms is not None:
            raise ValueError("legal-hold artifact cannot expire")
        return self


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1] = RESULT_AUTHORITY_SCHEMA_VERSION
    evidence_id: UUID
    source_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    connector_id: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN, max_length=128)
    tool_id: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN, max_length=128)
    retrieved_at_ms: int = Field(ge=0)
    freshness: EvidenceFreshness
    cache: EvidenceCacheDisposition = EvidenceCacheDisposition.NOT_APPLICABLE
    taint: EvidenceTaint
    content_sha256: str = Field(min_length=64, max_length=64, pattern=_HASH_PATTERN)
    display_reference: str = Field(min_length=1, max_length=2_000)
    artifact_id: UUID | None = None
    privacy: PrivacyClassification

    @field_validator("display_reference")
    @classmethod
    def normalize_display_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("evidence display reference cannot be empty")
        return normalized


class AuthoritativeResultRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1] = RESULT_AUTHORITY_SCHEMA_VERSION
    result_id: UUID
    request_id: UUID
    invocation_id: UUID
    producer_agent_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    producer_agent_version: str = Field(
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32
    )
    output_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    result_schema_version: Literal["1.0"] = RESULT_SCHEMA_VERSION
    family: Literal["plan"] = "plan"
    payload: SpecialistPlanPayload
    payload_sha256: str = Field(min_length=64, max_length=64, pattern=_HASH_PATTERN)
    invocation_result_sha256: str = Field(min_length=64, max_length=64, pattern=_HASH_PATTERN)
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=256)
    evidence: tuple[EvidenceReference, ...] = Field(default=(), max_length=1_024)
    committed_usage: UsageVector = Field(default_factory=UsageVector)
    privacy: PrivacyClassification
    retention: RetentionDisposition
    created_at_ms: int = Field(ge=0)
    completed_at_ms: int = Field(ge=0)
    canonical_sha256: str = Field(min_length=64, max_length=64, pattern=_HASH_PATTERN)
    replay: ResultReplayDisposition = ResultReplayDisposition.FRESH

    def authority_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"canonical_sha256", "replay"})

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.completed_at_ms < self.created_at_ms:
            raise ValueError("result completion cannot precede result creation")
        if self.output_contract != SPECIALIST_PLAN_OUTPUT_CONTRACT:
            raise ValueError("plan result requires the typed-plan output contract")
        if canonical_fingerprint(self.payload) != self.payload_sha256:
            raise ValueError("result payload hash does not match typed payload")
        if canonical_size_bytes(self.payload) > MAX_AUTHORITATIVE_INLINE_RESULT_BYTES:
            raise ValueError("authoritative inline result exceeds size limit")
        if canonical_fingerprint(self.authority_payload()) != self.canonical_sha256:
            raise ValueError("authoritative result hash does not match record")
        if len({item.artifact_id for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("artifact IDs must be unique within one result")
        if len({item.evidence_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("evidence IDs must be unique within one result")
        artifact_ids = {item.artifact_id for item in self.artifacts}
        linked_privacy = [self.privacy]
        for artifact in self.artifacts:
            if (
                artifact.request_id != self.request_id
                or artifact.invocation_id != self.invocation_id
                or artifact.producer_agent_id != self.producer_agent_id
                or artifact.producer_agent_version != self.producer_agent_version
            ):
                raise ValueError("artifact producer identity does not match result")
            linked_privacy.append(artifact.privacy)
        for evidence in self.evidence:
            if evidence.artifact_id is not None and evidence.artifact_id not in artifact_ids:
                raise ValueError("evidence references an artifact outside the result")
            linked_privacy.append(evidence.privacy)
        if PrivacyClassification.strictest(linked_privacy) != self.privacy:
            raise ValueError("result privacy must equal the strictest linked classification")
        return self
