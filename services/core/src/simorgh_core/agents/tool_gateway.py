from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from simorgh_core.agents.budget import BudgetAccount, BudgetError, ReservationKind
from simorgh_core.agents.contracts import SideEffectPolicy, UsageVector
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationStartKind,
    canonical_fingerprint,
)
from simorgh_core.agents.registry import (
    SpecialistPolicyError,
    SpecialistRegistry,
    SpecialistRegistryError,
)
from simorgh_core.agents.tracing import (
    CacheDisposition,
    NullTraceSink,
    TraceEventKind,
    TraceSink,
    trace_event,
)


class ToolEffect(StrEnum):
    READ_ONLY = "read_only"
    MUTATION = "mutation"


class ToolGatewayError(RuntimeError):
    pass


class ToolInvocationInProgressError(ToolGatewayError):
    pass


class ToolInvocationTerminalError(ToolGatewayError):
    pass


class ToolMutationBlockedError(ToolGatewayError):
    pass


class ToolInvoker(Protocol):
    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]: ...


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    request_id: UUID
    agent_id: str = Field(min_length=1, max_length=128)
    agent_version: str = Field(min_length=1, max_length=32)
    tool_id: str = Field(min_length=1, max_length=128)
    connector_id: str = Field(min_length=1, max_length=128)
    allowed_data_sources: frozenset[str] = Field(default_factory=frozenset, max_length=256)
    effect: ToolEffect = ToolEffect.READ_ONLY
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=256)

    @field_validator("allowed_data_sources")
    @classmethod
    def validate_data_sources(cls, value: frozenset[str]) -> frozenset[str]:
        for source in value:
            if not source or len(source) > 128:
                raise ValueError("data-source identifiers must be in 1..128 characters")
        return value


class ToolCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    tool_id: str
    connector_id: str
    payload: dict[str, Any]
    replayed: bool = False


