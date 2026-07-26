from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AGENT_CONTRACT_VERSION: Literal["1.0"] = "1.0"
_AGENT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_POLICY_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"


class TaskKind(StrEnum):
    REPOSITORY_RESEARCH = "repository_research"
    DEVELOPMENT_PLANNING = "development_planning"
    SEO_PLANNING = "seo_planning"
    MARKETING_PLANNING = "marketing_planning"
    EMAIL_READ = "email_read"
    CALENDAR_READ = "calendar_read"
    DOCUMENT_READ = "document_read"
    MOBILE_OPERATION_PLANNING = "mobile_operation_planning"
    GENERAL_PLANNING = "general_planning"


class RiskClass(StrEnum):
    READ_ONLY = "read_only"
    PLANNING = "planning"
    EXTERNAL_MUTATION = "external_mutation"
    SENSITIVE = "sensitive"


class FreshnessClass(StrEnum):
    IMMUTABLE = "immutable"
    CACHED_OK = "cached_ok"
    CURRENT = "current"
    EXECUTION_BOUND = "execution_bound"


class LatencyClass(StrEnum):
    INTERACTIVE = "interactive"
    NORMAL = "normal"
    BATCH = "batch"


class ExecutionMode(StrEnum):
    ROUTE_ONLY = "route_only"
    READ_ONLY = "read_only"
    PLAN = "plan"
    PROPOSE_MUTATION = "propose_mutation"
    EXECUTE_TYPED = "execute_typed"


class SideEffectPolicy(StrEnum):
    NONE = "none"
    PROPOSE_ONLY = "propose_only"
    TYPED_EXECUTOR_ONLY = "typed_executor_only"


class ModelTier(StrEnum):
    FAST = "fast"
    GENERAL = "general"
    REASONING = "reasoning"
    DOMAIN = "domain"


class RoutingMethod(StrEnum):
    EXPLICIT_TASK_KIND = "explicit_task_kind"
    DETERMINISTIC_RULE = "deterministic_rule"
    MODEL_CLASSIFIER = "model_classifier"


class RoutingState(StrEnum):
    ROUTED = "routed"
    NEEDS_CLARIFICATION = "needs_clarification"
    NEEDS_ESCALATION = "needs_escalation"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_BLOCKED = "policy_blocked"
    CONTRACT_INVALID = "contract_invalid"


class InvocationState(StrEnum):
    PENDING = "pending"
    RESERVED = "reserved"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"
    UNKNOWN_SIDE_EFFECT = "unknown_side_effect"


class UsageVector(BaseModel):
    """Integer accounting vector used for reservations and committed usage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_microusd: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    parallel_branches: int = Field(default=0, ge=0)

    def plus(self, other: UsageVector) -> UsageVector:
        return UsageVector(
            model_calls=self.model_calls + other.model_calls,
            tool_calls=self.tool_calls + other.tool_calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            estimated_cost_microusd=(
                self.estimated_cost_microusd + other.estimated_cost_microusd
            ),
            retries=self.retries + other.retries,
            parallel_branches=self.parallel_branches + other.parallel_branches,
        )


class TaskBudget(BaseModel):
    """Immutable upper bounds for one routed request or specialist invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_model_calls: int = Field(default=1, ge=0, le=100)
    max_tool_calls: int = Field(default=8, ge=0, le=10_000)
    max_input_tokens: int = Field(default=16_000, ge=0, le=100_000_000)
    max_output_tokens: int = Field(default=4_000, ge=0, le=10_000_000)
    max_estimated_cost_microusd: int = Field(default=50_000, ge=0, le=10**12)
    max_elapsed_ms: int = Field(default=120_000, ge=1, le=86_400_000)
    max_retries: int = Field(default=1, ge=0, le=100)
    max_parallel_branches: int = Field(default=1, ge=1, le=100)

    def limit_for(self, dimension: str) -> int:
        return {
            "model_calls": self.max_model_calls,
            "tool_calls": self.max_tool_calls,
            "input_tokens": self.max_input_tokens,
            "output_tokens": self.max_output_tokens,
            "estimated_cost_microusd": self.max_estimated_cost_microusd,
            "retries": self.max_retries,
            "parallel_branches": self.max_parallel_branches,
        }[dimension]


