from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.result_authority import (
    ArtifactReference,
    ArtifactStorageDisposition,
    DuplicateResultSchemaError,
    EvidenceCacheDisposition,
    EvidenceFreshness,
    EvidenceReference,
    EvidenceTaint,
    InMemoryResultStore,
    PersianPlanRenderer,
    PrivacyClassification,
    ResultConflictError,
    ResultNotFoundError,
    ResultProducer,
    ResultReplayDisposition,
    ResultSchemaRegistration,
    ResultSchemaRegistry,
    ResultStoreClosedError,
    RetentionClass,
    SpecialistResultRecord,
    UnknownResultSchemaError,
    UnsupportedResultLocaleError,
    create_specialist_plan_result,
    default_result_schema_registry,
)
from simorgh_core.agents.specialist_results import (
    SPECIALIST_PLAN_OUTPUT_CONTRACT,
    SpecialistPlanPayload,
)


def _producer() -> ResultProducer:
    return ResultProducer(
        request_id=uuid4(),
        invocation_id=uuid4(),
        agent_id="development.planner",
        agent_version="1.0.0",
    )


def _payload() -> SpecialistPlanPayload:
    return SpecialistPlanPayload(
        summary="برنامه مرحله‌ای معتبر",
        steps=("تعریف قرارداد", "اجرای تست"),
        unresolved_risks=("ذخیره‌سازی SQLite هنوز اضافه نشده است",),
        verification_requirements=("Ruff و MyPy و pytest اجرا شوند",),
    )


def _artifact(
    producer: ResultProducer,
    *,
    privacy: PrivacyClassification = PrivacyClassification.PRIVATE,
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uuid4(),
        sha256="a" * 64,
        media_type="application/json",
        size_bytes=128,
        producer=producer,
        privacy=privacy,
        retention=RetentionClass.PROJECT,
        storage_disposition=ArtifactStorageDisposition.CORE_LOCAL,
        storage_reference="result-artifacts/fixture.json",
        created_at_ms=2_000,
    )


def _evidence(
    *,
    artifact_id: UUID | None = None,
    privacy: PrivacyClassification = PrivacyClassification.PRIVATE,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=uuid4(),
        source_id="fixture.local",
        retrieved_at_ms=1_900,
        freshness=EvidenceFreshness.FRESH,
        cache=EvidenceCacheDisposition.NOT_APPLICABLE,
        taint=EvidenceTaint.CLEAN,
        projection_sha256="b" * 64,
        citation_reference="fixture:1",
        artifact_id=artifact_id,
        privacy=privacy,
    )


def _record(
    *,
    producer: ResultProducer | None = None,
    artifacts: tuple[ArtifactReference, ...] = (),
    evidence: tuple[EvidenceReference, ...] = (),
    privacy: PrivacyClassification = PrivacyClassification.PRIVATE,
) -> SpecialistResultRecord:
    return create_specialist_plan_result(
        producer=producer or _producer(),
        payload=_payload(),
        artifacts=artifacts,
        evidence=evidence,
        privacy=privacy,
        retention=RetentionClass.PROJECT,
        invocation_usage_sha256="c" * 64,
        invocation_result_sha256="d" * 64,
        created_at_ms=1_000,
        completed_at_ms=3_000,
    )


def _rehash(
    record: SpecialistResultRecord,
    **updates: object,
) -> SpecialistResultRecord:
    provisional = record.model_copy(
        update={**updates, "result_sha256": "0" * 64}
    )
    result_hash = canonical_fingerprint(provisional._hash_payload())
    return SpecialistResultRecord.model_validate(
        provisional.model_copy(
            update={"result_sha256": result_hash}
        ).model_dump(mode="json")
    )


def test_default_registry_validates_the_exact_plan_contract() -> None:
    registry = default_result_schema_registry()

    validated = registry.validate(
        output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
        schema_version="1.0",
        payload=_payload(),
    )

    assert isinstance(validated, SpecialistPlanPayload)
    assert validated.summary == "برنامه مرحله‌ای معتبر"


def test_schema_registry_rejects_duplicates_and_unknown_versions() -> None:
    registration = ResultSchemaRegistration(
        output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
        schema_version="1.0",
        payload_model=SpecialistPlanPayload,
    )

    with pytest.raises(DuplicateResultSchemaError):
        ResultSchemaRegistry((registration, registration))

    registry = ResultSchemaRegistry((registration,))
    with pytest.raises(UnknownResultSchemaError):
        registry.get(
            output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
            schema_version="2.0",
        )


