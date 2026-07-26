from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from enum import StrEnum
from threading import RLock
from typing import Literal, Protocol, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import (
    ExecutionMode,
    ModelTier,
    RoutingDecision,
    RoutingState,
    SideEffectPolicy,
    SpecialistDefinition,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InvocationEffect,
    canonical_fingerprint,
    canonical_size_bytes,
)
from simorgh_core.agents.registry import intersect_budgets
from simorgh_core.agents.specialist_results import (
    SPECIALIST_PLAN_OUTPUT_CONTRACT,
    SpecialistPlanPayload,
)

SPECIALIST_EXECUTION_CONTRACT_VERSION: Literal["1.0"] = "1.0"
MAX_SPECIALIST_INLINE_RESULT_BYTES = 256_000
_AGENT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_POLICY_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_RESOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"


class SpecialistExecutionError(RuntimeError):
    """Base class for deterministic specialist-execution contract failures."""


class DuplicateSpecialistExecutorError(SpecialistExecutionError):
    pass


class UnknownSpecialistExecutorError(SpecialistExecutionError):
    pass


class SpecialistExecutionPolicyError(SpecialistExecutionError):
    pass


class SpecialistExecutionCancelledError(SpecialistExecutionError):
    pass


class SpecialistResultContractError(SpecialistExecutionError):
    pass


class SpecialistExecutionOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"
    UNKNOWN_SIDE_EFFECT = "unknown_side_effect"


class SpecialistReplayDisposition(StrEnum):
    FRESH = "fresh"
    REPLAYED = "replayed"


class SpecialistCapabilitySet(BaseModel):
    """Explicit capability subset passed to one specialist invocation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    tool_ids: frozenset[str] = Field(default_factory=frozenset, max_length=256)
    connector_ids: frozenset[str] = Field(default_factory=frozenset, max_length=256)
    model_tiers: frozenset[ModelTier] = Field(default_factory=frozenset, max_length=4)
    proposal_allowed: bool = False
    typed_mutation_allowed: bool = False

    @field_validator("tool_ids", "connector_ids")
    @classmethod
    def validate_resource_ids(cls, value: frozenset[str]) -> frozenset[str]:
        for resource_id in value:
            if not resource_id or len(resource_id) > 128:
                raise ValueError("capability resource IDs must be in 1..128 characters")
        return value

    def require_subset_of(self, maximum: SpecialistCapabilitySet) -> None:
        if not self.tool_ids.issubset(maximum.tool_ids):
            raise SpecialistExecutionPolicyError(
                "requested specialist tools exceed the compiled policy subset"
            )
        if not self.connector_ids.issubset(maximum.connector_ids):
            raise SpecialistExecutionPolicyError(
                "requested specialist connectors exceed the task/policy intersection"
            )
        if not self.model_tiers.issubset(maximum.model_tiers):
            raise SpecialistExecutionPolicyError(
                "requested specialist model tiers exceed the compiled policy subset"
            )
        if self.proposal_allowed and not maximum.proposal_allowed:
            raise SpecialistExecutionPolicyError(
                "requested proposal authority exceeds the compiled specialist policy"
            )
        if self.typed_mutation_allowed and not maximum.typed_mutation_allowed:
            raise SpecialistExecutionPolicyError(
                "requested mutation authority exceeds the compiled specialist policy"
            )


class SpecialistExecutionRequest(BaseModel):
    """Immutable request derived from a durable routed task and compiled policy."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    schema_version: Literal["1.0"] = SPECIALIST_EXECUTION_CONTRACT_VERSION
    request_id: UUID
    invocation_id: UUID
    context_bundle_id: UUID
    cancellation_owner_id: UUID
    agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    agent_version: str = Field(pattern=_POLICY_VERSION_PATTERN, max_length=32)
    task_kind: TaskKind
    execution_mode: ExecutionMode
    effect: InvocationEffect
    input_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    output_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    task_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    context_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    capabilities: SpecialistCapabilitySet
    effective_budget: TaskBudget
    monotonic_timeout_ms: int = Field(ge=1, le=86_400_000)
    created_at_ms: int = Field(ge=0)
    deadline_at_ms: int | None = Field(default=None, ge=0)
    parent_invocation_id: UUID | None = None
    attempt: Literal[1] = 1

    @model_validator(mode="after")
    def validate_execution_shape(self) -> Self:
        if self.deadline_at_ms is not None and self.deadline_at_ms <= self.created_at_ms:
            raise ValueError("specialist execution deadline must be later than creation time")
        if self.effect == InvocationEffect.MUTATION:
            if self.execution_mode != ExecutionMode.EXECUTE_TYPED:
                raise ValueError("mutation specialist execution requires execute_typed mode")
            if not self.capabilities.typed_mutation_allowed:
                raise ValueError("mutation specialist execution requires typed mutation capability")
        elif self.capabilities.typed_mutation_allowed:
            raise ValueError("typed mutation capability requires a mutation specialist invocation")
        if self.effect == InvocationEffect.PROPOSAL and not self.capabilities.proposal_allowed:
            raise ValueError("proposal specialist execution requires proposal capability")
        if self.monotonic_timeout_ms != self.effective_budget.max_elapsed_ms:
            raise ValueError(
                "specialist monotonic timeout must equal the effective budget limit"
            )
        return self


