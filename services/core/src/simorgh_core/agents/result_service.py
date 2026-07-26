from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from simorgh_core.agents.invocations import (
    InvocationKind,
    InvocationPhase,
    InvocationStore,
    InvocationStoreError,
)
from simorgh_core.agents.result_authority import (
    ArtifactReference,
    AuthoritativeSpecialistResult,
    EvidenceReference,
    PersianSpecialistPlanRenderer,
    PrivacyClassification,
    RenderedPresentation,
    ResultContractError,
    ResultReplayDisposition,
    ResultSchemaRegistry,
    RetentionDisposition,
    build_authoritative_plan_result,
    privacy_is_at_least,
    retention_is_at_least,
)
from simorgh_core.agents.result_store import (
    ResultClaimKind,
    ResultNotFoundError,
    ResultStore,
    ResultStoreError,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistExecutionResult,
    SpecialistReplayDisposition,
)
from simorgh_core.agents.specialist_service import SpecialistExecutionControlPlane
from simorgh_core.agents.tracing import (
    NullTraceSink,
    TraceEventKind,
    TraceSink,
    trace_event,
)


class ResultTerminalizationError(RuntimeError):
    """Base class for safe specialist-result terminalization failures."""


class ResultInvocationMismatchError(ResultTerminalizationError):
    pass


class ResultAuthorityUnavailableError(ResultTerminalizationError):
    pass


class ResultReplayConflictError(ResultTerminalizationError):
    pass


class TypedResultStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    result: AuthoritativeSpecialistResult
    presentation: RenderedPresentation | None = None


