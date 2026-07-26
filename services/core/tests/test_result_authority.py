from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.invocations import InvocationEffect
from simorgh_core.agents.result_authority import (
    ArtifactReference,
    ArtifactStorageDisposition,
    DuplicateResultSchemaError,
    EvidenceCacheDisposition,
    EvidenceReference,
    PersianSpecialistPlanRenderer,
    PrivacyClassification,
    ResultContractError,
    ResultSchemaRegistry,
    RetentionDisposition,
    SpecialistPlanResultSchema,
    UnknownResultSchemaError,
    build_authoritative_plan_result,
    build_test_artifact_reference,
    result_canonical_sha256,
    validate_artifact_bytes,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistExecutionOutcome,
    SpecialistExecutionResult,
)


def _execution_result(
    *,
    request_id: UUID | None = None,
    invocation_id: UUID | None = None,
    summary: str = "برنامه پایدار",
) -> SpecialistExecutionResult:
    return SpecialistExecutionResult(
        request_id=request_id or uuid4(),
        invocation_id=invocation_id or uuid4(),
        agent_id="development.planner",
        agent_version="1.0.0",
        effect=InvocationEffect.PROPOSAL,
        outcome=SpecialistExecutionOutcome.COMPLETED,
        output_contract="simorgh.typed-plan.v1",
        payload={
            "summary": summary,
            "steps": ["قرارداد", "تست"],
            "unresolved_risks": ["اتصال زنده هنوز فعال نیست"],
            "verification_requirements": ["بازپخش پس از راه‌اندازی مجدد"],
        },
        started_at_ms=2_000,
        completed_at_ms=3_000,
    )


def _registry() -> ResultSchemaRegistry:
    return ResultSchemaRegistry((SpecialistPlanResultSchema(),))


def test_result_registry_is_exact_and_duplicate_safe() -> None:
    handler = SpecialistPlanResultSchema()
    with pytest.raises(DuplicateResultSchemaError, match="registered more than once"):
        ResultSchemaRegistry((handler, handler))

    registry = ResultSchemaRegistry((handler,))
    with pytest.raises(UnknownResultSchemaError, match="not registered"):
        registry.require(
            schema_id="simorgh.unknown-result",
            schema_version="1.0",
            output_contract="simorgh.typed-plan.v1",
            family="specialist_plan",
        )
    with pytest.raises(ResultContractError, match="does not match"):
        registry.require(
            schema_id="simorgh.specialist-plan-result",
            schema_version="1.0",
            output_contract="simorgh.other-result.v1",
            family="specialist_plan",
        )


def test_authoritative_result_rejects_raw_and_arbitrary_payloads() -> None:
    execution = _execution_result()
    dumped = execution.model_dump(mode="json")
    dumped["payload"] = "raw model text"
    with pytest.raises(ValidationError):
        SpecialistExecutionResult.model_validate(dumped)

    dumped["payload"] = {"summary": "valid", "unknown": "not registered"}
    with pytest.raises(ValidationError):
        SpecialistExecutionResult.model_validate(dumped)


def test_authoritative_result_hash_is_stable_and_presentation_neutral() -> None:
    execution = _execution_result()
    result = build_authoritative_plan_result(
        execution_result=execution,
        registry=_registry(),
    )
    before = result.canonical_sha256

    first = PersianSpecialistPlanRenderer().render(result, locale="fa-IR")
    second = PersianSpecialistPlanRenderer().render(result, locale="fa")

    assert first.text == second.text
    assert result.canonical_sha256 == before
    assert result_canonical_sha256(result) == before
    assert first.authoritative is False
    assert "ریسک‌های حل‌نشده" in first.text
    assert "نیازهای راستی‌آزمایی" in first.text


def test_renderer_uses_explicit_farsi_fallback_and_limit() -> None:
    result = build_authoritative_plan_result(
        execution_result=_execution_result(),
        registry=_registry(),
    )
    renderer = PersianSpecialistPlanRenderer()

    assert renderer.render(result, locale="en-US").locale == "fa-IR"
    with pytest.raises(ResultContractError, match="presentation limit"):
        renderer.render(result, max_characters=4)


