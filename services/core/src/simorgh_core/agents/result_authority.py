from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Literal, Protocol, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.invocations import canonical_fingerprint, canonical_size_bytes
from simorgh_core.agents.specialist_execution import (
    SpecialistExecutionOutcome,
    SpecialistExecutionResult,
)
from simorgh_core.agents.specialist_results import (
    SPECIALIST_PLAN_OUTPUT_CONTRACT,
    SpecialistPlanPayload,
)

RESULT_AUTHORITY_SCHEMA_VERSION: Literal["1.0"] = "1.0"
SPECIALIST_PLAN_RESULT_SCHEMA_ID: Literal[
    "simorgh.specialist-plan-result"
] = "simorgh.specialist-plan-result"
SPECIALIST_PLAN_RESULT_SCHEMA_VERSION: Literal["1.0"] = "1.0"
MAX_RESULT_INLINE_BYTES = 256_000
MAX_RESULT_REFERENCES = 256
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
_MEDIA_TYPE_PATTERN = r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"
_AGENT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_POLICY_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"


class ResultAuthorityError(RuntimeError):
    """Base class for deterministic typed-result authority failures."""


class DuplicateResultSchemaError(ResultAuthorityError):
    pass


class UnknownResultSchemaError(ResultAuthorityError):
    pass


class ResultContractError(ResultAuthorityError):
    pass


class PrivacyClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class RetentionDisposition(StrEnum):
    TRANSIENT = "transient"
    SESSION = "session"
    PROJECT = "project"
    LONG_LIVED = "long_lived"
    LEGAL_HOLD = "legal_hold"


class ArtifactStorageDisposition(StrEnum):
    TEST_FIXTURE = "test_fixture"
    LOCAL_REFERENCE = "local_reference"
    PRIVATE_REFERENCE = "private_reference"
    PUBLIC_REFERENCE = "public_reference"


class EvidenceCacheDisposition(StrEnum):
    LIVE = "live"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    STALE = "stale"
    UNKNOWN = "unknown"


class ResultReplayDisposition(StrEnum):
    FRESH = "fresh"
    REPLAYED = "replayed"


class UncertaintyDisposition(StrEnum):
    NONE = "none"
    DECLARED = "declared"
    UNVERIFIED = "unverified"


_PRIVACY_RANK = {
    PrivacyClassification.PUBLIC: 0,
    PrivacyClassification.INTERNAL: 1,
    PrivacyClassification.PRIVATE: 2,
    PrivacyClassification.SENSITIVE: 3,
    PrivacyClassification.RESTRICTED: 4,
}
_RETENTION_RANK = {
    RetentionDisposition.TRANSIENT: 0,
    RetentionDisposition.SESSION: 1,
    RetentionDisposition.PROJECT: 2,
    RetentionDisposition.LONG_LIVED: 3,
    RetentionDisposition.LEGAL_HOLD: 4,
}


def privacy_is_at_least(
    candidate: PrivacyClassification,
    minimum: PrivacyClassification,
) -> bool:
    return _PRIVACY_RANK[candidate] >= _PRIVACY_RANK[minimum]


def retention_is_at_least(
    candidate: RetentionDisposition,
    minimum: RetentionDisposition,
) -> bool:
    return _RETENTION_RANK[candidate] >= _RETENTION_RANK[minimum]


def strictest_privacy(
    values: Iterable[PrivacyClassification],
    *,
    default: PrivacyClassification = PrivacyClassification.INTERNAL,
) -> PrivacyClassification:
    strictest = default
    for value in values:
        if _PRIVACY_RANK[value] > _PRIVACY_RANK[strictest]:
            strictest = value
    return strictest


def strictest_retention(
    values: Iterable[RetentionDisposition],
    *,
    default: RetentionDisposition = RetentionDisposition.PROJECT,
) -> RetentionDisposition:
    strictest = default
    for value in values:
        if _RETENTION_RANK[value] > _RETENTION_RANK[strictest]:
            strictest = value
    return strictest