class SpecialistResultReference(BaseModel):
    """Bounded reference placeholder; artifact/evidence storage is a later trust boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    reference_id: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    kind: Literal["evidence", "artifact"]
    sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )


class SpecialistExecutionResult(BaseModel):
    """Typed terminal output returned by one specialist implementation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    schema_version: Literal["1.0"] = SPECIALIST_EXECUTION_CONTRACT_VERSION
    request_id: UUID
    invocation_id: UUID
    agent_id: str = Field(pattern=_AGENT_ID_PATTERN, max_length=128)
    agent_version: str = Field(pattern=_POLICY_VERSION_PATTERN, max_length=32)
    effect: InvocationEffect
    outcome: SpecialistExecutionOutcome
    output_contract: str = Field(pattern=_RESOURCE_ID_PATTERN, max_length=128)
    payload: SpecialistPlanPayload | None = None
    references: tuple[SpecialistResultReference, ...] = Field(default=(), max_length=256)
    committed_usage: UsageVector = Field(default_factory=UsageVector)
    reason: str | None = Field(default=None, max_length=2_000)
    replay: SpecialistReplayDisposition = SpecialistReplayDisposition.FRESH
    started_at_ms: int = Field(ge=0)
    completed_at_ms: int = Field(ge=0)

    @property
    def replayed(self) -> bool:
        return self.replay == SpecialistReplayDisposition.REPLAYED

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.completed_at_ms < self.started_at_ms:
            raise ValueError("specialist completion time cannot precede start time")
        if self.outcome == SpecialistExecutionOutcome.COMPLETED:
            if self.payload is None:
                raise ValueError("completed specialist execution requires a typed payload")
            if self.output_contract != SPECIALIST_PLAN_OUTPUT_CONTRACT:
                raise ValueError(
                    "specialist plan payload requires the typed-plan output contract"
                )
            if self.reason is not None:
                raise ValueError("completed specialist execution cannot contain a failure reason")
            if canonical_size_bytes(self.payload) > MAX_SPECIALIST_INLINE_RESULT_BYTES:
                raise ValueError("specialist inline result exceeds the durable payload limit")
        else:
            if self.payload is not None:
                raise ValueError("non-completed specialist execution cannot contain a payload")
            if self.reason is None or not self.reason.strip():
                raise ValueError("non-completed specialist execution requires a bounded reason")
        if (
            self.outcome == SpecialistExecutionOutcome.UNKNOWN_SIDE_EFFECT
            and self.effect != InvocationEffect.MUTATION
        ):
            raise ValueError("unknown_side_effect result requires mutation effect")
        if (
            self.effect == InvocationEffect.MUTATION
            and self.outcome == SpecialistExecutionOutcome.UNKNOWN
        ):
            raise ValueError("uncertain mutation result must use unknown_side_effect")
        return self


class SpecialistCancellation:
    """Small thread-safe token for cooperative in-process cancellation."""

    def __init__(self, *, owner_id: UUID | None = None) -> None:
        self._lock = RLock()
        self._owner_id = owner_id
        self._cancelled = False
        self._reason: str | None = None

    @property
    def owner_id(self) -> UUID | None:
        with self._lock:
            return self._owner_id

    def require_owner(self, expected_owner_id: UUID) -> None:
        with self._lock:
            if self._owner_id is None:
                self._owner_id = expected_owner_id
                return
            if self._owner_id != expected_owner_id:
                raise SpecialistExecutionPolicyError(
                    "specialist cancellation owner does not match execution request"
                )

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "specialist execution cancelled") -> None:
        with self._lock:
            if self._cancelled:
                return
            normalized = reason.strip()[:1_000]
            if not normalized:
                raise ValueError("cancellation reason cannot be empty")
            self._cancelled = True
            self._reason = normalized

    def raise_if_cancelled(self) -> None:
        with self._lock:
            if self._cancelled:
                raise SpecialistExecutionCancelledError(
                    self._reason or "specialist execution cancelled"
                )


class SpecialistExecutor(Protocol):
    @property
    def agent_id(self) -> str: ...

    @property
    def agent_version(self) -> str: ...

    @property
    def output_contract(self) -> str: ...

    async def execute(
        self,
        *,
        request: SpecialistExecutionRequest,
        cancellation: SpecialistCancellation,
        budget: BudgetAccount,
    ) -> SpecialistExecutionResult: ...