def test_artifact_bytes_media_type_and_public_storage_are_fail_closed() -> None:
    execution = _execution_result()
    content = b"deterministic artifact bytes"
    artifact = build_test_artifact_reference(
        artifact_id=uuid4(),
        content=content,
        media_type="application/json",
        request_id=execution.request_id,
        invocation_id=execution.invocation_id,
        producer_agent_id=execution.agent_id,
        producer_agent_version=execution.agent_version,
        privacy=PrivacyClassification.SENSITIVE,
        retention=RetentionDisposition.PROJECT,
        created_at_ms=2_500,
    )

    validate_artifact_bytes(artifact, content)
    with pytest.raises(ResultContractError, match=r"declared size|declared hash"):
        validate_artifact_bytes(artifact, content + b"changed")

    public_candidate = artifact.model_copy(
        update={
            "storage_disposition": ArtifactStorageDisposition.PUBLIC_REFERENCE,
            "storage_reference": "https://example.invalid/public",
        }
    )
    with pytest.raises(ValidationError, match="non-public artifact"):
        ArtifactReference.model_validate(public_candidate.model_dump(mode="json"))

    invalid_media = artifact.model_copy(update={"media_type": "not a media type"})
    with pytest.raises(ValidationError):
        ArtifactReference.model_validate(invalid_media.model_dump(mode="json"))


def test_result_privacy_and_retention_compose_to_strictest_reference() -> None:
    execution = _execution_result()
    artifact = build_test_artifact_reference(
        artifact_id=uuid4(),
        content=b"private",
        media_type="application/octet-stream",
        request_id=execution.request_id,
        invocation_id=execution.invocation_id,
        producer_agent_id=execution.agent_id,
        producer_agent_version=execution.agent_version,
        privacy=PrivacyClassification.RESTRICTED,
        retention=RetentionDisposition.LEGAL_HOLD,
        created_at_ms=2_500,
    )
    evidence = EvidenceReference(
        evidence_id=uuid4(),
        source_id="fake.github.issue",
        connector_id="github.fake",
        tool_id="github.read.issue",
        observed_at_ms=2_400,
        fresh_until_ms=4_000,
        cache_disposition=EvidenceCacheDisposition.CACHE_HIT,
        untrusted_source=True,
        tainted=True,
        projection_sha256="a" * 64,
        citation_reference="issue:46",
        artifact_id=artifact.artifact_id,
        privacy=PrivacyClassification.SENSITIVE,
    )

    result = build_authoritative_plan_result(
        execution_result=execution,
        registry=_registry(),
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.SESSION,
        artifacts=(artifact,),
        evidence=(evidence,),
    )

    assert result.privacy == PrivacyClassification.RESTRICTED
    assert result.retention == RetentionDisposition.LEGAL_HOLD
    assert result.artifacts[0].artifact_id == artifact.artifact_id
    assert result.evidence[0].artifact_id == artifact.artifact_id


def test_evidence_reference_is_tainted_bounded_and_linked() -> None:
    with pytest.raises(ValidationError, match="retain taint"):
        EvidenceReference(
            evidence_id=uuid4(),
            source_id="fake.github.issue",
            observed_at_ms=2_400,
            cache_disposition=EvidenceCacheDisposition.LIVE,
            untrusted_source=True,
            tainted=False,
            projection_sha256="b" * 64,
            citation_reference="issue:46",
            privacy=PrivacyClassification.INTERNAL,
        )

    with pytest.raises(ValidationError, match="one bounded non-empty line"):
        EvidenceReference(
            evidence_id=uuid4(),
            source_id="fake.github.issue",
            observed_at_ms=2_400,
            cache_disposition=EvidenceCacheDisposition.LIVE,
            projection_sha256="b" * 64,
            citation_reference="raw\nprivate body",
            privacy=PrivacyClassification.INTERNAL,
        )

    execution = _execution_result()
    evidence = EvidenceReference(
        evidence_id=uuid4(),
        source_id="fake.github.issue",
        observed_at_ms=2_400,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        projection_sha256="b" * 64,
        citation_reference="issue:46",
        artifact_id=uuid4(),
        privacy=PrivacyClassification.INTERNAL,
    )
    with pytest.raises(ValidationError, match="outside the result"):
        build_authoritative_plan_result(
            execution_result=execution,
            registry=_registry(),
            evidence=(evidence,),
        )
