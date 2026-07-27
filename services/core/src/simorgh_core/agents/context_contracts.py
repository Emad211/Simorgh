from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.contracts import (
    ExecutionMode,
    FreshnessClass,
    TaskBudget,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InvocationEffect,
    canonical_fingerprint,
    canonical_json,
    canonical_size_bytes,
)
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
    RetentionDisposition,
    strictest_privacy,
    strictest_retention,
)
from simorgh_core.agents.specialist_execution import SpecialistCapabilitySet

CONTEXT_CONTRACT_VERSION: Literal["1.0"] = "1.0"
CONTEXT_COMPILER_ID: Literal["simorgh.context-compiler"] = "simorgh.context-compiler"
CONTEXT_COMPILER_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_CONTEXT_BYTES = 1_000_000
MAX_CONTEXT_SECTIONS = 256
MAX_CONTEXT_TOOLS = 64
MAX_CONTEXT_OMISSIONS = 256
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
_AGENT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_POLICY_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_SCHEMA_VERSION_PATTERN = r"^[0-9]+\.[0-9]+$"


class ContextContractError(RuntimeError):
    """Base class for deterministic context-contract failures."""


class ContextTrustClass(StrEnum):
    TRUSTED_PROJECT_FACT = "trusted_project_fact"
    UNTRUSTED_EXTERNAL_EVIDENCE = "untrusted_external_evidence"
    UNTRUSTED_USER_CONTENT = "untrusted_user_content"


class ContextSourceKind(StrEnum):
    USER_TASK = "user_task"
    PROJECT_GOAL = "project_goal"
    DECISION = "decision"
    EVIDENCE = "evidence"
    RESULT_REFERENCE = "result_reference"


class ContextSectionDisposition(StrEnum):
    COMPLETE = "complete"
    TRUNCATED = "truncated"


class ContextOmissionReason(StrEnum):
    STALE = "stale"
    UNKNOWN_FRESHNESS = "unknown_freshness"
    PRIVACY_CEILING = "privacy_ceiling"
    RETENTION_CEILING = "retention_ceiling"
    SECTION_LIMIT = "section_limit"
    EVIDENCE_LIMIT = "evidence_limit"
    TEXT_LIMIT = "text_limit"
    BYTE_LIMIT = "byte_limit"
    TOKEN_LIMIT = "token_limit"


class ContextReplayDisposition(StrEnum):
    FRESH = "fresh"
    REPLAYED = "replayed"


class ContextCompilerLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    max_total_bytes: int = Field(default=128_000, ge=1, le=MAX_CONTEXT_BYTES)
    max_estimated_tokens: int = Field(default=32_000, ge=1, le=1_000_000)
    max_sections: int = Field(default=48, ge=1, le=MAX_CONTEXT_SECTIONS)
    max_evidence_items: int = Field(default=24, ge=0, le=MAX_CONTEXT_SECTIONS)
    max_text_characters: int = Field(default=24_000, ge=1, le=250_000)
    max_tools: int = Field(default=16, ge=0, le=MAX_CONTEXT_TOOLS)
    max_tool_schema_bytes: int = Field(default=96_000, ge=0, le=500_000)
    max_omissions: int = Field(default=128, ge=0, le=MAX_CONTEXT_OMISSIONS)


