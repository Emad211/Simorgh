from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import (
    RoutingDecision,
    SpecialistDefinition,
    TaskEnvelope,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InvocationKind,
    InvocationRecord,
    InvocationStartKind,
    InvocationStore,
    InvocationStoreError,
    canonical_fingerprint,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistCapabilitySet,
    SpecialistExecutionCancelledError,
    SpecialistExecutionOutcome,
    SpecialistExecutionPolicyError,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    SpecialistExecutorRegistry,
    SpecialistReplayDisposition,
    SpecialistResultContractError,
    build_specialist_execution_request,
)
from simorgh_core.agents.tracing import (
    NullTraceSink,
    TraceEventKind,
    TraceSink,
    trace_event,
)

_SPECIALIST_OPERATION = "specialist.execute"
_ZERO_USAGE = UsageVector()


class SpecialistRuntimeError(RuntimeError):
    """Base class for governed specialist-runtime failures."""


class SpecialistInvocationInProgressError(SpecialistRuntimeError):
    pass


class SpecialistInvocationTerminalError(SpecialistRuntimeError):
    pass


class SpecialistExecutionExpiredError(SpecialistRuntimeError):
    pass


class SpecialistExecutionStoreError(SpecialistRuntimeError):
    pass


class SpecialistExecutionRuntime:
    """Execute and durably replay exactly one selected specialist implementation."""

    def __init__(
        self,
        *,
        executor_registry: SpecialistExecutorRegistry,
        invocation_store: InvocationStore,
        trace_sink: TraceSink | None = None,
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        self._executors = executor_registry
        self._invocations = invocation_store
        self._traces = trace_sink or NullTraceSink()
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )

    async def execute(
        self,
        *,
        task: TaskEnvelope,
        decision: RoutingDecision,
        definition: SpecialistDefinition,
        invocation_id: UUID,
        context_fingerprint: str,
        capabilities: SpecialistCapabilitySet,
        budget: BudgetAccount,
        cancellation: SpecialistCancellation | None = None,
    ) -> SpecialistExecutionResult:
        token = cancellation or SpecialistCancellation()
        request = build_specialist_execution_request(
            task=task,
            decision=decision,
            definition=definition,
            invocation_id=invocation_id,
            context_fingerprint=context_fingerprint,
            requested_capabilities=capabilities,
            # Creation identity must survive process restart. Current time is checked separately
            # for execution admission and is intentionally excluded from durable input identity.
            created_at_ms=task.received_at_ms,
        )
        token.require_owner(request.cancellation_owner_id)
        self._require_budget(request=request, budget=budget)
        fingerprint = specialist_execution_fingerprint(request)

        try:
            started = self._invocations.begin(
                invocation_id=request.invocation_id,
                request_id=request.request_id,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                operation=_SPECIALIST_OPERATION,
                input_fingerprint=fingerprint,
                kind=InvocationKind.SPECIALIST,
                effect=request.effect,
            )
        except InvocationStoreError as exc:
            raise SpecialistExecutionStoreError(
                "specialist invocation identity could not be durably claimed"
            ) from exc

        if started.kind == InvocationStartKind.REPLAY:
            replayed = self._replay_completed(
                request=request,
                record=started.record,
            )
            self._emit_trace(
                request=request,
                kind=TraceEventKind.INVOCATION_REPLAYED,
                outcome=replayed.outcome.value,
                usage=replayed.committed_usage,
                replayed=True,
            )
            return replayed
        if started.kind == InvocationStartKind.IN_PROGRESS:
            raise SpecialistInvocationInProgressError(
                f"specialist invocation {request.invocation_id} is already in progress"
            )
        if started.kind == InvocationStartKind.TERMINAL:
            raise SpecialistInvocationTerminalError(
                started.record.failure_detail
                or f"specialist invocation ended in {started.record.state.value}"
            )

        try:
            self._require_not_cancelled(
                budget=budget,
                cancellation=token,
            )
            self._require_not_expired(request)
            self._require_elapsed_available(budget)
            # Executor availability is required only for a new invocation. Completed durable
            # replay must not depend on the current in-process implementation registry.
            executor = self._executors.require_definition(definition)
            self._emit_trace(
                request=request,
                kind=TraceEventKind.SPECIALIST_STARTED,
                outcome="started",
            )
            raw_result = await executor.execute(
                request=request,
                cancellation=token,
                budget=budget,
            )
            result = validate_specialist_result(
                request=request,
                raw_result=raw_result,
            )
            self._require_not_cancelled(
                budget=budget,
                cancellation=token,
            )
            self._require_not_expired(request)
            self._require_elapsed_available(budget)
        except SpecialistExecutionCancelledError:
            self._emit_trace(
                request=request,
                kind=TraceEventKind.SPECIALIST_FAILED,
                outcome=SpecialistExecutionOutcome.CANCELLED.value,
                reason="specialist_cancelled",
            )
            self._cancel_invocation(request.invocation_id)
            raise
        except SpecialistExecutionExpiredError:
            self._emit_trace(
                request=request,
                kind=TraceEventKind.SPECIALIST_FAILED,
                outcome=SpecialistExecutionOutcome.EXPIRED.value,
                reason="specialist_expired",
            )
            self._expire_invocation(request.invocation_id)
            raise
        except asyncio.CancelledError:
            self._emit_trace(
                request=request,
                kind=TraceEventKind.SPECIALIST_FAILED,
                outcome=SpecialistExecutionOutcome.UNKNOWN.value,
                reason="specialist_coroutine_cancelled",
            )
            self._mark_unknown(
                invocation_id=request.invocation_id,
                failure_code="specialist_coroutine_cancelled",
                failure_detail=(
                    "specialist coroutine was interrupted before durable completion"
                ),
            )
            raise
        except (ValidationError, SpecialistResultContractError) as exc:
            self._emit_trace(
                request=request,
                kind=TraceEventKind.SPECIALIST_FAILED,
                outcome=SpecialistExecutionOutcome.FAILED.value,
                reason="specialist_result_contract_invalid",
            )
            self._fail_invocation(
                invocation_id=request.invocation_id,
                failure_code="specialist_result_contract_invalid",
                failure_detail=exc.__class__.__name__,
            )
            raise SpecialistResultContractError(
                "specialist result failed typed contract validation"
            ) from exc
        except SpecialistExecutionPolicyError as exc:
            self._emit_trace(
                request=request,
                kind=TraceEventKind.SPECIALIST_FAILED,
                outcome=SpecialistExecutionOutcome.FAILED.value,
                reason="specialist_policy_failure",
            )
            self._fail_invocation(
                invocation_id=request.invocation_id,
                failure_code="specialist_policy_failure",
                failure_detail=exc.__class__.__name__,
            )
            raise
        except Exception as exc:
            self._emit_trace(
                request=request,
                kind=TraceEventKind.SPECIALIST_FAILED,
                outcome=SpecialistExecutionOutcome.FAILED.value,
                reason="specialist_execution_failure",
            )
            self._fail_invocation(
                invocation_id=request.invocation_id,
                failure_code="specialist_execution_failure",
                failure_detail=exc.__class__.__name__,
            )
            raise SpecialistRuntimeError("specialist implementation failed") from exc

        try:
            self._invocations.complete(
                invocation_id=request.invocation_id,
                result_payload=result.model_dump(mode="json"),
                committed_usage=result.committed_usage,
            )
        except InvocationStoreError as exc:
            self._mark_unknown_after_completion_failure(
                invocation_id=request.invocation_id,
            )
            self._emit_trace(
                request=request,
                kind=TraceEventKind.SPECIALIST_FAILED,
                outcome=SpecialistExecutionOutcome.UNKNOWN.value,
                reason="specialist_result_commit_failed",
            )
            raise SpecialistExecutionStoreError(
                "specialist result could not be durably committed"
            ) from exc
        self._emit_trace(
            request=request,
            kind=TraceEventKind.SPECIALIST_COMPLETED,
            outcome=result.outcome.value,
            usage=result.committed_usage,
        )
        return result

    def _replay_completed(
        self,
        *,
        request: SpecialistExecutionRequest,
        record: InvocationRecord,
    ) -> SpecialistExecutionResult:
        payload = record.result_payload
        if payload is None:
            raise SpecialistResultContractError(
                "completed specialist invocation has no durable result payload"
            )
        try:
            result = SpecialistExecutionResult.model_validate(payload)
        except ValidationError as exc:
            raise SpecialistResultContractError(
                "durable specialist result failed typed validation"
            ) from exc
        validate_specialist_result(request=request, raw_result=result)
        if result.committed_usage != record.committed_usage:
            raise SpecialistResultContractError(
                "durable specialist result usage does not match invocation accounting"
            )
        return result.model_copy(
            update={"replay": SpecialistReplayDisposition.REPLAYED}
        )

    def _require_budget(
        self,
        *,
        request: SpecialistExecutionRequest,
        budget: BudgetAccount,
    ) -> None:
        if budget.request_id != request.request_id:
            raise SpecialistExecutionPolicyError(
                "specialist budget request identity does not match execution request"
            )
        if budget.limits != request.effective_budget:
            raise SpecialistExecutionPolicyError(
                "specialist budget limits do not match the effective policy intersection"
            )
        snapshot = budget.snapshot()
        if snapshot.exhausted_dimension is not None:
            raise SpecialistExecutionPolicyError(
                "exhausted specialist budget cannot enter execution"
            )

    def _require_elapsed_available(self, budget: BudgetAccount) -> None:
        snapshot = budget.snapshot()
        if snapshot.elapsed_ms > budget.limits.max_elapsed_ms:
            raise SpecialistExecutionExpiredError(
                "specialist elapsed budget has expired"
            )

    def _require_not_cancelled(
        self,
        *,
        budget: BudgetAccount,
        cancellation: SpecialistCancellation,
    ) -> None:
        cancellation.raise_if_cancelled()
        if budget.snapshot().cancelled:
            raise SpecialistExecutionCancelledError(
                "specialist parent task budget was cancelled"
            )

    def _require_not_expired(self, request: SpecialistExecutionRequest) -> None:
        if request.deadline_at_ms is not None and self._now_ms() >= request.deadline_at_ms:
            raise SpecialistExecutionExpiredError(
                "specialist execution deadline has expired"
            )

    def _cancel_invocation(self, invocation_id: UUID) -> None:
        try:
            self._invocations.cancel(invocation_id)
        except InvocationStoreError as exc:
            raise SpecialistExecutionStoreError(
                "specialist cancellation could not be durably recorded"
            ) from exc

    def _expire_invocation(self, invocation_id: UUID) -> None:
        try:
            self._invocations.expire(invocation_id)
        except InvocationStoreError as exc:
            raise SpecialistExecutionStoreError(
                "specialist expiry could not be durably recorded"
            ) from exc

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
            raise SpecialistExecutionStoreError(
                "specialist uncertainty could not be durably recorded"
            ) from exc

    def _mark_unknown_after_completion_failure(self, *, invocation_id: UUID) -> None:
        try:
            self._invocations.mark_unknown(
                invocation_id=invocation_id,
                failure_code="specialist_result_commit_failed",
                failure_detail=(
                    "specialist execution returned but durable completion failed"
                ),
            )
        except InvocationStoreError:
            # The caller receives a storage failure and no success claim. If the store itself is
            # unhealthy, startup recovery remains the authoritative uncertainty path.
            return

    def _fail_invocation(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> None:
        try:
            self._invocations.fail(
                invocation_id=invocation_id,
                failure_code=failure_code,
                failure_detail=failure_detail,
                committed_usage=_ZERO_USAGE,
            )
        except InvocationStoreError as exc:
            raise SpecialistExecutionStoreError(
                "specialist failure could not be durably recorded"
            ) from exc

    def _emit_trace(
        self,
        *,
        request: SpecialistExecutionRequest,
        kind: TraceEventKind,
        outcome: str,
        usage: UsageVector | None = None,
        reason: str | None = None,
        replayed: bool = False,
    ) -> None:
        self._traces.emit(
            trace_event(
                request_id=request.request_id,
                invocation_id=request.invocation_id,
                kind=kind,
                agent_id=request.agent_id,
                agent_version=request.agent_version,
                usage=usage,
                outcome=outcome,
                reason=reason,
                metadata={
                    "context_bundle_id": str(request.context_bundle_id),
                    "output_contract": request.output_contract,
                    "effect": request.effect.value,
                    "replayed": replayed,
                    "monotonic_timeout_ms": request.monotonic_timeout_ms,
                },
                wall_clock_millis=self._wall_clock_millis,
            )
        )

    def _now_ms(self) -> int:
        return max(0, int(self._wall_clock_millis()))


def specialist_execution_fingerprint(request: SpecialistExecutionRequest) -> str:
    payload: dict[str, Any] = request.model_dump(mode="json")
    payload.pop("created_at_ms", None)
    capabilities = payload["capabilities"]
    if not isinstance(capabilities, dict):
        raise SpecialistResultContractError(
            "specialist capability payload is not a JSON object"
        )
    for key in ("tool_ids", "connector_ids", "model_tiers"):
        value = capabilities[key]
        if not isinstance(value, list):
            raise SpecialistResultContractError(
                "specialist capability collection is not a JSON list"
            )
        capabilities[key] = sorted(value)
    return canonical_fingerprint(payload)


def validate_specialist_result(
    *,
    request: SpecialistExecutionRequest,
    raw_result: SpecialistExecutionResult,
) -> SpecialistExecutionResult:
    try:
        result = SpecialistExecutionResult.model_validate(
            raw_result.model_dump(mode="json")
        )
    except (AttributeError, ValidationError) as exc:
        raise SpecialistResultContractError(
            "specialist implementation returned an invalid typed result"
        ) from exc
    if result.outcome != SpecialistExecutionOutcome.COMPLETED:
        raise SpecialistResultContractError(
            "specialist implementation returned a non-completed result directly"
        )
    identity = (
        result.request_id,
        result.invocation_id,
        result.agent_id,
        result.agent_version,
        result.effect,
        result.output_contract,
    )
    expected = (
        request.request_id,
        request.invocation_id,
        request.agent_id,
        request.agent_version,
        request.effect,
        request.output_contract,
    )
    if identity != expected:
        raise SpecialistResultContractError(
            "specialist result identity does not match execution request"
        )
    if result.replay != SpecialistReplayDisposition.FRESH:
        raise SpecialistResultContractError(
            "specialist implementation cannot claim durable replay"
        )
    if result.committed_usage != _ZERO_USAGE:
        raise SpecialistResultContractError(
            "native specialist result cannot bypass governed model/tool accounting"
        )
    return result
