from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
)
from simorgh_core.agents.result_authority import (
    ArtifactReference,
    ArtifactStorageDisposition,
    EvidenceCacheDisposition,
    EvidenceFreshness,
    EvidenceReference,
    EvidenceTaint,
    InMemoryResultStore,
    PrivacyClassification,
    ResultConflictError,
    ResultProducer,
    ResultReplayDisposition,
    RetentionClass,
    create_specialist_plan_result,
)
from simorgh_core.agents.result_store import (
    ArtifactBytesNotFoundError,
    ArtifactIntegrityError,
    ResultStoreCorruptionError,
    ResultStoreSchemaError,
    SQLiteResultStore,
)
from simorgh_core.agents.result_terminalizer import (
    ResultInvocationMismatchError,
    ResultTerminalizationError,
    SpecialistResultAuthorityService,
)
from simorgh_core.agents.specialist_execution import (
    SpecialistExecutionOutcome,
    SpecialistExecutionResult,
)
from simorgh_core.agents.specialist_results import SPECIALIST_PLAN_OUTPUT_CONTRACT


def _artifact_bytes() -> bytes:
    return b'{"kind":"fixture","value":1}'


def _producer() -> ResultProducer:
    return ResultProducer(
        request_id=uuid4(),
        invocation_id=uuid4(),
        agent_id="development.planner",
        agent_version="1.0.0",
    )


def _artifact(producer: ResultProducer, payload: bytes) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uuid4(),
        sha256=hashlib.sha256(payload).hexdigest(),
        media_type="application/json",
        size_bytes=len(payload),
        producer=producer,
        privacy=PrivacyClassification.PRIVATE,
        retention=RetentionClass.PROJECT,
        storage_disposition=ArtifactStorageDisposition.CORE_LOCAL,
        storage_reference="sqlite:inline-fixture",
        created_at_ms=1_500,
    )


def _evidence(artifact_id: object) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=uuid4(),
        source_id="fixture.local",
        retrieved_at_ms=1_400,
        freshness=EvidenceFreshness.FRESH,
        cache=EvidenceCacheDisposition.NOT_APPLICABLE,
        taint=EvidenceTaint.CLEAN,
        projection_sha256="b" * 64,
        citation_reference="fixture:result-store",
        artifact_id=artifact_id,
        privacy=PrivacyClassification.PRIVATE,
    )


def _record_with_artifact() -> tuple[object, ArtifactReference, bytes]:
    producer = _producer()
    payload = _artifact_bytes()
    artifact = _artifact(producer, payload)
    evidence = _evidence(artifact.artifact_id)
    record = create_specialist_plan_result(
        producer=producer,
        payload={
            "summary": "برنامهٔ ذخیره‌شده",
            "steps": ["ثبت نتیجه", "بازخوانی"],
            "unresolved_risks": ["دادهٔ زنده هنوز متصل نیست"],
            "verification_requirements": ["SQLite reopen"],
        },
        artifacts=(artifact,),
        evidence=(evidence,),
        privacy=PrivacyClassification.PRIVATE,
        retention=RetentionClass.PROJECT,
        committed_usage=UsageVector(),
        invocation_result_sha256="c" * 64,
        created_at_ms=1_000,
        completed_at_ms=2_000,
    )
    return record, artifact, payload


def _completed_specialist_invocation() -> tuple[
    SpecialistExecutionResult,
    object,
]:
    request_id = uuid4()
    invocation_id = uuid4()
    result = SpecialistExecutionResult(
        request_id=request_id,
        invocation_id=invocation_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        effect=InvocationEffect.PROPOSAL,
        outcome=SpecialistExecutionOutcome.COMPLETED,
        output_contract=SPECIALIST_PLAN_OUTPUT_CONTRACT,
        payload={
            "summary": "برنامهٔ نهایی",
            "steps": ["قرارداد", "تست"],
            "unresolved_risks": ["بدون منبع زنده"],
            "verification_requirements": ["CI سبز"],
        },
        committed_usage=UsageVector(),
        started_at_ms=1_500,
        completed_at_ms=2_000,
    )
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id=result.agent_id,
        agent_version=result.agent_version,
        operation="specialist.execute",
        input_fingerprint="a" * 64,
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.PROPOSAL,
    )
    invocation = store.complete(
        invocation_id=invocation_id,
        result_payload=result.model_dump(mode="json"),
        committed_usage=result.committed_usage,
    )
    return result, invocation