def _normalize_bounded_reference(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise ValueError("reference metadata must be one bounded non-empty line")
    return normalized


class ArtifactReference(BaseModel):
    """Immutable metadata authority; artifact bytes never enter this record."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = RESULT_AUTHORITY_SCHEMA_VERSION
    artifact_id: UUID
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    media_type: str = Field(min_length=3, max_length=255, pattern=_MEDIA_TYPE_PATTERN)
    byte_size: int = Field(ge=0, le=2_147_483_647)
    request_id: UUID
    invocation_id: UUID
    producer_agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    producer_agent_version: str = Field(pattern=_POLICY_VERSION_PATTERN, max_length=32)
    privacy: PrivacyClassification
    retention: RetentionDisposition
    storage_disposition: ArtifactStorageDisposition
    storage_reference: str | None = Field(default=None, min_length=1, max_length=2_048)
    created_at_ms: int = Field(ge=0)
    expires_at_ms: int | None = Field(default=None, ge=0)
    encryption_key_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=_RESOURCE_ID_PATTERN,
    )

    @field_validator("storage_reference", "encryption_key_reference")
    @classmethod
    def normalize_references(cls, value: str | None) -> str | None:
        return _normalize_bounded_reference(value)

    @model_validator(mode="after")
    def validate_artifact_shape(self) -> Self:
        if self.expires_at_ms is not None and self.expires_at_ms <= self.created_at_ms:
            raise ValueError("artifact expiry must be later than creation time")
        if self.retention == RetentionDisposition.LEGAL_HOLD and self.expires_at_ms is not None:
            raise ValueError("legal-hold artifact cannot carry an expiry")
        if self.storage_disposition == ArtifactStorageDisposition.TEST_FIXTURE:
            if self.storage_reference is not None:
                raise ValueError("test fixture artifact cannot carry a storage reference")
        elif self.storage_reference is None:
            raise ValueError("referenced artifact requires a storage reference")
        if (
            self.storage_disposition == ArtifactStorageDisposition.PUBLIC_REFERENCE
            and self.privacy != PrivacyClassification.PUBLIC
        ):
            raise ValueError("non-public artifact cannot use public storage")
        return self


class EvidenceReference(BaseModel):
    """Presentation-neutral metadata about one observed or retrieved source."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = RESULT_AUTHORITY_SCHEMA_VERSION
    evidence_id: UUID
    source_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    connector_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    tool_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    observed_at_ms: int = Field(ge=0)
    fresh_until_ms: int | None = Field(default=None, ge=0)
    cache_disposition: EvidenceCacheDisposition
    untrusted_source: bool = False
    tainted: bool = False
    projection_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    citation_reference: str = Field(min_length=1, max_length=2_048)
    artifact_id: UUID | None = None
    privacy: PrivacyClassification

    @field_validator("citation_reference")
    @classmethod
    def normalize_citation_reference(cls, value: str) -> str:
        normalized = _normalize_bounded_reference(value)
        if normalized is None:
            raise ValueError("evidence citation reference cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        if self.fresh_until_ms is not None and self.fresh_until_ms < self.observed_at_ms:
            raise ValueError("evidence freshness cannot precede observation time")
        if self.untrusted_source and not self.tainted:
            raise ValueError("untrusted evidence must retain taint metadata")
        return self


class ResultUncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    disposition: UncertaintyDisposition
    unresolved_risks: tuple[str, ...] = Field(default=(), max_length=128)
    verification_requirements: tuple[str, ...] = Field(default=(), max_length=128)

    @field_validator("unresolved_risks", "verification_requirements")
    @classmethod
    def validate_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item or len(item) > 2_000 for item in normalized):
            raise ValueError("result uncertainty items must be in 1..2000 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("result uncertainty items must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        has_requirements = bool(self.unresolved_risks or self.verification_requirements)
        if self.disposition == UncertaintyDisposition.NONE and has_requirements:
            raise ValueError("uncertainty none cannot contain unresolved requirements")
        if self.disposition != UncertaintyDisposition.NONE and not has_requirements:
            raise ValueError("declared uncertainty requires risks or verification requirements")
        return self


class AuthoritativeSpecialistResult(BaseModel):
    """Immutable typed result, evidence, and artifact metadata authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = RESULT_AUTHORITY_SCHEMA_VERSION
    result_id: UUID
    request_id: UUID
    invocation_id: UUID
    producer_agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    producer_agent_version: str = Field(pattern=_POLICY_VERSION_PATTERN, max_length=32)
    output_contract: Literal["simorgh.typed-plan.v1"] = SPECIALIST_PLAN_OUTPUT_CONTRACT
    result_schema_id: Literal[
        "simorgh.specialist-plan-result"
    ] = SPECIALIST_PLAN_RESULT_SCHEMA_ID
    result_schema_version: Literal["1.0"] = SPECIALIST_PLAN_RESULT_SCHEMA_VERSION
    family: Literal["specialist_plan"] = "specialist_plan"
    payload: SpecialistPlanPayload
    artifacts: tuple[ArtifactReference, ...] = Field(
        default=(),
        max_length=MAX_RESULT_REFERENCES,
    )
    evidence: tuple[EvidenceReference, ...] = Field(
        default=(),
        max_length=MAX_RESULT_REFERENCES,
    )
    committed_usage_invocation_id: UUID
    uncertainty: ResultUncertainty
    privacy: PrivacyClassification
    retention: RetentionDisposition
    created_at_ms: int = Field(ge=0)
    completed_at_ms: int = Field(ge=0)
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    replay: ResultReplayDisposition = ResultReplayDisposition.FRESH

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        if self.completed_at_ms < self.created_at_ms:
            raise ValueError("result completion cannot precede creation")
        if self.committed_usage_invocation_id != self.invocation_id:
            raise ValueError("result usage reference must point to the producer invocation")
        if self.uncertainty.unresolved_risks != self.payload.unresolved_risks:
            raise ValueError("result unresolved risks must match the typed payload")
        if (
            self.uncertainty.verification_requirements
            != self.payload.verification_requirements
        ):
            raise ValueError("result verification requirements must match the typed payload")

        artifact_ids = tuple(item.artifact_id for item in self.artifacts)
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("result artifact IDs must be unique")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("result evidence IDs must be unique")
        if artifact_ids != tuple(sorted(artifact_ids, key=str)):
            raise ValueError("result artifacts must be canonically ordered")
        if evidence_ids != tuple(sorted(evidence_ids, key=str)):
            raise ValueError("result evidence must be canonically ordered")

        available_artifacts = set(artifact_ids)
        expected_identity = (
            self.request_id,
            self.invocation_id,
            self.producer_agent_id,
            self.producer_agent_version,
        )
        for artifact in self.artifacts:
            producer_identity = (
                artifact.request_id,
                artifact.invocation_id,
                artifact.producer_agent_id,
                artifact.producer_agent_version,
            )
            if producer_identity != expected_identity:
                raise ValueError("artifact producer identity does not match the result")
            if not privacy_is_at_least(self.privacy, artifact.privacy):
                raise ValueError("result privacy cannot downgrade artifact classification")
            if not retention_is_at_least(self.retention, artifact.retention):
                raise ValueError("result retention cannot be shorter than artifact retention")
        for item in self.evidence:
            if item.artifact_id is not None and item.artifact_id not in available_artifacts:
                raise ValueError("evidence references an artifact outside the result")
            if not privacy_is_at_least(self.privacy, item.privacy):
                raise ValueError("result privacy cannot downgrade evidence classification")

        if canonical_size_bytes(self.payload) > MAX_RESULT_INLINE_BYTES:
            raise ValueError("typed result payload exceeds the inline authority limit")
        if result_canonical_sha256(self) != self.canonical_sha256:
            raise ValueError("result canonical hash does not match authoritative content")
        return self


class ResultSchemaHandler(Protocol):
    @property
    def schema_id(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    @property
    def output_contract(self) -> str: ...

    @property
    def family(self) -> str: ...

    def validate_payload(self, payload: object) -> BaseModel: ...


class SpecialistPlanResultSchema:
    @property
    def schema_id(self) -> str:
        return SPECIALIST_PLAN_RESULT_SCHEMA_ID

    @property
    def schema_version(self) -> str:
        return SPECIALIST_PLAN_RESULT_SCHEMA_VERSION

    @property
    def output_contract(self) -> str:
        return SPECIALIST_PLAN_OUTPUT_CONTRACT

    @property
    def family(self) -> str:
        return "specialist_plan"

    def validate_payload(self, payload: object) -> SpecialistPlanPayload:
        return SpecialistPlanPayload.model_validate(payload)


class ResultSchemaRegistry:
    """Immutable exact-version registry for authoritative result families."""

    def __init__(self, handlers: Iterable[ResultSchemaHandler] = ()) -> None:
        compiled: dict[tuple[str, str], ResultSchemaHandler] = {}
        for handler in handlers:
            if re.fullmatch(_RESOURCE_ID_PATTERN, handler.schema_id) is None:
                raise ResultContractError("result schema ID is invalid")
            if re.fullmatch(_POLICY_VERSION_PATTERN, handler.schema_version) is None:
                raise ResultContractError("result schema version is invalid")
            if re.fullmatch(_RESOURCE_ID_PATTERN, handler.output_contract) is None:
                raise ResultContractError("result output contract is invalid")
            key = (handler.schema_id, handler.schema_version)
            if key in compiled:
                raise DuplicateResultSchemaError(
                    f"result schema {key!r} was registered more than once"
                )
            compiled[key] = handler
        self._handlers = compiled

    def require(
        self,
        *,
        schema_id: str,
        schema_version: str,
        output_contract: str,
        family: str,
    ) -> ResultSchemaHandler:
        handler = self._handlers.get((schema_id, schema_version))
        if handler is None:
            raise UnknownResultSchemaError(
                f"result schema {(schema_id, schema_version)!r} is not registered"
            )
        if handler.output_contract != output_contract or handler.family != family:
            raise ResultContractError(
                "registered result schema does not match output contract or family"
            )
        return handler


def default_result_schema_registry() -> ResultSchemaRegistry:
    return ResultSchemaRegistry((SpecialistPlanResultSchema(),))


class RenderedPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    locale: str = Field(min_length=2, max_length=32)
    text: str = Field(min_length=1, max_length=32_000)
    result_id: UUID
    result_canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    authoritative: Literal[False] = False


class ResultRenderer(Protocol):
    def render(
        self,
        result: AuthoritativeSpecialistResult,
        *,
        locale: str = "fa-IR",
        max_characters: int = 32_000,
    ) -> RenderedPresentation: ...


class PersianSpecialistPlanRenderer:
    """Deterministic Persian rendering outside the result authority fields."""

    def render(
        self,
        result: AuthoritativeSpecialistResult,
        *,
        locale: str = "fa-IR",
        max_characters: int = 32_000,
    ) -> RenderedPresentation:
        normalized_locale = locale.strip() or "fa-IR"
        if normalized_locale not in {"fa", "fa-IR"}:
            normalized_locale = "fa-IR"
        lines = [result.payload.summary]
        if result.payload.steps:
            lines.extend(["", "مراحل:"])
            lines.extend(
                f"{index}. {step}"
                for index, step in enumerate(result.payload.steps, start=1)
            )
        if result.payload.unresolved_risks:
            lines.extend(["", "ریسک‌های حل‌نشده:"])
            lines.extend(f"- {item}" for item in result.payload.unresolved_risks)
        if result.payload.verification_requirements:
            lines.extend(["", "نیازهای راستی‌آزمایی:"])
            lines.extend(f"- {item}" for item in result.payload.verification_requirements)
        text = "\n".join(lines)
        if len(text) > max_characters:
            raise ResultContractError("rendered result exceeds the presentation limit")
        return RenderedPresentation(
            locale=normalized_locale,
            text=text,
            result_id=result.result_id,
            result_canonical_sha256=result.canonical_sha256,
        )


def build_test_artifact_reference(
    *,
    artifact_id: UUID,
    content: bytes,
    media_type: str,
    request_id: UUID,
    invocation_id: UUID,
    producer_agent_id: str,
    producer_agent_version: str,
    privacy: PrivacyClassification,
    retention: RetentionDisposition,
    created_at_ms: int,
    expires_at_ms: int | None = None,
) -> ArtifactReference:
    """Build metadata for deterministic fake bytes without persisting those bytes."""

    return ArtifactReference(
        artifact_id=artifact_id,
        canonical_sha256=hashlib.sha256(content).hexdigest(),
        media_type=media_type,
        byte_size=len(content),
        request_id=request_id,
        invocation_id=invocation_id,
        producer_agent_id=producer_agent_id,
        producer_agent_version=producer_agent_version,
        privacy=privacy,
        retention=retention,
        storage_disposition=ArtifactStorageDisposition.TEST_FIXTURE,
        created_at_ms=created_at_ms,
        expires_at_ms=expires_at_ms,
    )


def validate_artifact_bytes(reference: ArtifactReference, content: bytes) -> None:
    if len(content) != reference.byte_size:
        raise ResultContractError("artifact bytes do not match declared size")
    if hashlib.sha256(content).hexdigest() != reference.canonical_sha256:
        raise ResultContractError("artifact bytes do not match declared hash")


def stable_result_id(
    *,
    invocation_id: UUID,
    result_schema_id: str = SPECIALIST_PLAN_RESULT_SCHEMA_ID,
    result_schema_version: str = SPECIALIST_PLAN_RESULT_SCHEMA_VERSION,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"simorgh-result:{invocation_id}:{result_schema_id}:{result_schema_version}",
    )


def result_authoritative_payload(
    result: AuthoritativeSpecialistResult,
) -> dict[str, object]:
    payload: dict[str, object] = result.model_dump(mode="json")
    payload.pop("canonical_sha256", None)
    payload.pop("replay", None)
    return payload


def result_canonical_sha256(result: AuthoritativeSpecialistResult) -> str:
    return canonical_fingerprint(result_authoritative_payload(result))


def build_authoritative_plan_result(
    *,
    execution_result: SpecialistExecutionResult,
    registry: ResultSchemaRegistry,
    privacy: PrivacyClassification = PrivacyClassification.INTERNAL,
    retention: RetentionDisposition = RetentionDisposition.PROJECT,
    artifacts: Iterable[ArtifactReference] = (),
    evidence: Iterable[EvidenceReference] = (),
) -> AuthoritativeSpecialistResult:
    if execution_result.outcome != SpecialistExecutionOutcome.COMPLETED:
        raise ResultContractError("only a completed specialist result can be terminalized")
    if execution_result.payload is None:
        raise ResultContractError("completed specialist result has no typed payload")
    handler = registry.require(
        schema_id=SPECIALIST_PLAN_RESULT_SCHEMA_ID,
        schema_version=SPECIALIST_PLAN_RESULT_SCHEMA_VERSION,
        output_contract=execution_result.output_contract,
        family="specialist_plan",
    )
    payload = SpecialistPlanPayload.model_validate(
        handler.validate_payload(execution_result.payload).model_dump(mode="json")
    )
    uncertainty = ResultUncertainty(
        disposition=(
            UncertaintyDisposition.DECLARED
            if payload.unresolved_risks or payload.verification_requirements
            else UncertaintyDisposition.NONE
        ),
        unresolved_risks=payload.unresolved_risks,
        verification_requirements=payload.verification_requirements,
    )
    ordered_artifacts = tuple(sorted(artifacts, key=lambda item: str(item.artifact_id)))
    ordered_evidence = tuple(sorted(evidence, key=lambda item: str(item.evidence_id)))
    effective_privacy = strictest_privacy(
        (
            privacy,
            *(item.privacy for item in ordered_artifacts),
            *(item.privacy for item in ordered_evidence),
        ),
        default=privacy,
    )
    effective_retention = strictest_retention(
        (retention, *(item.retention for item in ordered_artifacts)),
        default=retention,
    )
    provisional = AuthoritativeSpecialistResult.model_construct(
        schema_version=RESULT_AUTHORITY_SCHEMA_VERSION,
        result_id=stable_result_id(invocation_id=execution_result.invocation_id),
        request_id=execution_result.request_id,
        invocation_id=execution_result.invocation_id,
        producer_agent_id=execution_result.agent_id,
        producer_agent_version=execution_result.agent_version,
        output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
        result_schema_id=SPECIALIST_PLAN_RESULT_SCHEMA_ID,
        result_schema_version=SPECIALIST_PLAN_RESULT_SCHEMA_VERSION,
        family="specialist_plan",
        payload=payload,
        artifacts=ordered_artifacts,
        evidence=ordered_evidence,
        committed_usage_invocation_id=execution_result.invocation_id,
        uncertainty=uncertainty,
        privacy=effective_privacy,
        retention=effective_retention,
        created_at_ms=execution_result.started_at_ms,
        completed_at_ms=execution_result.completed_at_ms,
        canonical_sha256="0" * 64,
        replay=ResultReplayDisposition.FRESH,
    )
    canonical_sha256 = result_canonical_sha256(provisional)
    return AuthoritativeSpecialistResult.model_validate(
        provisional.model_copy(update={"canonical_sha256": canonical_sha256}).model_dump(
            mode="json"
        )
    )
