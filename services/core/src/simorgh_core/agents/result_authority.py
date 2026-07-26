from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.invocations import (
    InvocationPayloadError,
    canonical_fingerprint,
    canonical_size_bytes,
)
from simorgh_core.agents.specialist_results import (
    SPECIALIST_PLAN_OUTPUT_CONTRACT,
    SpecialistPlanPayload,
)

RESULT_AUTHORITY_SCHEMA_VERSION: Literal["1.0"] = "1.0"
MAX_INLINE_RESULT_BYTES = 256_000
MAX_PRESENTATION_CHARACTERS = 32_000
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_AGENT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
_MEDIA_TYPE_PATTERN = r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"


class ResultAuthorityError(RuntimeError):
    """Base class for deterministic result-authority failures."""


class DuplicateResultSchemaError(ResultAuthorityError):
    pass


class UnknownResultSchemaError(ResultAuthorityError):
    pass


class ResultConflictError(ResultAuthorityError):
    pass


class ResultNotFoundError(ResultAuthorityError):
    pass


class ResultStoreClosedError(ResultAuthorityError):
    pass


class UnsupportedResultLocaleError(ResultAuthorityError):
    pass


class PrivacyClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


_PRIVACY_RANK: dict[PrivacyClassification, int] = {
    PrivacyClassification.PUBLIC: 0,
    PrivacyClassification.INTERNAL: 1,
    PrivacyClassification.PRIVATE: 2,
    PrivacyClassification.SENSITIVE: 3,
    PrivacyClassification.RESTRICTED: 4,
}


class RetentionClass(StrEnum):
    TRANSIENT = "transient"
    SESSION = "session"
    PROJECT = "project"
    LONG_LIVED = "long_lived"
    LEGAL_HOLD = "legal_hold"


class ArtifactStorageDisposition(StrEnum):
    CORE_LOCAL = "core_local"
    EXTERNAL_PRIVATE = "external_private"
    PUBLIC = "public"


class EvidenceFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class EvidenceCacheDisposition(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    MISS = "miss"
    HIT = "hit"
    BYPASSED_FRESHNESS = "bypassed_freshness"
    BYPASSED_POLICY = "bypassed_policy"


class EvidenceTaint(StrEnum):
    CLEAN = "clean"
    UNTRUSTED = "untrusted"
    TAINTED = "tainted"


class ResultReplayDisposition(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"


class ResultProducer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    request_id: UUID
    invocation_id: UUID
    agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    agent_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = RESULT_AUTHORITY_SCHEMA_VERSION
    artifact_id: UUID
    sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_PATTERN)
    media_type: str = Field(min_length=3, max_length=255, pattern=_MEDIA_TYPE_PATTERN)
    size_bytes: int = Field(ge=1, le=1_000_000_000)
    producer: ResultProducer
    privacy: PrivacyClassification
    retention: RetentionClass
    storage_disposition: ArtifactStorageDisposition
    storage_reference: str = Field(min_length=1, max_length=1_000)
    created_at_ms: int = Field(ge=0)
    encrypted: bool = False
    key_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=_RESOURCE_ID_PATTERN,
    )

    @model_validator(mode="after")
    def validate_storage_policy(self) -> ArtifactReference:
        if (
            self.storage_disposition == ArtifactStorageDisposition.PUBLIC
            and self.privacy != PrivacyClassification.PUBLIC
        ):
            raise ValueError("non-public artifact cannot use public storage disposition")
        if self.encrypted and self.key_reference is None:
            raise ValueError("encrypted artifact requires a key reference")
        if not self.encrypted and self.key_reference is not None:
            raise ValueError("unencrypted artifact cannot contain a key reference")
        return self


class EvidenceReference(BaseModel):
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
    retrieved_at_ms: int = Field(ge=0)
    freshness: EvidenceFreshness
    cache: EvidenceCacheDisposition = EvidenceCacheDisposition.NOT_APPLICABLE
    taint: EvidenceTaint
    projection_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )
    citation_reference: str = Field(min_length=1, max_length=1_000)
    artifact_id: UUID | None = None
    privacy: PrivacyClassification


