from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable
from uuid import UUID

from simorgh_core.agents.invocations import (
    InvocationKind,
    InvocationPhase,
    InvocationRecord,
    canonical_fingerprint,
)
from simorgh_core.agents.result_authority import (
    ArtifactReference,
    EvidenceReference,
    PrivacyClassification,
    ResultAuthorityError,
    ResultConflictError,
    ResultProducer,
    ResultSchemaRegistry,
    ResultStore,
    ResultWrite,
    RetentionClass,
    SpecialistResultRecord,
    create_specialist_plan_result,
    default_result_schema_registry,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistExecutionOutcome,
    SpecialistExecutionResult,
    SpecialistReplayDisposition,
)


class ResultTerminalizationError(ResultAuthorityError):
    pass


class ResultInvocationMismatchError(ResultTerminalizationError):
    pass


@runtime_checkable
class ArtifactAwareResultStore(Protocol):
    def put_with_artifacts(
        self,
        record: SpecialistResultRecord,
        *,
        artifact_bytes: Mapping[UUID, bytes],
    ) -> ResultWrite: ...


class SpecialistResultAuthorityService:
    """Terminalize one durable specialist completion into immutable result authority."""

    def __init__(
        self,
        *,
        store: ResultStore,
        schema_registry: ResultSchemaRegistry | None = None,
    ) -> None:
        self._store = store
        self._schemas = schema_registry or default_result_schema_registry()

    def terminalize(
        self,
        *,
        execution_result: SpecialistExecutionResult,
        invocation: InvocationRecord,
        artifacts: tuple[ArtifactReference, ...] = (),
        evidence: tuple[EvidenceReference, ...] = (),
        artifact_bytes: Mapping[UUID, bytes] | None = None,
        privacy: PrivacyClassification = PrivacyClassification.INTERNAL,
        retention: RetentionClass = RetentionClass.PROJECT,
    ) -> ResultWrite:
        self._validate_invocation(
            execution_result=execution_result,
            invocation=invocation,
        )
        if execution_result.payload is None:
            raise ResultTerminalizationError(
                "completed specialist execution has no typed payload"
            )
        durable_result_payload = invocation.result_payload
        if durable_result_payload is None:
            raise ResultTerminalizationError(
                "completed specialist invocation has no durable result payload"
            )
        record = create_specialist_plan_result(
            producer=ResultProducer(
                request_id=invocation.request_id,
                invocation_id=invocation.invocation_id,
                agent_id=invocation.agent_id,
                agent_version=invocation.agent_version,
            ),
            payload=execution_result.payload,
            artifacts=artifacts,
            evidence=evidence,
            privacy=privacy,
            retention=retention,
            committed_usage=invocation.committed_usage,
            invocation_result_sha256=canonical_fingerprint(durable_result_payload),
            created_at_ms=invocation.created_at_ms,
            completed_at_ms=invocation.updated_at_ms,
            registry=self._schemas,
        )
        blobs = dict(artifact_bytes or {})
        if blobs:
            if not isinstance(self._store, ArtifactAwareResultStore):
                raise ResultTerminalizationError(
                    "configured result store cannot persist local artifact bytes"
                )
            return self._store.put_with_artifacts(
                record, artifact_bytes=blobs
            )
        return self._store.put(record)

    def get(self, result_id: UUID) -> SpecialistResultRecord:
        return self._store.get(result_id)

    def get_for_invocation(self, invocation_id: UUID) -> SpecialistResultRecord:
        return self._store.get_for_invocation(invocation_id)

    def _validate_invocation(
        self,
        *,
        execution_result: SpecialistExecutionResult,
        invocation: InvocationRecord,
    ) -> None:
        if invocation.kind != InvocationKind.SPECIALIST:
            raise ResultTerminalizationError(
                "only a specialist invocation can produce specialist result authority"
            )
        if invocation.state != InvocationPhase.COMPLETED:
            raise ResultTerminalizationError(
                "authoritative result requires a completed specialist invocation"
            )
        if invocation.result_payload is None:
            raise ResultTerminalizationError(
                "completed specialist invocation has no durable result payload"
            )
        if execution_result.outcome != SpecialistExecutionOutcome.COMPLETED:
            raise ResultTerminalizationError(
                "only completed specialist execution can be terminalized"
            )
        identity = (
            execution_result.request_id,
            execution_result.invocation_id,
            execution_result.agent_id,
            execution_result.agent_version,
            execution_result.committed_usage,
        )
        expected = (
            invocation.request_id,
            invocation.invocation_id,
            invocation.agent_id,
            invocation.agent_version,
            invocation.committed_usage,
        )
        if identity != expected:
            raise ResultInvocationMismatchError(
                "specialist result identity does not match invocation authority"
            )
        try:
            stored_result = SpecialistExecutionResult.model_validate(
                invocation.result_payload
            )
        except ValueError:
            raise ResultTerminalizationError(
                "durable specialist invocation result failed typed validation"
            ) from None
        incoming_payload = execution_result.model_dump(mode="json")
        stored_payload = stored_result.model_dump(mode="json")
        incoming_payload["replay"] = SpecialistReplayDisposition.FRESH.value
        stored_payload["replay"] = SpecialistReplayDisposition.FRESH.value
        if canonical_fingerprint(incoming_payload) != canonical_fingerprint(stored_payload):
            raise ResultInvocationMismatchError(
                "specialist result content does not match durable invocation completion"
            )


def require_same_result_authority(
    first: SpecialistResultRecord,
    second: SpecialistResultRecord,
) -> None:
    if first.result_id != second.result_id or first.result_sha256 != second.result_sha256:
        raise ResultConflictError("result replay changed immutable authority identity")