class ContextMaterial(BaseModel):
    """One approved bounded source candidate before deterministic compilation."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    material_id: UUID
    source_kind: ContextSourceKind
    trust: ContextTrustClass
    source_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    source_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    content_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    content: str = Field(min_length=1, max_length=250_000)
    required: bool = False
    priority: int = Field(default=100, ge=0, le=1_000)
    observed_at_ms: int = Field(ge=0)
    fresh_until_ms: int | None = Field(default=None, ge=0)
    cache_disposition: EvidenceCacheDisposition = EvidenceCacheDisposition.UNKNOWN
    content_addressed: bool = False
    tainted: bool
    privacy: PrivacyClassification
    retention: RetentionDisposition
    citation_reference: str | None = Field(default=None, min_length=1, max_length=2_048)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        _require_safe_text(value)
        return value

    @field_validator("citation_reference")
    @classmethod
    def normalize_citation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("context citation must be one bounded non-empty line")
        return normalized

    @model_validator(mode="after")
    def validate_material(self) -> Self:
        if context_text_sha256(self.content) != self.content_sha256:
            raise ValueError("context material content hash does not match content")
        if self.fresh_until_ms is not None and self.fresh_until_ms < self.observed_at_ms:
            raise ValueError("context material freshness cannot precede observation time")
        expected_trust = {
            ContextSourceKind.USER_TASK: ContextTrustClass.UNTRUSTED_USER_CONTENT,
            ContextSourceKind.EVIDENCE: ContextTrustClass.UNTRUSTED_EXTERNAL_EVIDENCE,
            ContextSourceKind.PROJECT_GOAL: ContextTrustClass.TRUSTED_PROJECT_FACT,
            ContextSourceKind.DECISION: ContextTrustClass.TRUSTED_PROJECT_FACT,
            ContextSourceKind.RESULT_REFERENCE: ContextTrustClass.TRUSTED_PROJECT_FACT,
        }[self.source_kind]
        if self.trust != expected_trust:
            raise ValueError("context source kind does not match its fixed trust class")
        if self.trust in {
            ContextTrustClass.UNTRUSTED_EXTERNAL_EVIDENCE,
            ContextTrustClass.UNTRUSTED_USER_CONTENT,
        }:
            if not self.tainted:
                raise ValueError("untrusted context material must retain taint")
        elif self.tainted:
            raise ValueError("trusted project facts cannot be marked as tainted")
        return self


class ContextSection(BaseModel):
    """One immutable admitted context data section; authority remains top-level."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    material_id: UUID
    source_kind: ContextSourceKind
    trust: ContextTrustClass
    source_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    source_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    content_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    content: str = Field(min_length=1, max_length=250_000)
    disposition: ContextSectionDisposition
    original_characters: int = Field(ge=1, le=250_000)
    included_characters: int = Field(ge=1, le=250_000)
    byte_count: int = Field(ge=1, le=1_000_000)
    estimated_tokens: int = Field(ge=1, le=1_000_000)
    required: bool
    priority: int = Field(ge=0, le=1_000)
    observed_at_ms: int = Field(ge=0)
    fresh_until_ms: int | None = Field(default=None, ge=0)
    cache_disposition: EvidenceCacheDisposition
    content_addressed: bool
    tainted: bool
    privacy: PrivacyClassification
    retention: RetentionDisposition
    citation_reference: str | None = Field(default=None, min_length=1, max_length=2_048)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        _require_safe_text(value)
        return value

    @field_validator("citation_reference")
    @classmethod
    def normalize_citation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("context citation must be one bounded non-empty line")
        return normalized

    @model_validator(mode="after")
    def validate_section(self) -> Self:
        if context_text_sha256(self.content) != self.content_sha256:
            raise ValueError("context section content hash does not match content")
        if len(self.content) != self.included_characters:
            raise ValueError("context section included character count is invalid")
        if len(self.content.encode("utf-8")) != self.byte_count:
            raise ValueError("context section byte count is invalid")
        if estimate_context_tokens(self.content) != self.estimated_tokens:
            raise ValueError("context section token estimate is invalid")
        if self.included_characters > self.original_characters:
            raise ValueError("context section cannot exceed original character count")
        if self.disposition == ContextSectionDisposition.COMPLETE:
            if self.included_characters != self.original_characters:
                raise ValueError("complete context section must preserve all characters")
        elif self.included_characters >= self.original_characters:
            raise ValueError("truncated context section must omit at least one character")
        if self.required and self.disposition != ContextSectionDisposition.COMPLETE:
            raise ValueError("required context material cannot be silently truncated")
        if self.fresh_until_ms is not None and self.fresh_until_ms < self.observed_at_ms:
            raise ValueError("context section freshness cannot precede observation time")
        if self.trust in {
            ContextTrustClass.UNTRUSTED_EXTERNAL_EVIDENCE,
            ContextTrustClass.UNTRUSTED_USER_CONTENT,
        }:
            if not self.tainted:
                raise ValueError("untrusted context section must retain taint")
        elif self.tainted:
            raise ValueError("trusted context section cannot be tainted")
        return self


class ContextOmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    material_id: UUID
    source_kind: ContextSourceKind
    source_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    source_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    reason: ContextOmissionReason
    required: Literal[False] = False


class ContextToolSchemaProjection(BaseModel):
    """Reviewed tool-schema data; carrying it grants no execution authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    tool_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    connector_id: str | None = Field(
        default=None,
        pattern=_RESOURCE_ID_PATTERN,
        max_length=128,
    )
    effect: InvocationEffect
    input_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    output_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    description: str = Field(min_length=1, max_length=1_000)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        _require_safe_text(value)
        return value.strip()

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if context_tool_schema_sha256(self) != self.canonical_sha256:
            raise ValueError("tool schema projection hash does not match content")
        return self


class ContextOutputSchemaProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    output_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    result_schema_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    result_schema_version: str = Field(pattern=_SCHEMA_VERSION_PATTERN, max_length=32)
    family: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    json_schema: dict[str, Any]
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if context_output_schema_sha256(self) != self.canonical_sha256:
            raise ValueError("output schema projection hash does not match content")
        return self


class ContextBudgetProjection(BaseModel):
    """Machine-verifiable remaining specialist budget at compilation time."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    request_id: UUID
    effective_limits: TaskBudget
    committed: UsageVector
    reserved: UsageVector
    remaining: UsageVector
    elapsed_ms: int = Field(ge=0)
    remaining_elapsed_ms: int = Field(ge=0)
    cancelled: bool
    exhausted_dimension: str | None = None
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )

    @model_validator(mode="after")
    def validate_budget(self) -> Self:
        expected_remaining = context_remaining_usage(
            limits=self.effective_limits,
            committed=self.committed,
            reserved=self.reserved,
        )
        if self.remaining != expected_remaining:
            raise ValueError("context remaining budget does not match usage and limits")
        expected_elapsed = max(0, self.effective_limits.max_elapsed_ms - self.elapsed_ms)
        if self.remaining_elapsed_ms != expected_elapsed:
            raise ValueError("context remaining elapsed budget is invalid")
        if context_budget_projection_sha256(self) != self.canonical_sha256:
            raise ValueError("context budget projection hash does not match content")
        return self


class ContextCompilerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    compiler_id: Literal["simorgh.context-compiler"] = CONTEXT_COMPILER_ID
    compiler_version: Literal["1.0.0"] = CONTEXT_COMPILER_VERSION
    enabled: bool = True
    limits: ContextCompilerLimits = Field(default_factory=ContextCompilerLimits)
    privacy_ceiling: PrivacyClassification = PrivacyClassification.INTERNAL
    retention_ceiling: RetentionDisposition = RetentionDisposition.LEGAL_HOLD

    @property
    def canonical_sha256(self) -> str:
        return canonical_fingerprint(self)


class ContextCompilationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    request_id: UUID
    specialist_invocation_id: UUID
    agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    agent_version: str = Field(pattern=_POLICY_VERSION_PATTERN, max_length=32)
    capabilities: SpecialistCapabilitySet
    materials: tuple[ContextMaterial, ...] = Field(default=(), max_length=MAX_CONTEXT_SECTIONS)
    tool_schemas: tuple[ContextToolSchemaProjection, ...] = Field(
        default=(),
        max_length=MAX_CONTEXT_TOOLS,
    )
    output_schema: ContextOutputSchemaProjection

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        material_ids = tuple(item.material_id for item in self.materials)
        if len(set(material_ids)) != len(material_ids):
            raise ValueError("context compilation material IDs must be unique")
        tool_ids = tuple(item.tool_id for item in self.tool_schemas)
        if len(set(tool_ids)) != len(tool_ids):
            raise ValueError("context compilation tool IDs must be unique")
        return self


