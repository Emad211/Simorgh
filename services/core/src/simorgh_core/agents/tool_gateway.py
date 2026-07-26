from __future__ import annotations

import asyncio
from contextlib import suppress
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from simorgh_core.agents.budget import (
    BudgetAccount,
    BudgetCancelledError,
    BudgetError,
    BudgetReservationNotFoundError,
    ReservationKind,
)
from simorgh_core.agents.contracts import SideEffectPolicy, UsageVector
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    InvocationStartKind,
    InvocationStateError,
    InvocationStore,
    InvocationStoreError,
    canonical_fingerprint,
    canonical_json,
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


class ToolResultRejectedError(ToolGatewayError):
    """Sanitized deterministic rejection after a structured tool returned."""


class ToolInvoker(Protocol):
    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]: ...


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

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

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = canonical_json(value).encode("utf-8")
        except ValueError:
            raise ValueError("tool arguments must be strict JSON data") from None
        if len(encoded) > 256_000:
            raise ValueError("tool arguments exceed the 256000-byte limit")
        return value


class ToolCallResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: UUID
    tool_id: str
    connector_id: str
    payload: dict[str, Any]
    replayed: bool = False

    @field_validator("payload")
    @classmethod
    def validate_json_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            canonical_json(value)
        except ValueError:
            raise ValueError("tool result payload must be strict JSON data") from None
        return value