def test_arbitrary_or_extra_final_payload_is_rejected_without_private_echo() -> None:
    private_marker = "PRIVATE_RESULT_MARKER_b17c"

    with pytest.raises(ValidationError) as raised:
        create_specialist_plan_result(
            producer=_producer(),
            payload={
                "summary": "valid summary",
                "steps": [],
                "arbitrary": private_marker,
            },
            privacy=PrivacyClassification.PRIVATE,
            retention=RetentionClass.PROJECT,
            invocation_usage_sha256="c" * 64,
            invocation_result_sha256="d" * 64,
            created_at_ms=1_000,
            completed_at_ms=2_000,
        )

    assert private_marker not in str(raised.value)


def test_artifact_public_storage_cannot_hold_private_data() -> None:
    producer = _producer()

    with pytest.raises(ValidationError, match="public storage"):
        ArtifactReference(
            artifact_id=uuid4(),
            sha256="a" * 64,
            media_type="application/json",
            size_bytes=128,
            producer=producer,
            privacy=PrivacyClassification.PRIVATE,
            retention=RetentionClass.PROJECT,
            storage_disposition=ArtifactStorageDisposition.PUBLIC,
            storage_reference="https://example.invalid/result.json",
            created_at_ms=2_000,
        )


def test_result_hashes_and_reference_identity_are_validated() -> None:
    producer = _producer()
    artifact = _artifact(producer)
    evidence = _evidence(artifact_id=artifact.artifact_id)
    record = _record(
        producer=producer,
        artifacts=(artifact,),
        evidence=(evidence,),
    )

    assert record.payload_sha256 != record.result_sha256
    assert record.payload.summary == "برنامه مرحله‌ای معتبر"

    with pytest.raises(ValidationError, match="result hash"):
        SpecialistResultRecord.model_validate(
            record.model_copy(update={"result_sha256": "f" * 64}).model_dump(
                mode="json"
            )
        )

    with pytest.raises(ValidationError, match="outside the result"):
        _record(
            producer=producer,
            evidence=(_evidence(artifact_id=uuid4()),),
        )


def test_result_privacy_cannot_downgrade_child_references() -> None:
    producer = _producer()
    artifact = _artifact(
        producer,
        privacy=PrivacyClassification.SENSITIVE,
    )

    with pytest.raises(ValidationError, match="privacy cannot be weaker"):
        _record(
            producer=producer,
            artifacts=(artifact,),
            privacy=PrivacyClassification.PRIVATE,
        )


def test_in_memory_store_creates_replays_and_rejects_mutation() -> None:
    store = InMemoryResultStore()
    record = _record()

    created = store.put(record)
    replayed = store.put(record)

    assert created.disposition == ResultReplayDisposition.CREATED
    assert replayed.disposition == ResultReplayDisposition.REPLAYED
    assert store.get(record.result_id) == record
    assert store.get_for_invocation(record.producer.invocation_id) == record
    assert store.load() == (record,)

    with pytest.raises(ResultConflictError):
        store.put(_rehash(record, retention=RetentionClass.LONG_LIVED))


def test_in_memory_store_allows_only_one_result_per_invocation() -> None:
    store = InMemoryResultStore()
    producer = _producer()
    first = _record(producer=producer)
    store.put(first)
    different_id = _rehash(first, result_id=uuid4())

    with pytest.raises(ResultConflictError, match="already owns"):
        store.put(different_id)


def test_in_memory_store_not_found_and_closed_behavior() -> None:
    store = InMemoryResultStore()

    with pytest.raises(ResultNotFoundError):
        store.get(uuid4())
    with pytest.raises(ResultNotFoundError):
        store.get_for_invocation(uuid4())

    store.close()

    with pytest.raises(ResultStoreClosedError):
        store.load()


def test_persian_renderer_is_deterministic_and_non_authoritative() -> None:
    record = _record()
    renderer = PersianPlanRenderer()

    first = renderer.render(record, locale="fa-IR")
    second = renderer.render(record, locale="fa-IR")

    assert first == second
    assert first.result_id == record.result_id
    assert first.result_sha256 == record.result_sha256
    assert "مراحل:" in first.body
    assert "ریسک‌های حل‌نشده:" in first.body
    assert "نیازهای راستی‌آزمایی:" in first.body
    assert record == _record(
        producer=record.producer,
        privacy=record.privacy,
    )


def test_persian_renderer_rejects_implicit_locale_fallback() -> None:
    with pytest.raises(UnsupportedResultLocaleError, match="Persian"):
        PersianPlanRenderer().render(_record(), locale="en-US")
