from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.budget import BudgetAccount, BudgetError, ReservationKind
from simorgh_core.agents.contracts import SideEffectPolicy, UsageVector
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationStartKind,
    canonical_fingerprint,
)
from simorgh_core.agents.registry import SpecialistPolicyError, SpecialistRegistry


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
    effect: ToolEffect = ToolEffect.READ_ONLY
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=256)


class ToolCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    tool_id: str
    connector_id: str
    payload: dict[str, Any]
    replayed: bool = False


class BudgetedToolGateway:
    """Enforce policy, one-call budget, and exact retry replay for structured tools."""

    def __init__(
        self,
        *,
        registry: SpecialistRegistry,
        invoker: ToolInvoker,
        invocation_store: InMemoryInvocationStore,
    ) -> None:
        self._registry = registry
        self._invoker = invoker
        self._invocations = invocation_store

    async def invoke(
        self,
        *,
        request: ToolCallRequest,
        budget: BudgetAccount,
    ) -> ToolCallResult:
        definition = self._registry.get(request.agent_id)
        if definition.version != request.agent_version:
            raise SpecialistPolicyError(
                "tool request agent version does not match the active specialist policy"
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

        fingerprint = canonical_fingerprint(request)
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

        try:
            reservation = budget.reserve(
                kind=ReservationKind.TOOL,
                usage=UsageVector(tool_calls=1),
            )
        except BudgetError as exc:
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="budget_exhausted",
                failure_detail=str(exc),
            )
            raise

        try:
            payload = await self._invoker.invoke(
                tool_id=request.tool_id,
                arguments=request.arguments,
            )
        except Exception as exc:
            # The remote tool may have received a read request before transport failed. Keep the
            # call accounted and do not automatically issue another invocation identity.
            budget.commit_reserved(reservation.reservation_id)
            self._invocations.fail(
                invocation_id=request.invocation_id,
                failure_code="tool_failure",
                failure_detail=f"{exc.__class__.__name__}: {exc}",
            )
            raise ToolGatewayError("structured tool invocation failed") from exc

        budget.reconcile(
            reservation_id=reservation.reservation_id,
            actual_usage=UsageVector(tool_calls=1),
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
        return result
