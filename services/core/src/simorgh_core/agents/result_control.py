from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.invocations import InvocationRecord
from simorgh_core.agents.result_authority import (
    ArtifactReference,
    EvidenceReference,
    PersianPlanRenderer,
    PrivacyClassification,
    RenderedPresentation,
    ResultReplayDisposition,
    ResultWrite,
    RetentionClass,
    SpecialistResultRecord,
)
from simorgh_core.agents.result_terminalizer import SpecialistResultAuthorityService
from simorgh_core.agents.specialist_execution import SpecialistExecutionResult
from simorgh_core.agents.tracing import (
    InMemoryTraceSink,
    NullTraceSink,
    TraceEventKind,
    TraceSink,
    trace_event,
)


class ResultStatus(BaseModel):
    """Presentation-neutral authority status with no private result content."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    result_id: UUID
    request_id: UUID
    invocation_id: UUID
    producer_agent_id: str = Field(min_length=1, max_length=128)
    producer_agent_version: str = Field(min_length=1, max_length=32)
    output_contract: str = Field(min_length=1, max_length=128)
    result_schema_version: str = Field(min_length=1, max_length=16)
    payload_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    privacy: PrivacyClassification
    retention: RetentionClass
    artifact_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    unresolved_risk_count: int = Field(ge=0)
    verification_requirement_count: int = Field(ge=0)
    created_at_ms: int = Field(ge=0)
    completed_at_ms: int = Field(ge=0)


class ResultAuthorityControlPlane:
    """Internal Core-only terminalize/read/render surface for authoritative results."""

    def __init__(
        self,
        *,
        authority: SpecialistResultAuthorityService,
        renderer: PersianPlanRenderer | None = None,
        trace_sink: TraceSink | None = None,
        wall_clock_millis: Callable[[], int] | None = None,
    ) -> None:
        self._authority = authority
        self._renderer = renderer or PersianPlanRenderer()
        self._traces = trace_sink or NullTraceSink()
        self._wall_clock_millis = wall_clock_millis or (
            lambda: int(time.time() * 1_000)
        )

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
        written = self._authority.terminalize(
            execution_result=execution_result,
            invocation=invocation,
            artifacts=artifacts,
            evidence=evidence,
            artifact_bytes=artifact_bytes,
            privacy=privacy,
            retention=retention,
        )
        self._emit_result_trace(
            record=written.record,
            disposition=written.disposition,
        )
        return written

    def get_status(self, result_id: UUID) -> ResultStatus:
        return _result_status(self._authority.get(result_id))

    def get_status_for_invocation(self, invocation_id: UUID) -> ResultStatus:
        return _result_status(self._authority.get_for_invocation(invocation_id))

    def render(self, result_id: UUID, *, locale: str = "fa-IR") -> RenderedPresentation:
        record = self._authority.get(result_id)
        before_hash = record.result_sha256
        rendered = self._renderer.render(record, locale=locale)
        if record.result_sha256 != before_hash or rendered.result_sha256 != before_hash:
            raise RuntimeError("result renderer changed authoritative result identity")
        self._traces.emit(
            trace_event(
                request_id=record.producer.request_id,
                invocation_id=record.producer.invocation_id,
                kind=TraceEventKind.TERMINAL,
                agent_id=record.producer.agent_id,
                agent_version=record.producer.agent_version,
                outcome="result_presentation_rendered",
                metadata={
                    "result_id": str(record.result_id),
                    "result_sha256": record.result_sha256,
                    "output_contract": record.output_contract,
                    "schema_version": record.result_schema_version,
                    "privacy": record.privacy.value,
                    "locale": rendered.locale,
                },
                wall_clock_millis=self._wall_clock_millis,
            )
        )
        return rendered

    def _emit_result_trace(
        self,
        *,
        record: SpecialistResultRecord,
        disposition: ResultReplayDisposition,
    ) -> None:
        kind = (
            TraceEventKind.INVOCATION_REPLAYED
            if disposition == ResultReplayDisposition.REPLAYED
            else TraceEventKind.TERMINAL
        )
        self._traces.emit(
            trace_event(
                request_id=record.producer.request_id,
                invocation_id=record.producer.invocation_id,
                kind=kind,
                agent_id=record.producer.agent_id,
                agent_version=record.producer.agent_version,
                usage=record.committed_usage,
                outcome=f"result_{disposition.value}",
                metadata={
                    "result_id": str(record.result_id),
                    "result_sha256": record.result_sha256,
                    "payload_sha256": record.payload_sha256,
                    "output_contract": record.output_contract,
                    "schema_version": record.result_schema_version,
                    "privacy": record.privacy.value,
                    "retention": record.retention.value,
                    "artifact_count": len(record.artifacts),
                    "evidence_count": len(record.evidence),
                },
                wall_clock_millis=self._wall_clock_millis,
            )
        )


def _result_status(record: SpecialistResultRecord) -> ResultStatus:
    return ResultStatus(
        result_id=record.result_id,
        request_id=record.producer.request_id,
        invocation_id=record.producer.invocation_id,
        producer_agent_id=record.producer.agent_id,
        producer_agent_version=record.producer.agent_version,
        output_contract=record.output_contract,
        result_schema_version=record.result_schema_version,
        payload_sha256=record.payload_sha256,
        result_sha256=record.result_sha256,
        privacy=record.privacy,
        retention=record.retention,
        artifact_count=len(record.artifacts),
        evidence_count=len(record.evidence),
        unresolved_risk_count=len(record.unresolved_risks),
        verification_requirement_count=len(record.verification_requirements),
        created_at_ms=record.created_at_ms,
        completed_at_ms=record.completed_at_ms,
    )


__all__ = [
    "InMemoryTraceSink",
    "ResultAuthorityControlPlane",
    "ResultStatus",
]