class SpecialistResultRecord(BaseModel):
    """Immutable authoritative result separate from presentation and invocation state."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    authority_schema_version: Literal["1.0"] = RESULT_AUTHORITY_SCHEMA_VERSION
    result_id: UUID
    producer: ResultProducer
    output_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    result_schema_version: str = Field(pattern=r"^[0-9]+\.[0-9]+$", max_length=16)
    payload: SpecialistPlanPayload
    payload_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=256)
    evidence: tuple[EvidenceReference, ...] = Field(default=(), max_length=512)
    unresolved_risks: tuple[str, ...] = Field(default=(), max_length=128)
    verification_requirements: tuple[str, ...] = Field(default=(), max_length=128)
    invocation_usage_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )
    invocation_result_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )
    privacy: PrivacyClassification
    retention: RetentionClass
    created_at_ms: int = Field(ge=0)
    completed_at_ms: int = Field(ge=0)
    result_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )

    @model_validator(mode="after")
    def validate_authority_shape(self) -> SpecialistResultRecord:
        if self.completed_at_ms < self.created_at_ms:
            raise ValueError("result completion cannot precede creation")
        if self.output_contract != SPECIALIST_PLAN_OUTPUT_CONTRACT:
            raise ValueError("plan payload requires the typed-plan output contract")
        if self.result_schema_version != self.payload.schema_version:
            raise ValueError("result schema version does not match payload")
        if canonical_size_bytes(self.payload) > MAX_INLINE_RESULT_BYTES:
            raise ValueError("inline specialist result exceeds the authority limit")
        if canonical_fingerprint(self.payload) != self.payload_sha256:
            raise ValueError("payload hash does not match typed payload")
        if self.unresolved_risks != self.payload.unresolved_risks:
            raise ValueError("record risks must match the typed payload")
        if self.verification_requirements != self.payload.verification_requirements:
            raise ValueError("record verification requirements must match the typed payload")
        self._validate_reference_identity()
        self._validate_privacy()
        if canonical_fingerprint(self._hash_payload()) != self.result_sha256:
            raise ValueError("result hash does not match immutable authority content")
        return self

    def _hash_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("result_sha256", None)
        return payload

    def _validate_reference_identity(self) -> None:
        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("artifact IDs must be unique within a result")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence IDs must be unique within a result")
        available_artifacts = set(artifact_ids)
        for artifact in self.artifacts:
            if artifact.producer != self.producer:
                raise ValueError("artifact producer does not match result producer")
            if artifact.created_at_ms > self.completed_at_ms:
                raise ValueError("artifact cannot be created after result completion")
        for item in self.evidence:
            if item.retrieved_at_ms > self.completed_at_ms:
                raise ValueError("evidence retrieval cannot follow result completion")
            if item.artifact_id is not None and item.artifact_id not in available_artifacts:
                raise ValueError("evidence references an artifact outside the result")

    def _validate_privacy(self) -> None:
        child_privacy = [
            *(artifact.privacy for artifact in self.artifacts),
            *(item.privacy for item in self.evidence),
        ]
        if child_privacy and _PRIVACY_RANK[self.privacy] < max(
            _PRIVACY_RANK[value] for value in child_privacy
        ):
            raise ValueError("result privacy cannot be weaker than child references")


class ResultWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    disposition: ResultReplayDisposition
    record: SpecialistResultRecord


@dataclass(frozen=True, slots=True)
class ResultSchemaRegistration:
    output_contract: str
    schema_version: str
    payload_model: type[BaseModel]

    def __post_init__(self) -> None:
        if re.fullmatch(_RESOURCE_ID_PATTERN, self.output_contract) is None:
            raise ValueError("result output contract is invalid")
        if re.fullmatch(r"^[0-9]+\.[0-9]+$", self.schema_version) is None:
            raise ValueError("result schema version is invalid")
        if not issubclass(self.payload_model, BaseModel):
            raise TypeError("result payload model must extend BaseModel")

    @property
    def identity(self) -> tuple[str, str]:
        return (self.output_contract, self.schema_version)

    def validate(self, payload: BaseModel | dict[str, Any]) -> BaseModel:
        raw = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        return self.payload_model.model_validate(raw)


class ResultSchemaRegistry:
    """Immutable exact-version registry for authoritative result payloads."""

    def __init__(self, registrations: Iterable[ResultSchemaRegistration]) -> None:
        compiled: dict[tuple[str, str], ResultSchemaRegistration] = {}
        for registration in registrations:
            if registration.identity in compiled:
                raise DuplicateResultSchemaError(
                    f"result schema {registration.identity!r} was registered more than once"
                )
            compiled[registration.identity] = registration
        self._registrations = compiled

    def get(self, *, output_contract: str, schema_version: str) -> ResultSchemaRegistration:
        registration = self._registrations.get((output_contract, schema_version))
        if registration is None:
            raise UnknownResultSchemaError(
                f"result schema {(output_contract, schema_version)!r} is not registered"
            )
        return registration

    def validate(
        self,
        *,
        output_contract: str,
        schema_version: str,
        payload: BaseModel | dict[str, Any],
    ) -> BaseModel:
        return self.get(
            output_contract=output_contract,
            schema_version=schema_version,
        ).validate(payload)


class ResultStore(Protocol):
    def put(self, record: SpecialistResultRecord) -> ResultWrite: ...

    def get(self, result_id: UUID) -> SpecialistResultRecord: ...

    def get_for_invocation(self, invocation_id: UUID) -> SpecialistResultRecord: ...

    def load(self) -> tuple[SpecialistResultRecord, ...]: ...

    def close(self) -> None: ...


class InMemoryResultStore:
    """Process-local immutable authority used before the SQLite increment."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[UUID, SpecialistResultRecord] = {}
        self._invocation_index: dict[UUID, UUID] = {}
        self._closed = False

    def put(self, record: SpecialistResultRecord) -> ResultWrite:
        validated = SpecialistResultRecord.model_validate(record.model_dump(mode="json"))
        with self._lock:
            self._require_open_locked()
            existing = self._records.get(validated.result_id)
            if existing is not None:
                if existing != validated:
                    raise ResultConflictError(
                        "result ID was reused with different immutable content"
                    )
                return ResultWrite(
                    disposition=ResultReplayDisposition.REPLAYED,
                    record=existing,
                )
            existing_result_id = self._invocation_index.get(
                validated.producer.invocation_id
            )
            if existing_result_id is not None:
                raise ResultConflictError(
                    "specialist invocation already owns a different result"
                )
            self._records[validated.result_id] = validated
            self._invocation_index[validated.producer.invocation_id] = validated.result_id
            return ResultWrite(
                disposition=ResultReplayDisposition.CREATED,
                record=validated,
            )

    def get(self, result_id: UUID) -> SpecialistResultRecord:
        with self._lock:
            self._require_open_locked()
            record = self._records.get(result_id)
            if record is None:
                raise ResultNotFoundError(f"result {result_id} does not exist")
            return record

    def get_for_invocation(self, invocation_id: UUID) -> SpecialistResultRecord:
        with self._lock:
            self._require_open_locked()
            result_id = self._invocation_index.get(invocation_id)
            if result_id is None:
                raise ResultNotFoundError(
                    f"invocation {invocation_id} has no authoritative result"
                )
            return self._records[result_id]

    def load(self) -> tuple[SpecialistResultRecord, ...]:
        with self._lock:
            self._require_open_locked()
            return tuple(
                sorted(
                    self._records.values(),
                    key=lambda record: (record.created_at_ms, str(record.result_id)),
                )
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _require_open_locked(self) -> None:
        if self._closed:
            raise ResultStoreClosedError("result store is closed")


class RenderedPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    result_id: UUID
    result_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )
    locale: str = Field(min_length=2, max_length=32)
    body: str = Field(min_length=1, max_length=MAX_PRESENTATION_CHARACTERS)