def test_sqlite_result_and_artifact_bytes_replay_after_reopen(tmp_path: Path) -> None:
    record, artifact, payload = _record_with_artifact()
    path = tmp_path / "results.sqlite3"

    first_store = SQLiteResultStore(path)
    created = first_store.put_with_artifacts(
        record,
        artifact_bytes={artifact.artifact_id: payload},
    )
    assert created.disposition == ResultReplayDisposition.CREATED
    assert first_store.get_artifact_bytes(artifact.artifact_id) == payload
    first_store.close()

    reopened = SQLiteResultStore(path)
    loaded = reopened.get(record.result_id)
    replayed = reopened.put_with_artifacts(
        record,
        artifact_bytes={artifact.artifact_id: payload},
    )

    assert loaded == record
    assert reopened.get_for_invocation(record.producer.invocation_id) == record
    assert reopened.load() == (record,)
    assert replayed.disposition == ResultReplayDisposition.REPLAYED
    assert reopened.get_artifact_bytes(artifact.artifact_id) == payload
    reopened.close()


def test_artifact_bytes_hash_size_and_registration_are_enforced(tmp_path: Path) -> None:
    record, artifact, payload = _record_with_artifact()
    store = SQLiteResultStore(tmp_path / "results.sqlite3")

    with pytest.raises(ArtifactIntegrityError, match="size"):
        store.put_with_artifacts(
            record,
            artifact_bytes={artifact.artifact_id: payload + b"x"},
        )

    with pytest.raises(ArtifactIntegrityError, match="unregistered"):
        store.put_with_artifacts(
            record,
            artifact_bytes={uuid4(): payload},
        )

    assert store.load() == ()
    with pytest.raises(ArtifactBytesNotFoundError):
        store.get_artifact_bytes(artifact.artifact_id)
    store.close()


def test_sqlite_result_identity_is_immutable(tmp_path: Path) -> None:
    record, _, _ = _record_with_artifact()
    store = SQLiteResultStore(tmp_path / "results.sqlite3")
    store.put(record)
    changed = create_specialist_plan_result(
        producer=record.producer,
        payload={
            "summary": "محتوای متفاوت",
            "steps": [],
            "unresolved_risks": [],
            "verification_requirements": [],
        },
        privacy=record.privacy,
        retention=record.retention,
        committed_usage=record.committed_usage,
        invocation_result_sha256=record.invocation_result_sha256,
        created_at_ms=record.created_at_ms,
        completed_at_ms=record.completed_at_ms,
    )

    with pytest.raises(ResultConflictError, match="different immutable"):
        store.put(changed)
    store.close()


def test_sqlite_payload_hash_corruption_fails_closed(tmp_path: Path) -> None:
    record, _, _ = _record_with_artifact()
    path = tmp_path / "results.sqlite3"
    store = SQLiteResultStore(path)
    store.put(record)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE result_records SET payload_sha256 = ? WHERE result_id = ?",
        ("f" * 64, str(record.result_id)),
    )
    connection.commit()
    connection.close()

    with pytest.raises(ResultStoreCorruptionError, match="hash"):
        SQLiteResultStore(path)


def test_sqlite_unsupported_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "results.sqlite3"
    store = SQLiteResultStore(path)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE result_store_meta SET value = '999' WHERE key = 'schema_version'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(ResultStoreSchemaError, match="unsupported"):
        SQLiteResultStore(path)


def test_terminalizer_binds_result_to_durable_invocation() -> None:
    execution_result, invocation = _completed_specialist_invocation()
    store = InMemoryResultStore()
    authority = SpecialistResultAuthorityService(store=store)

    created = authority.terminalize(
        execution_result=execution_result,
        invocation=invocation,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionClass.PROJECT,
    )
    replayed = authority.terminalize(
        execution_result=execution_result,
        invocation=invocation,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionClass.PROJECT,
    )

    assert created.disposition == ResultReplayDisposition.CREATED
    assert replayed.disposition == ResultReplayDisposition.REPLAYED
    assert created.record.committed_usage == invocation.committed_usage
    assert created.record.invocation_result_sha256 != "0" * 64
    assert authority.get_for_invocation(invocation.invocation_id) == created.record


def test_terminalizer_rejects_changed_or_noncompleted_invocation() -> None:
    execution_result, invocation = _completed_specialist_invocation()
    authority = SpecialistResultAuthorityService(store=InMemoryResultStore())
    changed = execution_result.model_copy(
        update={"payload": {"summary": "changed", "steps": []}}
    )

    with pytest.raises(ResultInvocationMismatchError, match="content"):
        authority.terminalize(
            execution_result=changed,
            invocation=invocation,
        )

    pending_store = InMemoryInvocationStore(wall_clock_millis=lambda: 2_000)
    pending = pending_store.begin(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="specialist.execute",
        input_fingerprint="d" * 64,
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.PROPOSAL,
    ).record
    with pytest.raises(ResultTerminalizationError, match="completed"):
        authority.terminalize(
            execution_result=execution_result,
            invocation=pending,
        )