class BudgetedToolGateway:
    """Enforce policy, durable reservation, and exact read-tool replay."""

    def __init__(
        self,
        *,
        registry: SpecialistRegistry,
        invoker: ToolInvoker,
        invocation_store: InvocationStore,
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
        self._require_budget_identity(request=request, budget=budget)
        self._require_policy(request)
        request_payload = request.model_dump(mode="json")
        request_payload["allowed_data_sources"] = sorted(request.allowed_data_sources)
        fingerprint = canonical_fingerprint(request_payload)
        try:
            started = self._invocations.begin(
                invocation_id=request.invocation_id,
                request_id=request.request_id,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                operation=f"tool:{request.tool_id}",
                input_fingerprint=fingerprint,
                kind=InvocationKind.TOOL,
                effect=InvocationEffect.READ_ONLY,
                tool_id=request.tool_id,
                connector_id=request.connector_id,
            )
        except InvocationStoreError as exc:
            raise ToolGatewayError("tool invocation identity could not be durably claimed") from exc

        if started.kind == InvocationStartKind.REPLAY:
            return self._replay_result(
                request=request,
                payload=started.record.result_payload,
                committed_usage=started.record.committed_usage,
            )
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
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="budget_exhausted",
                failure_detail=str(exc),
                committed_usage=UsageVector(),
            )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                outcome="budget_exhausted",
                reason=str(exc),
            )
            raise

        try:
            self._invocations.reserve(
                invocation_id=request.invocation_id,
                usage=reserved_usage,
            )
        except InvocationStoreError:
            with suppress(
                BudgetCancelledError,
                BudgetReservationNotFoundError,
            ):
                budget.release(reservation.reservation_id)
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                outcome="invocation_store_failure",
                reason="tool was not issued because durable reservation failed",
            )
            raise ToolGatewayError("tool invocation could not be durably reserved") from None

        self._emit(
            request=request,
            kind=TraceEventKind.BUDGET_RESERVED,
            usage=reserved_usage,
            outcome="reserved",
            reason="tool budget and durable invocation usage were reserved",
        )
        self._emit(
            request=request,
            kind=TraceEventKind.TOOL_STARTED,
            cache=CacheDisposition.MISS,
            outcome="started",
            reason="approved structured read tool invocation started",
        )
        try:
            payload = await self._invoker.invoke(
                tool_id=request.tool_id,
                arguments=request.arguments,
            )
        except ToolResultRejectedError:
            actual_usage = UsageVector(tool_calls=1)
            try:
                budget.reconcile(
                    reservation_id=reservation.reservation_id,
                    actual_usage=actual_usage,
                )
            except BudgetError as exc:
                self._record_failure(
                    invocation_id=request.invocation_id,
                    failure_code="budget_reconciliation_failed",
                    failure_detail="tool_result_rejection_reconciliation_failed",
                    committed_usage=actual_usage,
                )
                self._emit(
                    request=request,
                    kind=TraceEventKind.TOOL_FAILED,
                    usage=actual_usage,
                    outcome="budget_reconciliation_failed",
                    reason="rejected tool result usage could not be reconciled",
                )
                raise ToolGatewayError(
                    "rejected structured tool usage could not be reconciled"
                ) from exc
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="tool_result_rejected",
                failure_detail="typed_tool_result_rejected",
                committed_usage=actual_usage,
            )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                usage=actual_usage,
                outcome="tool_result_rejected",
                reason="structured tool returned a deterministic policy-invalid projection",
            )
            raise ToolGatewayError("structured tool result was rejected") from None
        except asyncio.CancelledError:
            with suppress(ToolGatewayError):
                self._mark_unknown_and_settle(
                    invocation_id=request.invocation_id,
                    failure_code="tool_call_cancelled",
                    failure_detail=(
                        "tool coroutine was cancelled after durable reservation; "
                        "completion is uncertain"
                    ),
                    budget=budget,
                    reservation_id=reservation.reservation_id,
                )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                usage=reserved_usage,
                outcome="unknown",
                reason="tool coroutine was cancelled after reservation",
            )
            raise
        except Exception as exc:
            self._mark_unknown_and_settle(
                invocation_id=request.invocation_id,
                failure_code="tool_transport_uncertain",
                failure_detail=exc.__class__.__name__,
                budget=budget,
                reservation_id=reservation.reservation_id,
            )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                usage=reserved_usage,
                outcome="unknown",
                reason=f"structured tool transport became uncertain with {exc.__class__.__name__}",
            )
            raise ToolGatewayError("structured tool invocation failed") from None

        actual_usage = UsageVector(tool_calls=1)
        try:
            budget.reconcile(
                reservation_id=reservation.reservation_id,
                actual_usage=actual_usage,
            )
        except BudgetError as exc:
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="budget_reconciliation_failed",
                failure_detail=str(exc),
                committed_usage=actual_usage,
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
        try:
            result = ToolCallResult(
                invocation_id=request.invocation_id,
                tool_id=request.tool_id,
                connector_id=request.connector_id,
                payload=payload,
            )
        except ValueError:
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="result_contract_invalid",
                failure_detail="typed_tool_result_rejected",
                committed_usage=actual_usage,
            )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                usage=actual_usage,
                outcome="result_contract_invalid",
                reason="tool result failed the typed JSON result contract",
            )
            raise ToolGatewayError(
                "structured tool result failed durable contract validation"
            ) from None
        try:
            self._invocations.complete(
                invocation_id=request.invocation_id,
                result_payload=result.model_dump(mode="json"),
                committed_usage=actual_usage,
            )
        except InvocationStateError:
            self._record_failure(
                invocation_id=request.invocation_id,
                failure_code="result_contract_invalid",
                failure_detail="typed_tool_result_rejected",
                committed_usage=actual_usage,
            )
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                usage=actual_usage,
                outcome="result_contract_invalid",
                reason="tool result failed the durable typed result contract",
            )
            raise ToolGatewayError(
                "structured tool result failed durable contract validation"
            ) from None
        except InvocationStoreError:
            self._emit(
                request=request,
                kind=TraceEventKind.TOOL_FAILED,
                usage=actual_usage,
                outcome="invocation_store_failure",
                reason="tool result could not be durably committed",
            )
            raise ToolGatewayError("tool result could not be durably committed") from None
        self._emit(
            request=request,
            kind=TraceEventKind.TOOL_COMPLETED,
            usage=actual_usage,
            outcome="completed",
            reason="structured tool result passed policy, budget, and durable validation",
        )
        return result

    def _require_budget_identity(
        self,
        *,
        request: ToolCallRequest,
        budget: BudgetAccount,
    ) -> None:
        if budget.request_id == request.request_id:
            return
        self._emit(
            request=request,
            kind=TraceEventKind.TOOL_FAILED,
            outcome="budget_identity_mismatch",
            reason="tool request and request budget identities do not match",
        )
        raise ToolGatewayError("tool request budget identity does not match request")

    def _require_policy(self, request: ToolCallRequest) -> None:
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

    def _replay_result(
        self,
        *,
        request: ToolCallRequest,
        payload: dict[str, Any] | None,
        committed_usage: UsageVector,
    ) -> ToolCallResult:
        if payload is None:
            raise ToolGatewayError("completed tool invocation has no result payload")
        replayed = ToolCallResult.model_validate(payload)
        expected_usage = UsageVector(tool_calls=1)
        if replayed.invocation_id != request.invocation_id:
            raise ToolGatewayError("durable tool result invocation identity does not match request")
        if replayed.tool_id != request.tool_id or replayed.connector_id != request.connector_id:
            raise ToolGatewayError("durable tool result target identity does not match request")
        if committed_usage != expected_usage:
            raise ToolGatewayError("durable tool result usage does not match invocation accounting")
        self._emit(
            request=request,
            kind=TraceEventKind.INVOCATION_REPLAYED,
            cache=CacheDisposition.HIT,
            outcome="completed",
            reason="exact completed tool invocation was replayed from durable state",
        )
        return replayed.model_copy(update={"replayed": True})

    def _mark_unknown_and_settle(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
        budget: BudgetAccount,
        reservation_id: UUID,
    ) -> None:
        store_failed = False
        try:
            self._invocations.mark_unknown(
                invocation_id=invocation_id,
                failure_code=failure_code,
                failure_detail=failure_detail,
            )
        except InvocationStoreError:
            store_failed = True

        try:
            budget.commit_reserved(reservation_id)
        except (BudgetCancelledError, BudgetReservationNotFoundError):
            pass
        except BudgetError:
            pass

        if store_failed:
            raise ToolGatewayError(
                "tool invocation uncertainty could not be durably recorded"
            ) from None

    def _record_failure(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
        committed_usage: UsageVector,
    ) -> None:
        try:
            self._invocations.fail(
                invocation_id=invocation_id,
                failure_code=failure_code,
                failure_detail=failure_detail,
                committed_usage=committed_usage,
            )
        except InvocationStoreError as exc:
            raise ToolGatewayError("tool invocation failure could not be durably recorded") from exc

    def _mark_unknown(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> None:
        try:
            self._invocations.mark_unknown(
                invocation_id=invocation_id,
                failure_code=failure_code,
                failure_detail=failure_detail,
            )
        except InvocationStoreError as exc:
            raise ToolGatewayError(
                "tool invocation uncertainty could not be durably recorded"
            ) from exc

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