class TaskEnvelope(BaseModel):
    """Versioned edge contract routed to exactly one primary specialist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = AGENT_CONTRACT_VERSION
    request_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID | None = None
    parent_request_id: UUID | None = None
    received_at_ms: int = Field(ge=0)
    deadline_at_ms: int | None = Field(default=None, ge=0)
    locale: str = Field(default="fa-IR", min_length=2, max_length=35)
    input_text: str = Field(min_length=1, max_length=100_000)
    requested_outcome: str = Field(min_length=1, max_length=4_000)
    explicit_task_kind: TaskKind | None = None
    risk_class: RiskClass = RiskClass.PLANNING
    freshness: FreshnessClass = FreshnessClass.CURRENT
    latency: LatencyClass = LatencyClass.INTERACTIVE
    execution_mode: ExecutionMode = ExecutionMode.PLAN
    allowed_data_sources: frozenset[str] = Field(default_factory=frozenset, max_length=256)
    budget: TaskBudget = Field(default_factory=TaskBudget)

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        normalized = value.strip().replace("_", "-")
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("locale must be a compact BCP-47-like identifier")
        return normalized

    @field_validator("allowed_data_sources")
    @classmethod
    def validate_data_sources(cls, value: frozenset[str]) -> frozenset[str]:
        for source in value:
            if not source or len(source) > 128:
                raise ValueError("data-source identifiers must be in 1..128 characters")
        return value

    @model_validator(mode="after")
    def validate_deadline_and_execution_mode(self) -> Self:
        if self.deadline_at_ms is not None and self.deadline_at_ms <= self.received_at_ms:
            raise ValueError("deadline_at_ms must be later than received_at_ms")
        if (
            self.execution_mode == ExecutionMode.EXECUTE_TYPED
            and self.risk_class not in {RiskClass.EXTERNAL_MUTATION, RiskClass.SENSITIVE}
        ):
            raise ValueError("execute_typed requires external_mutation or sensitive risk class")
        return self


class ModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_tiers: tuple[ModelTier, ...] = ()
    minimum_tier: ModelTier | None = None
    maximum_model_calls: int = Field(default=0, ge=0, le=100)
    classifier_allowed: bool = False
    escalation_agent_ids: tuple[str, ...] = ()

    @field_validator("escalation_agent_ids")
    @classmethod
    def validate_escalation_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for agent_id in value:
            if not agent_id:
                raise ValueError("escalation agent identifiers cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_model_access(self) -> Self:
        if not self.allowed_tiers and self.maximum_model_calls != 0:
            raise ValueError("maximum_model_calls must be zero when no model tier is allowed")
        if self.minimum_tier is not None and self.minimum_tier not in self.allowed_tiers:
            raise ValueError("minimum_tier must be included in allowed_tiers")
        if self.classifier_allowed and self.maximum_model_calls == 0:
            raise ValueError("classifier_allowed requires at least one model call")
        return self


class RoutingRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    locale_prefixes: frozenset[str] = Field(default_factory=frozenset, max_length=32)
    phrases: tuple[str, ...] = Field(min_length=1, max_length=128)
    weight: int = Field(default=10, ge=1, le=1_000)

    @field_validator("phrases")
    @classmethod
    def validate_phrases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(phrase.strip() for phrase in value)
        if any(not phrase or len(phrase) > 256 for phrase in normalized):
            raise ValueError("routing phrases must be in 1..256 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("routing phrases must be unique within one rule")
        return normalized


class SpecialistDefinition(BaseModel):
    """Immutable compiled policy for one specialist implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    version: str = Field(pattern=_POLICY_VERSION_PATTERN, max_length=32)
    display_name: str = Field(min_length=1, max_length=200)
    task_kinds: frozenset[TaskKind] = Field(min_length=1, max_length=128)
    locale_prefixes: frozenset[str] = Field(default_factory=frozenset, max_length=32)
    input_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    output_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    tool_allowlist: frozenset[str] = Field(default_factory=frozenset, max_length=256)
    connector_allowlist: frozenset[str] = Field(default_factory=frozenset, max_length=256)
    model_policy: ModelPolicy = Field(default_factory=ModelPolicy)
    budget_ceiling: TaskBudget = Field(default_factory=TaskBudget)
    side_effect_policy: SideEffectPolicy = SideEffectPolicy.NONE
    routing_rules: tuple[RoutingRule, ...] = ()
    routing_priority: int = Field(default=100, ge=0, le=10_000)

    @field_validator("tool_allowlist", "connector_allowlist")
    @classmethod
    def validate_resources(cls, value: frozenset[str]) -> frozenset[str]:
        for resource in value:
            if not resource or len(resource) > 128:
                raise ValueError("resource identifiers must be in 1..128 characters")
        return value

    @model_validator(mode="after")
    def validate_side_effect_boundary(self) -> Self:
        if (
            self.side_effect_policy == SideEffectPolicy.TYPED_EXECUTOR_ONLY
            and not any(kind == TaskKind.MOBILE_OPERATION_PLANNING for kind in self.task_kinds)
        ):
            raise ValueError("typed executor policy requires a compatible task kind")
        return self


class AgentClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    confidence_bps: int = Field(ge=0, le=10_000)
    reason: str = Field(min_length=1, max_length=1_000)


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = AGENT_CONTRACT_VERSION
    decision_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    state: RoutingState
    selected_agent_id: str | None = Field(
        default=None,
        pattern=_AGENT_ID_PATTERN,
        max_length=128,
    )
    selected_agent_version: str | None = Field(
        default=None,
        pattern=_POLICY_VERSION_PATTERN,
        max_length=32,
    )
    method: RoutingMethod | None = None
    confidence_bps: int = Field(default=0, ge=0, le=10_000)
    candidate_agent_ids: tuple[str, ...] = ()
    matched_rule_ids: tuple[str, ...] = ()
    classifier_invocation_id: UUID | None = None
    model_calls: int = Field(default=0, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_routing_shape(self) -> Self:
        selected = self.selected_agent_id is not None
        versioned = self.selected_agent_version is not None
        if self.state == RoutingState.ROUTED:
            if not selected or not versioned or self.method is None:
                raise ValueError("routed decision requires selected agent, version, and method")
        elif selected or versioned:
            raise ValueError("non-routed decision cannot select an agent")
        if self.method == RoutingMethod.MODEL_CLASSIFIER:
            if self.classifier_invocation_id is None:
                raise ValueError(
                    "model-classifier decision requires classifier invocation identity"
                )
        else:
            if self.model_calls != 0:
                raise ValueError("deterministic route cannot report model calls")
            if self.classifier_invocation_id is not None:
                raise ValueError("deterministic route cannot carry classifier invocation identity")
        return self