class SpecialistResultTerminalizer:
    """Cross-check a completed invocation and claim one immutable typed result."""

    def __init__(
        self,
        *,
        invocation_store: InvocationStore,
        result_store: ResultStore,
        schema_registry: ResultSchemaRegistry,
        renderer: PersianSpecialistPlanRenderer | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self._invocations = invocation_store
        self._results = result_store
        self._schemas = schema_registry
        self._renderer = renderer or PersianSpecialistPlanRenderer()
        self._traces = trace_sink or NullTraceSink()

    def terminalize(
        self,
        execution_result: SpecialistExecutionResult,
        *,
        privacy: PrivacyClassification | None = None,
        retention: RetentionDisposition | None = None,
        artifacts: Iterable[ArtifactReference] | None = None,
        evidence: Iterable[EvidenceReference] | None = None,
    ) -> AuthoritativeSpecialistResult:
        normalized = execution_result.model_copy(
            update={"replay": SpecialistReplayDisposition.FRESH}
        )
        try:
            normalized = SpecialistExecutionResult.model_validate(
                normalized.model_dump(mode="json")
            )
            durable_execution = self._load_durable_execution(normalized)
            existing = self._load_existing(normalized.invocation_id)
            if existing is not None:
                self._validate_replay_request(
                    existing=existing,
                    execution=durable_execution,
                    privacy=privacy,
                    retention=retention,
                    artifacts=artifacts,
                    evidence=evidence,
                )
                replayed = existing.model_copy(
                    update={"replay": ResultReplayDisposition.REPLAYED}
                )
                self._emit_result_trace(
                    result=replayed,
                    kind=TraceEventKind.RESULT_REPLAYED,
                )
                return replayed

            candidate = build_authoritative_plan_result(
                execution_result=durable_execution,
                registry=self._schemas,
                privacy=privacy or PrivacyClassification.INTERNAL,
                retention=retention or RetentionDisposition.PROJECT,
                artifacts=artifacts or (),
                evidence=evidence or (),
            )
            claim = self._results.claim(candidate)
            if claim.kind == ResultClaimKind.REPLAY:
                _require_result_matches_execution(claim.record, durable_execution)
                replayed = claim.record.model_copy(
                    update={"replay": ResultReplayDisposition.REPLAYED}
                )
                self._emit_result_trace(
                    result=replayed,
                    kind=TraceEventKind.RESULT_REPLAYED,
                )
                return replayed
            self._emit_result_trace(
                result=claim.record,
                kind=TraceEventKind.RESULT_COMMITTED,
            )
            return claim.record
        except ResultTerminalizationError as exc:
            self._emit_failure_trace(normalized, reason=exc.__class__.__name__)
            raise
        except (ResultContractError, ResultStoreError, ValidationError, ValueError) as exc:
            self._emit_failure_trace(normalized, reason=exc.__class__.__name__)
            raise ResultAuthorityUnavailableError(
                "typed specialist result could not be durably terminalized"
            ) from exc

    def get(self, result_id: UUID) -> AuthoritativeSpecialistResult:
        try:
            return self._results.get(result_id)
        except (ResultNotFoundError, ResultStoreError) as exc:
            raise ResultAuthorityUnavailableError(
                "authoritative specialist result could not be loaded"
            ) from exc

    def get_by_invocation(self, invocation_id: UUID) -> AuthoritativeSpecialistResult:
        try:
            return self._results.get_by_invocation(invocation_id)
        except (ResultNotFoundError, ResultStoreError) as exc:
            raise ResultAuthorityUnavailableError(
                "authoritative specialist result could not be loaded"
            ) from exc

    def status(
        self,
        *,
        result_id: UUID,
        locale: str | None = None,
    ) -> TypedResultStatus:
        result = self.get(result_id)
        presentation = (
            self._renderer.render(result, locale=locale or "fa-IR")
            if locale is not None
            else None
        )
        return TypedResultStatus(result=result, presentation=presentation)

    def _load_durable_execution(
        self,
        execution: SpecialistExecutionResult,
    ) -> SpecialistExecutionResult:
        try:
            invocation = self._invocations.get(execution.invocation_id)
        except InvocationStoreError as exc:
            raise ResultAuthorityUnavailableError(
                "completed specialist invocation could not be loaded safely"
            ) from exc
        if invocation.state != InvocationPhase.COMPLETED:
            raise ResultInvocationMismatchError(
                "only a completed specialist invocation can create a result authority"
            )
        if invocation.kind != InvocationKind.SPECIALIST:
            raise ResultInvocationMismatchError(
                "authoritative specialist result requires a specialist invocation"
            )
        if invocation.result_payload is None:
            raise ResultInvocationMismatchError(
                "completed specialist invocation has no typed result payload"
            )
        try:
            durable_execution = SpecialistExecutionResult.model_validate(
                invocation.result_payload
            )
        except ValidationError as exc:
            raise ResultInvocationMismatchError(
                "durable specialist invocation result failed typed validation"
            ) from exc
        if durable_execution != execution:
            raise ResultInvocationMismatchError(
                "specialist result does not match the durable invocation payload"
            )
        if invocation.committed_usage != execution.committed_usage:
            raise ResultInvocationMismatchError(
                "specialist result usage does not match durable invocation accounting"
            )
        return durable_execution

    def _load_existing(
        self,
        invocation_id: UUID,
    ) -> AuthoritativeSpecialistResult | None:
        try:
            return self._results.get_by_invocation(invocation_id)
        except ResultNotFoundError:
            return None
        except ResultStoreError as exc:
            raise ResultAuthorityUnavailableError(
                "typed specialist result authority could not be inspected"
            ) from exc

    def _validate_replay_request(
        self,
        *,
        existing: AuthoritativeSpecialistResult,
        execution: SpecialistExecutionResult,
        privacy: PrivacyClassification | None,
        retention: RetentionDisposition | None,
        artifacts: Iterable[ArtifactReference] | None,
        evidence: Iterable[EvidenceReference] | None,
    ) -> None:
        _require_result_matches_execution(existing, execution)
        if privacy is not None and not privacy_is_at_least(existing.privacy, privacy):
            raise ResultReplayConflictError(
                "replay cannot strengthen or rewrite immutable result privacy"
            )
        if retention is not None and not retention_is_at_least(
            existing.retention,
            retention,
        ):
            raise ResultReplayConflictError(
                "replay cannot extend or rewrite immutable result retention"
            )
        if artifacts is not None:
            incoming_artifacts = tuple(
                sorted(artifacts, key=lambda item: str(item.artifact_id))
            )
            if incoming_artifacts != existing.artifacts:
                raise ResultReplayConflictError(
                    "replay supplied different immutable artifact metadata"
                )
        if evidence is not None:
            incoming_evidence = tuple(
                sorted(evidence, key=lambda item: str(item.evidence_id))
            )
            if incoming_evidence != existing.evidence:
                raise ResultReplayConflictError(
                    "replay supplied different immutable evidence metadata"
                )

    def _emit_result_trace(
        self,
        *,
        result: AuthoritativeSpecialistResult,
        kind: TraceEventKind,
    ) -> None:
        self._traces.emit(
            trace_event(
                request_id=result.request_id,
                invocation_id=result.invocation_id,
                kind=kind,
                agent_id=result.producer_agent_id,
                agent_version=result.producer_agent_version,
                outcome="completed",
                metadata={
                    "result_id": str(result.result_id),
                    "result_schema_id": result.result_schema_id,
                    "result_schema_version": result.result_schema_version,
                    "canonical_sha256": result.canonical_sha256,
                    "artifact_count": len(result.artifacts),
                    "evidence_count": len(result.evidence),
                    "privacy": result.privacy.value,
                    "retention": result.retention.value,
                    "replayed": result.replay == ResultReplayDisposition.REPLAYED,
                },
            )
        )

    def _emit_failure_trace(
        self,
        execution: SpecialistExecutionResult,
        *,
        reason: str,
    ) -> None:
        self._traces.emit(
            trace_event(
                request_id=execution.request_id,
                invocation_id=execution.invocation_id,
                kind=TraceEventKind.RESULT_FAILED,
                agent_id=execution.agent_id,
                agent_version=execution.agent_version,
                outcome="failed",
                reason=reason,
                metadata={"output_contract": execution.output_contract},
            )
        )


class SpecialistResultControlPlane:
    """Execute Phase 1.3, then withhold success until Phase 1.4 is durable."""

    def __init__(
        self,
        *,
        specialist_control: SpecialistExecutionControlPlane,
        terminalizer: SpecialistResultTerminalizer,
    ) -> None:
        self._specialists = specialist_control
        self._terminalizer = terminalizer

    async def execute(
        self,
        *,
        request_id: UUID,
        invocation_id: UUID,
        context_fingerprint: str,
        privacy: PrivacyClassification | None = None,
        retention: RetentionDisposition | None = None,
    ) -> AuthoritativeSpecialistResult:
        execution_result = await self._specialists.execute(
            request_id=request_id,
            invocation_id=invocation_id,
            context_fingerprint=context_fingerprint,
        )
        return self._terminalizer.terminalize(
            execution_result,
            privacy=privacy,
            retention=retention,
        )

    def get_result(self, result_id: UUID) -> AuthoritativeSpecialistResult:
        return self._terminalizer.get(result_id)

    def get_result_by_invocation(
        self,
        invocation_id: UUID,
    ) -> AuthoritativeSpecialistResult:
        return self._terminalizer.get_by_invocation(invocation_id)

    def status(
        self,
        *,
        result_id: UUID,
        locale: str | None = None,
    ) -> TypedResultStatus:
        return self._terminalizer.status(result_id=result_id, locale=locale)


def _require_result_matches_execution(
    result: AuthoritativeSpecialistResult,
    execution: SpecialistExecutionResult,
) -> None:
    identity = (
        result.request_id,
        result.invocation_id,
        result.producer_agent_id,
        result.producer_agent_version,
        result.output_contract,
        result.payload,
        result.committed_usage_invocation_id,
        result.created_at_ms,
        result.completed_at_ms,
    )
    expected = (
        execution.request_id,
        execution.invocation_id,
        execution.agent_id,
        execution.agent_version,
        execution.output_contract,
        execution.payload,
        execution.invocation_id,
        execution.started_at_ms,
        execution.completed_at_ms,
    )
    if identity != expected:
        raise ResultInvocationMismatchError(
            "authoritative result does not match the durable specialist invocation"
        )