class ResultRenderer(Protocol):
    def render(
        self,
        record: SpecialistResultRecord,
        *,
        locale: str,
    ) -> RenderedPresentation: ...


class PersianPlanRenderer:
    """Deterministic non-authoritative renderer for the first result family."""

    def render(
        self,
        record: SpecialistResultRecord,
        *,
        locale: str,
    ) -> RenderedPresentation:
        if not locale.casefold().startswith("fa"):
            raise UnsupportedResultLocaleError(
                "the initial specialist plan renderer supports Persian locales only"
            )
        payload = record.payload
        sections = [payload.summary]
        if payload.steps:
            sections.append(
                "مراحل:\n"
                + "\n".join(
                    f"{index}. {step}"
                    for index, step in enumerate(payload.steps, start=1)
                )
            )
        if payload.unresolved_risks:
            sections.append(
                "ریسک‌های حل‌نشده:\n"
                + "\n".join(f"- {risk}" for risk in payload.unresolved_risks)
            )
        if payload.verification_requirements:
            sections.append(
                "نیازهای راستی‌آزمایی:\n"
                + "\n".join(
                    f"- {requirement}"
                    for requirement in payload.verification_requirements
                )
            )
        body = "\n\n".join(sections)
        if len(body) > MAX_PRESENTATION_CHARACTERS:
            raise ResultAuthorityError("rendered presentation exceeds its size limit")
        return RenderedPresentation(
            result_id=record.result_id,
            result_sha256=record.result_sha256,
            locale=locale,
            body=body,
        )