class SpecialistExecutorRegistry:
    """Immutable exact-version registry for native specialist implementations."""

    def __init__(self, executors: Iterable[SpecialistExecutor] = ()) -> None:
        compiled: dict[tuple[str, str], SpecialistExecutor] = {}
        for executor in executors:
            if re.fullmatch(_AGENT_ID_PATTERN, executor.agent_id) is None:
                raise SpecialistExecutionPolicyError(
                    "specialist executor agent_id is invalid"
                )
            if re.fullmatch(_POLICY_VERSION_PATTERN, executor.agent_version) is None:
                raise SpecialistExecutionPolicyError(
                    "specialist executor version is invalid"
                )
            if re.fullmatch(_RESOURCE_ID_PATTERN, executor.output_contract) is None:
                raise SpecialistExecutionPolicyError(
                    "specialist executor output contract is invalid"
                )
            identity = (executor.agent_id, executor.agent_version)
            if identity in compiled:
                raise DuplicateSpecialistExecutorError(
                    f"specialist executor {identity!r} was registered more than once"
                )
            compiled[identity] = executor
        self._executors = compiled

    def get(self, *, agent_id: str, agent_version: str) -> SpecialistExecutor:
        executor = self._executors.get((agent_id, agent_version))
        if executor is None:
            raise UnknownSpecialistExecutorError(
                f"specialist executor {(agent_id, agent_version)!r} is not registered"
            )
        return executor

    def require_definition(self, definition: SpecialistDefinition) -> SpecialistExecutor:
        executor = self.get(
            agent_id=definition.agent_id,
            agent_version=definition.version,
        )
        if executor.output_contract != definition.output_contract:
            raise SpecialistExecutionPolicyError(
                "specialist executor output contract does not match compiled policy"
            )
        return executor