class BudgetedToolGateway:
    """Enforce task and specialist policy, budget, and exact read replay."""

    def __init__(
        self,
        *,
        registry: SpecialistRegistry,
        invoker: ToolInvoker,
        invocation_store: InMemoryInvocationStore,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self._registry = registry
        self._invoker = invoker
        self._invocations = invocation_store
        self._trace_sink = trace_sink or NullTraceSink()

    async def invoke(
        self,
        *,
        request: ToolCallRequest,
        budget: BudgetAccount,
    ) -> ToolCallResult:
        try:
            definition = self._registry.get(request.agent_id)
            if definition.version != request.agent_version:
                raise SpecialistPolicyError(
                    "tool request agent version does not match the active specialist policy"
                )
            if request.connector_id not in request.allowed_data_sources:
                raise SpecialistPolicyError(
                    f"task does not allow data source {request.connector_id!r}"
                )
            self._registry.require_tool(
                agent_id=request.agent_id,
                tool_id=request.tool_id,
            )
            self._registry.require_connector(
                agent_id=request.agent_id,
                connector_id=request.connector_id,
            )
            if request.effect == ToolEffect.MUTATION:
                if definition.side_effect_policy != SideEffectPolicy.TYPED_EXECUTOR_ONLY:
                    raise ToolMutationBlockedError(
                        "specialist policy does not permit mutation execution"
                    )
                raise ToolMutationBlockedError(
                    "control-plane foundation does not execute mutation tools; use a reviewed "
                    "typed executor boundary"
                )
        except (SpecialistRegistryError, ToolMutationBlockedError) as exc:
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                cache=CacheDisposition.BYPASSED_POLICY,
                outcome="policy_blocked",
                reason=str(exc),
            )
            raise

        request_payload = request.model_dump(mode="json")
        request_payload["allowed_data_sources"] = sorted(request.allowed_data_sources)
        fingerprint = canonical_fingerprint(request_payload)
        started = self._invocations.begin(
            invocation_id=request.invocation_id,
            request_id=request.request_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            operation=f"tool:{request.tool_id}",
            input_fingerprint=fingerprint,
        )
        if started.kind == InvocationStartKind.REPLAY:
            payload = started.record.result_payload
            if payload is None:
                raise ToolGatewayError("completed tool invocation has no result payload")
            replayed = ToolCallResult.model_validate(payload)
            self._emit(
                request=request,
                kind=TraceEventKind.INVOCATION_REPLAYED,
                cache=CacheDisposition.HIT,
                outcome="completed",
                reason="exact completed tool invocation was replayed",
            )
            return replayed.model_copy(update={"replayed": True})
        if started.kind == InvocationStartKind.IN_PROGRESS:
            raise ToolInvocationInProgressError(
                f"tool invocation {request.invocation_id} is already in progress"
            )
        if started.kind == InvocationStartKind.TERMINAL:
            raise ToolInvocationTerminalError(
                started.record.failure_detail
                or f"tool invocation ended in {started.record.state.value}"
            )

        reserved_usage = UsageVector(tool_calls=1)
        try:
            reservation = budget.reserve(
                kind=ReservationKind.TOOL,
                usage=reserved_usage,
            )
        except BudgetError as exc:
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="budget_exhausted",
                failure_detail=str(exc),
            )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                outcome="budget_exhausted",
                reason=str(exc),
            )
            raise

        self._emit(
            request=request,
            kind=TraceEventKind.BUDGET_RESERVED,
            usage=reserved_usage,
            outcome="reserved",
            reason="one structured tool call was reserved before invocation",
        )
        self._emit(
            request=request,
            kind=TraceEventKind.TOOL_STARTED,
            cache=CacheDisposition.MISS,
            outcome="started",
            reason="approved structured tool invocation started",
        )
        try:
            payload = await self._invoker.invoke(
                tool_id=request.tool_id,
                arguments=request.arguments,
            )
        except Exception as exc:
            # The remote tool may have received the read request before transport failed. Keep the
            # call accounted and do not automatically issue another invocation identity.
            budget.commit_reserved(reservation.reservation_id)
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="tool_failure",
                failure_detail=f"{exc.__class__.__name__}: {exc}",
            )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                usage=reserved_usage,
                outcome="tool_failure",
                reason=f"structured tool failed closed with {exc.__class__.__name__}",
            )
            raise ToolGatewayError("structured tool invocation failed") from exc

        actual_usage = UsageVector(tool_calls=1)
        try:
            budget.reconcile(
                reservation_id=reservation.reservation_id,
                actual_usage=actual_usage,
            )
        except BudgetError as exc:
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="budget_reconciliation_failed",
                failure_detail=str(exc),
            )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                usage=actual_usage,
                outcome="budget_reconciliation_failed",
                reason=str(exc),
            )
            raise

        self._emit(
            request=request,
            kind=TraceEventKind.BUDGET_RECONCILED,
            usage=actual_usage,
            outcome="reconciled",
            reason="structured tool usage was reconciled",
        )
        result = ToolCallResult(
            invocation_id=request.invocation_id,
            tool_id=request.tool_id,
            connector_id=request.connector_id,
            payload=payload,
        )
        self._invocations.complete(
            invocation_id=request.invocation_id,
            result_payload=result.model_dump(mode="json"),
        )
        self._emit(
            request=request,
            kind=TraceEventKind.TOOL_COMPLETED,
            usage=actual_usage,
            outcome="completed",
            reason="structured tool result passed the typed gateway",
        )
        return result

    def _emit(
        self,
        *,
        request: ToolCallRequest,
        kind: TraceEventKind,
        cache: CacheDisposition = CacheDisposition.NOT_APPLICABLE,
        usage: UsageVector | None = None,
        outcome: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._trace_sink.emit(
            trace_event(
                request_id=request.request_id,
                invocation_id=request.invocation_id,
                kind=kind,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                tool_id=request.tool_id,
                cache=cache,
                usage=usage,
                outcome=outcome,
                reason=reason,
                metadata={
                    "connector_id": request.connector_id,
                    "effect": request.effect.value,
                },
            )
        )