def default_result_schema_registry() -> ResultSchemaRegistry:
    return ResultSchemaRegistry(
        (
            ResultSchemaRegistration(
                output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
                schema_version="1.0",
                payload_model=SpecialistPlanPayload,
            ),
        )
    )


def stable_result_id(
    *,
    invocation_id: UUID,
    output_contract: str,
    schema_version: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"simorgh-result:{invocation_id}:{output_contract}:{schema_version}",
    )


def create_specialist_plan_result(
    *,
    producer: ResultProducer,
    payload: SpecialistPlanPayload | dict[str, Any],
    artifacts: Iterable[ArtifactReference] = (),
    evidence: Iterable[EvidenceReference] = (),
    privacy: PrivacyClassification,
    retention: RetentionClass,
    invocation_usage_sha256: str,
    invocation_result_sha256: str,
    created_at_ms: int | None = None,
    completed_at_ms: int | None = None,
    registry: ResultSchemaRegistry | None = None,
    wall_clock_millis: Callable[[], int] | None = None,
) -> SpecialistResultRecord:
    schemas = registry or default_result_schema_registry()
    validated_payload = schemas.validate(
        output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
        schema_version="1.0",
        payload=payload,
    )
    if not isinstance(validated_payload, SpecialistPlanPayload):
        raise ResultAuthorityError("registered plan schema returned the wrong payload type")
    plan_payload = validated_payload
    now = wall_clock_millis or (lambda: int(time.time() * 1_000))
    created = max(0, int(now()) if created_at_ms is None else created_at_ms)
    completed = (
        max(created, int(now()))
        if completed_at_ms is None
        else completed_at_ms
    )
    if completed < created:
        raise ValueError("result completion cannot precede creation")
    result_id = stable_result_id(
        invocation_id=producer.invocation_id,
        output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
        schema_version=plan_payload.schema_version,
    )
    artifact_tuple = tuple(artifacts)
    evidence_tuple = tuple(evidence)
    payload_sha256 = canonical_fingerprint(plan_payload)
    provisional = SpecialistResultRecord.model_construct(
        authority_schema_version=RESULT_AUTHORITY_SCHEMA_VERSION,
        result_id=result_id,
        producer=producer,
        output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
        result_schema_version=plan_payload.schema_version,
        payload=plan_payload,
        payload_sha256=payload_sha256,
        artifacts=artifact_tuple,
        evidence=evidence_tuple,
        unresolved_risks=plan_payload.unresolved_risks,
        verification_requirements=plan_payload.verification_requirements,
        invocation_usage_sha256=invocation_usage_sha256,
        invocation_result_sha256=invocation_result_sha256,
        privacy=privacy,
        retention=retention,
        created_at_ms=created,
        completed_at_ms=completed,
        result_sha256="0" * 64,
    )
    try:
        result_sha256 = canonical_fingerprint(provisional._hash_payload())
    except InvocationPayloadError:
        raise ResultAuthorityError(
            "specialist result could not be encoded as canonical JSON"
        ) from None
    return SpecialistResultRecord.model_validate(
        provisional.model_copy(
            update={"result_sha256": result_sha256}
        ).model_dump(mode="json")
    )