class StaticProposalSpecialistExecutor:
    """Deterministic local proposal executor used for zero-cost runtime validation."""

    def __init__(
        self,
        *,
        agent_id: str,
        agent_version: str,
        output_contract: str,
        payload: SpecialistPlanPayload | dict[str, object],
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._agent_version = agent_version
        if output_contract != SPECIALIST_PLAN_OUTPUT_CONTRACT:
            raise SpecialistExecutionPolicyError(
                "static proposal executor requires the typed-plan output contract"
            )
        self._output_contract = output_contract
        self._payload = SpecialistPlanPayload.model_validate(payload)
        self._wall_clock_millis = wall_clock_millis or (lambda: int(time.time() * 1_000))
        # Validate the static fixture immediately rather than at execution time.
        canonical_size_bytes(self._payload)

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def agent_version(self) -> str:
        return self._agent_version

    @property
    def output_contract(self) -> str:
        return self._output_contract

    async def execute(
        self,
        *,
        request: SpecialistExecutionRequest,
        cancellation: SpecialistCancellation,
        budget: BudgetAccount,
    ) -> SpecialistExecutionResult:
        cancellation.raise_if_cancelled()
        if budget.request_id != request.request_id:
            raise SpecialistExecutionPolicyError(
                "specialist budget request identity does not match execution request"
            )
        if budget.limits != request.effective_budget:
            raise SpecialistExecutionPolicyError(
                "specialist budget limits do not match the derived effective budget"
            )
        if (
            request.agent_id != self.agent_id
            or request.agent_version != self.agent_version
            or request.output_contract != self.output_contract
        ):
            raise SpecialistExecutionPolicyError(
                "specialist execution request does not match executor identity"
            )
        if request.effect != InvocationEffect.PROPOSAL:
            raise SpecialistExecutionPolicyError(
                "static proposal executor accepts proposal invocations only"
            )
        cancellation.raise_if_cancelled()
        started_at_ms = max(0, int(self._wall_clock_millis()))
        return SpecialistExecutionResult(
            request_id=request.request_id,
            invocation_id=request.invocation_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            effect=request.effect,
            outcome=SpecialistExecutionOutcome.COMPLETED,
            output_contract=request.output_contract,
            payload=self._payload,
            committed_usage=UsageVector(),
            started_at_ms=started_at_ms,
            completed_at_ms=max(started_at_ms, int(self._wall_clock_millis())),
        )


def build_specialist_execution_request(
    *,
    task: TaskEnvelope,
    decision: RoutingDecision,
    definition: SpecialistDefinition,
    invocation_id: UUID,
    context_fingerprint: str,
    requested_capabilities: SpecialistCapabilitySet | None = None,
    created_at_ms: int | None = None,
) -> SpecialistExecutionRequest:
    """Derive, narrow, and validate one execution request from authoritative inputs."""

    if decision.state != RoutingState.ROUTED:
        raise SpecialistExecutionPolicyError("only a routed decision can be executed")
    if decision.request_id != task.request_id:
        raise SpecialistExecutionPolicyError(
            "routing decision request identity does not match the task"
        )
    if (
        decision.selected_agent_id != definition.agent_id
        or decision.selected_agent_version != definition.version
    ):
        raise SpecialistExecutionPolicyError(
            "routing decision specialist identity does not match compiled policy"
        )

    task_kind = _resolve_task_kind(task=task, definition=definition)
    effect = _execution_effect(definition=definition, mode=task.execution_mode)
    maximum_capabilities = _maximum_capabilities(task=task, definition=definition)
    capabilities = requested_capabilities or SpecialistCapabilitySet()
    capabilities.require_subset_of(maximum_capabilities)

    if effect == InvocationEffect.PROPOSAL and not capabilities.proposal_allowed:
        raise SpecialistExecutionPolicyError(
            "proposal execution requires an explicitly requested proposal capability"
        )
    if effect == InvocationEffect.MUTATION and not capabilities.typed_mutation_allowed:
        raise SpecialistExecutionPolicyError(
            "typed execution requires an explicitly requested mutation capability"
        )

    now = max(
        task.received_at_ms,
        int(time.time() * 1_000) if created_at_ms is None else created_at_ms,
    )
    task_payload = task.model_dump(mode="json")
    task_payload["allowed_data_sources"] = sorted(task.allowed_data_sources)
    effective_budget = intersect_budgets(task.budget, definition.budget_ceiling)
    return SpecialistExecutionRequest(
        request_id=task.request_id,
        invocation_id=invocation_id,
        context_bundle_id=uuid5(
            NAMESPACE_URL,
            f"simorgh-context:{task.request_id}:{context_fingerprint}",
        ),
        cancellation_owner_id=uuid5(
            NAMESPACE_URL,
            f"simorgh-cancellation:{task.request_id}:{invocation_id}",
        ),
        agent_id=definition.agent_id,
        agent_version=definition.version,
        task_kind=task_kind,
        execution_mode=task.execution_mode,
        effect=effect,
        input_contract=definition.input_contract,
        output_contract=definition.output_contract,
        task_fingerprint=canonical_fingerprint(task_payload),
        context_fingerprint=context_fingerprint,
        capabilities=capabilities,
        effective_budget=effective_budget,
        monotonic_timeout_ms=effective_budget.max_elapsed_ms,
        created_at_ms=now,
        deadline_at_ms=task.deadline_at_ms,
    )


def _resolve_task_kind(
    *,
    task: TaskEnvelope,
    definition: SpecialistDefinition,
) -> TaskKind:
    if task.explicit_task_kind is not None:
        if task.explicit_task_kind not in definition.task_kinds:
            raise SpecialistExecutionPolicyError(
                "explicit task kind is not supported by the selected specialist"
            )
        return task.explicit_task_kind
    if len(definition.task_kinds) != 1:
        raise SpecialistExecutionPolicyError(
            "implicit task kind is ambiguous for the selected specialist"
        )
    return next(iter(definition.task_kinds))


def _execution_effect(
    *,
    definition: SpecialistDefinition,
    mode: ExecutionMode,
) -> InvocationEffect:
    if mode == ExecutionMode.ROUTE_ONLY:
        raise SpecialistExecutionPolicyError("route-only tasks cannot execute a specialist")
    if mode == ExecutionMode.EXECUTE_TYPED:
        if definition.side_effect_policy != SideEffectPolicy.TYPED_EXECUTOR_ONLY:
            raise SpecialistExecutionPolicyError(
                "typed execution requires a typed-executor specialist policy"
            )
        return InvocationEffect.MUTATION
    if definition.side_effect_policy == SideEffectPolicy.PROPOSE_ONLY:
        return InvocationEffect.PROPOSAL
    return InvocationEffect.READ_ONLY


def _maximum_capabilities(
    *,
    task: TaskEnvelope,
    definition: SpecialistDefinition,
) -> SpecialistCapabilitySet:
    connectors = definition.connector_allowlist.intersection(task.allowed_data_sources)
    model_tiers = (
        frozenset(definition.model_policy.allowed_tiers)
        if definition.model_policy.maximum_model_calls > 0
        else frozenset()
    )
    proposal_allowed = definition.side_effect_policy in {
        SideEffectPolicy.PROPOSE_ONLY,
        SideEffectPolicy.TYPED_EXECUTOR_ONLY,
    }
    mutation_allowed = (
        definition.side_effect_policy == SideEffectPolicy.TYPED_EXECUTOR_ONLY
        and task.execution_mode == ExecutionMode.EXECUTE_TYPED
    )
    return SpecialistCapabilitySet(
        tool_ids=definition.tool_allowlist,
        connector_ids=connectors,
        model_tiers=model_tiers,
        proposal_allowed=proposal_allowed,
        typed_mutation_allowed=mutation_allowed,
    )