class SpecialistContextBundle(BaseModel):
    """Immutable machine-verifiable specialist context authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = CONTEXT_CONTRACT_VERSION
    compiler_id: Literal["simorgh.context-compiler"] = CONTEXT_COMPILER_ID
    compiler_version: Literal["1.0.0"] = CONTEXT_COMPILER_VERSION
    context_bundle_id: UUID
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    request_id: UUID
    specialist_invocation_id: UUID
    agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    agent_version: str = Field(pattern=_POLICY_VERSION_PATTERN, max_length=32)
    task_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    routing_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    policy_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    task_kind: TaskKind
    execution_mode: ExecutionMode
    freshness: FreshnessClass
    deadline_at_ms: int | None = Field(default=None, ge=0)
    capabilities: SpecialistCapabilitySet
    budget: ContextBudgetProjection
    limits: ContextCompilerLimits
    output_schema: ContextOutputSchemaProjection
    tool_schemas: tuple[ContextToolSchemaProjection, ...] = Field(
        default=(),
        max_length=MAX_CONTEXT_TOOLS,
    )
    sections: tuple[ContextSection, ...] = Field(
        min_length=1,
        max_length=MAX_CONTEXT_SECTIONS,
    )
    omissions: tuple[ContextOmission, ...] = Field(
        default=(),
        max_length=MAX_CONTEXT_OMISSIONS,
    )
    source_manifest_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    privacy: PrivacyClassification
    retention: RetentionDisposition
    tainted: bool
    section_count: int = Field(ge=1, le=MAX_CONTEXT_SECTIONS)
    evidence_count: int = Field(ge=0, le=MAX_CONTEXT_SECTIONS)
    tool_count: int = Field(ge=0, le=MAX_CONTEXT_TOOLS)
    omission_count: int = Field(ge=0, le=MAX_CONTEXT_OMISSIONS)
    total_bytes: int = Field(ge=1, le=MAX_CONTEXT_BYTES)
    estimated_tokens: int = Field(ge=1, le=1_000_000)
    compiled_at_ms: int = Field(ge=0)
    replay: ContextReplayDisposition = ContextReplayDisposition.FRESH

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        section_ids = tuple(section.material_id for section in self.sections)
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("context bundle section material IDs must be unique")
        if self.sections != tuple(sorted(self.sections, key=context_section_sort_key)):
            raise ValueError("context bundle sections must be canonically ordered")
        tool_ids = tuple(item.tool_id for item in self.tool_schemas)
        if len(set(tool_ids)) != len(tool_ids):
            raise ValueError("context bundle tool IDs must be unique")
        if self.tool_schemas != tuple(
            sorted(self.tool_schemas, key=lambda item: (item.tool_id, item.connector_id or ""))
        ):
            raise ValueError("context bundle tool schemas must be canonically ordered")
        if self.omissions != tuple(sorted(self.omissions, key=context_omission_sort_key)):
            raise ValueError("context bundle omissions must be canonically ordered")
        if self.budget.request_id != self.request_id:
            raise ValueError("context bundle budget does not belong to request")
        if self.budget.cancelled:
            raise ValueError("cancelled budget cannot authorize a context bundle")
        if self.section_count != len(self.sections):
            raise ValueError("context bundle section count is invalid")
        expected_evidence = sum(
            section.source_kind == ContextSourceKind.EVIDENCE for section in self.sections
        )
        if self.evidence_count != expected_evidence:
            raise ValueError("context bundle evidence count is invalid")
        if self.tool_count != len(self.tool_schemas):
            raise ValueError("context bundle tool count is invalid")
        if self.omission_count != len(self.omissions):
            raise ValueError("context bundle omission count is invalid")
        if self.section_count > self.limits.max_sections:
            raise ValueError("context bundle exceeds section limit")
        if self.evidence_count > self.limits.max_evidence_items:
            raise ValueError("context bundle exceeds evidence limit")
        if self.tool_count > self.limits.max_tools:
            raise ValueError("context bundle exceeds tool limit")
        if self.omission_count > self.limits.max_omissions:
            raise ValueError("context bundle exceeds omission limit")
        tool_schema_bytes = sum(canonical_size_bytes(item) for item in self.tool_schemas)
        if tool_schema_bytes > self.limits.max_tool_schema_bytes:
            raise ValueError("context bundle exceeds tool-schema byte limit")
        expected_privacy = strictest_privacy(
            (section.privacy for section in self.sections),
            default=PrivacyClassification.INTERNAL,
        )
        if self.privacy != expected_privacy:
            raise ValueError("context bundle privacy does not match admitted sections")
        expected_retention = strictest_retention(
            (section.retention for section in self.sections),
            default=RetentionDisposition.SESSION,
        )
        if self.retention != expected_retention:
            raise ValueError("context bundle retention does not match admitted sections")
        if self.tainted != any(section.tainted for section in self.sections):
            raise ValueError("context bundle taint does not match admitted sections")
        if (
            context_source_manifest_sha256(self.sections, self.omissions)
            != self.source_manifest_sha256
        ):
            raise ValueError("context source manifest hash does not match bundle sources")
        if context_bundle_canonical_sha256(self) != self.canonical_sha256:
            raise ValueError("context bundle hash does not match authoritative content")
        expected_id = context_bundle_id_for(
            request_id=self.request_id,
            canonical_sha256=self.canonical_sha256,
        )
        if self.context_bundle_id != expected_id:
            raise ValueError("context bundle ID does not match canonical identity")
        payload = context_bundle_canonical_payload(self)
        expected_bytes = canonical_size_bytes(payload)
        if self.total_bytes != expected_bytes:
            raise ValueError("context bundle byte count is invalid")
        expected_tokens = estimate_context_tokens(canonical_json(payload))
        if self.estimated_tokens != expected_tokens:
            raise ValueError("context bundle token estimate is invalid")
        if self.total_bytes > self.limits.max_total_bytes:
            raise ValueError("context bundle exceeds total byte limit")
        if self.estimated_tokens > self.limits.max_estimated_tokens:
            raise ValueError("context bundle exceeds estimated-token limit")
        return self


def context_remaining_usage(
    *,
    limits: TaskBudget,
    committed: UsageVector,
    reserved: UsageVector,
) -> UsageVector:
    committed_values = committed.model_dump()
    reserved_values = reserved.model_dump()

    def remaining(dimension: str) -> int:
        committed_value = int(committed_values[dimension])
        reserved_value = int(reserved_values[dimension])
        return max(
            0,
            limits.limit_for(dimension) - committed_value - reserved_value,
        )

    return UsageVector(
        model_calls=remaining("model_calls"),
        tool_calls=remaining("tool_calls"),
        input_tokens=remaining("input_tokens"),
        output_tokens=remaining("output_tokens"),
        estimated_cost_microusd=remaining("estimated_cost_microusd"),
        retries=remaining("retries"),
        parallel_branches=remaining("parallel_branches"),
    )


def context_budget_projection_sha256(value: ContextBudgetProjection) -> str:
    return canonical_fingerprint(
        value.model_dump(mode="json", exclude={"canonical_sha256"})
    )


def context_text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def estimate_context_tokens(value: str) -> int:
    if not value:
        return 0
    byte_estimate = (len(value.encode("utf-8")) + 2) // 3
    return max(len(value), byte_estimate, 1)


def context_section_from_material(
    material: ContextMaterial,
    *,
    content: str | None = None,
) -> ContextSection:
    included = material.content if content is None else content
    if not included:
        raise ContextContractError("context section cannot be empty")
    if not material.content.startswith(included):
        raise ContextContractError("context truncation must preserve a deterministic prefix")
    disposition = (
        ContextSectionDisposition.COMPLETE
        if included == material.content
        else ContextSectionDisposition.TRUNCATED
    )
    return ContextSection(
        material_id=material.material_id,
        source_kind=material.source_kind,
        trust=material.trust,
        source_id=material.source_id,
        source_sha256=material.source_sha256,
        content_sha256=context_text_sha256(included),
        content=included,
        disposition=disposition,
        original_characters=len(material.content),
        included_characters=len(included),
        byte_count=len(included.encode("utf-8")),
        estimated_tokens=estimate_context_tokens(included),
        required=material.required,
        priority=material.priority,
        observed_at_ms=material.observed_at_ms,
        fresh_until_ms=material.fresh_until_ms,
        cache_disposition=material.cache_disposition,
        content_addressed=material.content_addressed,
        tainted=material.tainted,
        privacy=material.privacy,
        retention=material.retention,
        citation_reference=material.citation_reference,
    )


def context_tool_schema_sha256(value: ContextToolSchemaProjection) -> str:
    return canonical_fingerprint(
        value.model_dump(mode="json", exclude={"canonical_sha256"})
    )


def context_output_schema_sha256(value: ContextOutputSchemaProjection) -> str:
    return canonical_fingerprint(
        value.model_dump(mode="json", exclude={"canonical_sha256"})
    )


def context_section_sort_key(section: ContextSection) -> tuple[int, int, int, str, str]:
    kind_rank = {
        ContextSourceKind.USER_TASK: 0,
        ContextSourceKind.PROJECT_GOAL: 1,
        ContextSourceKind.DECISION: 2,
        ContextSourceKind.RESULT_REFERENCE: 3,
        ContextSourceKind.EVIDENCE: 4,
    }[section.source_kind]
    return (
        kind_rank,
        0 if section.required else 1,
        -section.priority,
        section.source_id,
        str(section.material_id),
    )


def context_omission_sort_key(
    omission: ContextOmission,
) -> tuple[str, str, str, str]:
    return (
        omission.source_kind.value,
        omission.source_id,
        str(omission.material_id),
        omission.reason.value,
    )


def context_source_manifest_sha256(
    sections: tuple[ContextSection, ...],
    omissions: tuple[ContextOmission, ...],
) -> str:
    payload = {
        "sections": [
            {
                "material_id": str(section.material_id),
                "source_kind": section.source_kind.value,
                "source_id": section.source_id,
                "source_sha256": section.source_sha256,
                "content_sha256": section.content_sha256,
                "disposition": section.disposition.value,
                "tainted": section.tainted,
            }
            for section in sections
        ],
        "omissions": [item.model_dump(mode="json") for item in omissions],
    }
    return canonical_fingerprint(payload)


def context_bundle_canonical_payload(
    value: SpecialistContextBundle | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(value, SpecialistContextBundle):
        payload = value.model_dump(mode="json")
    else:
        payload = dict(value)
    capabilities = payload.get("capabilities")
    if isinstance(capabilities, dict):
        for key in ("tool_ids", "connector_ids", "model_tiers"):
            values = capabilities.get(key)
            if isinstance(values, list):
                capabilities[key] = sorted(values)
    for field in (
        "context_bundle_id",
        "canonical_sha256",
        "compiled_at_ms",
        "replay",
        "section_count",
        "evidence_count",
        "tool_count",
        "omission_count",
        "total_bytes",
        "estimated_tokens",
    ):
        payload.pop(field, None)
    return payload


def context_bundle_canonical_sha256(
    value: SpecialistContextBundle | dict[str, Any],
) -> str:
    return canonical_fingerprint(context_bundle_canonical_payload(value))


def context_bundle_id_for(*, request_id: UUID, canonical_sha256: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"simorgh-context:{request_id}:{canonical_sha256}",
    )


def context_material_id_for(
    *,
    request_id: UUID,
    source_kind: ContextSourceKind,
    source_id: str,
    source_sha256: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"simorgh-context-material:{request_id}:{source_kind.value}:"
        f"{source_id}:{source_sha256}",
    )


def _require_safe_text(value: str) -> None:
    for character in value:
        if ord(character) < 32 and character not in {"\n", "\r", "\t"}:
            raise ValueError("context text contains a disallowed control character")


__all__ = [
    "CONTEXT_COMPILER_ID",
    "CONTEXT_COMPILER_VERSION",
    "CONTEXT_CONTRACT_VERSION",
    "ContextBudgetProjection",
    "ContextCompilationRequest",
    "ContextCompilerLimits",
    "ContextCompilerPolicy",
    "ContextContractError",
    "ContextMaterial",
    "ContextOmission",
    "ContextOmissionReason",
    "ContextOutputSchemaProjection",
    "ContextReplayDisposition",
    "ContextSection",
    "ContextSectionDisposition",
    "ContextSourceKind",
    "ContextToolSchemaProjection",
    "ContextTrustClass",
    "SpecialistContextBundle",
    "context_budget_projection_sha256",
    "context_bundle_canonical_payload",
    "context_bundle_canonical_sha256",
    "context_bundle_id_for",
    "context_material_id_for",
    "context_output_schema_sha256",
    "context_remaining_usage",
    "context_section_from_material",
    "context_source_manifest_sha256",
    "context_text_sha256",
    "context_tool_schema_sha256",
    "estimate_context_tokens",
]
