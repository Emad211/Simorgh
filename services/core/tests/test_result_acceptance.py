from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import (
    ExecutionMode,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import InMemoryInvocationStore, InvocationEffect
from simorgh_core.agents.result_authority import (
    ArtifactReference,
    EvidenceCacheDisposition,
    EvidenceReference,
    PersianSpecialistPlanRenderer,
    PrivacyClassification,
    RetentionDisposition,
    build_test_artifact_reference,
    default_result_schema_registry,
)
from simorgh_core.agents.result_service import (
    SpecialistResultControlPlane,
    SpecialistResultTerminalizer,
)
from simorgh_core.agents.result_store import InMemoryResultStore, SQLiteResultStore
from simorgh_core.agents.specialist_execution import (
    SpecialistCancellation,
    SpecialistExecutionOutcome,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    SpecialistExecutorRegistry,
)
from simorgh_core.agents.specialist_service import SpecialistExecutionControlPlane
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord

_CONTEXT_FINGERPRINT = "e" * 64


class StaticTaskReader:
    def __init__(self, record: AgentTaskRecord) -> None:
        self._record = record

    async def get(self, request_id: UUID) -> AgentTaskRecord:
        if request_id != self._record.request_id:
            raise KeyError(request_id)
        return self._record


class CountingProposalExecutor:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def agent_id(self) -> str:
        return "development.planner"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    @property
    def output_contract(self) -> str:
        return "simorgh.typed-plan.v1"

    async def execute(
        self,
        *,
        request: SpecialistExecutionRequest,
        cancellation: SpecialistCancellation,
        budget: BudgetAccount,
    ) -> SpecialistExecutionResult:
        del budget
        cancellation.raise_if_cancelled()
        self.calls += 1
        return SpecialistExecutionResult(
            request_id=request.request_id,
            invocation_id=request.invocation_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            effect=request.effect,
            outcome=SpecialistExecutionOutcome.COMPLETED,
            output_contract=request.output_contract,
            payload={
                "summary": "برنامه نهایی پایدار",
                "steps": ["اجرای متخصص", "ثبت نتیجه"],
                "verification_requirements": ["بازپخش دقیق"],
            },
            committed_usage=UsageVector(),
            started_at_ms=2_000,
            completed_at_ms=3_000,
        )


def _routed_record() -> AgentTaskRecord:
    task = TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=60_000,
        locale="fa-IR",
        input_text="برای نسخه بعدی سیمرغ برنامه توسعه بساز",
        requested_outcome="برنامه توسعه تایپ‌شده",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
        allowed_data_sources=frozenset({"github"}),
    )
    decision = RoutingDecision(
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="development.planner",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        reason="explicit development route",
    )
    account = BudgetAccount(
        request_id=task.request_id,
        limits=task.budget,
        monotonic_millis=lambda: 100,
    )
    return AgentTaskRecord(
        request_id=task.request_id,
        phase=AgentTaskPhase.ROUTED,
        created_at_ms=1_500,
        updated_at_ms=1_600,
        task=task,
        routing_decision=decision,
        budget=account.snapshot(),
        detail="routed acceptance fixture",
    )


def _specialist_control(
    *,
    record: AgentTaskRecord,
    invocation_store: InMemoryInvocationStore,
    executors: SpecialistExecutorRegistry,
) -> SpecialistExecutionControlPlane:
    return SpecialistExecutionControlPlane(
        task_reader=StaticTaskReader(record),
        policy_registry=default_specialist_registry(),
        executor_registry=executors,
        invocation_store=invocation_store,
        wall_clock_millis=lambda: 2_000,
        monotonic_millis=lambda: 100,
    )


def _terminalizer(
    *,
    invocation_store: InMemoryInvocationStore,
    result_store: InMemoryResultStore | SQLiteResultStore,
) -> SpecialistResultTerminalizer:
    return SpecialistResultTerminalizer(
        invocation_store=invocation_store,
        result_store=result_store,
        schema_registry=default_result_schema_registry(),
    )


@pytest.mark.asyncio
async def test_phase_13_to_14_exact_replay_does_not_reenter_executor_or_charge() -> None:
    record = _routed_record()
    invocation_id = uuid4()
    invocation_store = InMemoryInvocationStore()
    result_store = InMemoryResultStore()
    executor = CountingProposalExecutor()
    first_control = SpecialistResultControlPlane(
        specialist_control=_specialist_control(
            record=record,
            invocation_store=invocation_store,
            executors=SpecialistExecutorRegistry((executor,)),
        ),
        terminalizer=_terminalizer(
            invocation_store=invocation_store,
            result_store=result_store,
        ),
    )

    first = await first_control.execute(
        request_id=record.request_id,
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
    )
    committed_before = invocation_store.get(invocation_id).committed_usage

    replay_control = SpecialistResultControlPlane(
        specialist_control=_specialist_control(
            record=record,
            invocation_store=invocation_store,
            executors=SpecialistExecutorRegistry(),
        ),
        terminalizer=_terminalizer(
            invocation_store=invocation_store,
            result_store=result_store,
        ),
    )
    replay = await replay_control.execute(
        request_id=record.request_id,
        invocation_id=invocation_id,
        context_fingerprint=_CONTEXT_FINGERPRINT,
    )
    status = replay_control.status(result_id=first.result_id, locale="fa-IR")

    assert executor.calls == 1
    assert len(result_store.load()) == 1
    assert invocation_store.get(invocation_id).committed_usage == committed_before
    assert replay.result_id == first.result_id
    assert replay.canonical_sha256 == first.canonical_sha256
    assert replay.payload == first.payload
    assert status.result == first
    assert status.presentation is not None
    assert status.presentation.result_id == first.result_id
    assert status.presentation.authoritative is False


def _completed_execution() -> SpecialistExecutionResult:
    return SpecialistExecutionResult(
        request_id=uuid4(),
        invocation_id=uuid4(),
        agent_id="development.planner",
        agent_version="1.0.0",
        effect=InvocationEffect.PROPOSAL,
        outcome=SpecialistExecutionOutcome.COMPLETED,
        output_contract="simorgh.typed-plan.v1",
        payload={"summary": "خلاصه معتبر", "steps": ["ثبت شواهد"]},
        started_at_ms=2_000,
        completed_at_ms=3_000,
    )


def _complete_invocation(
    store: InMemoryInvocationStore,
    execution: SpecialistExecutionResult,
) -> None:
    store.begin(
        invocation_id=execution.invocation_id,
        request_id=execution.request_id,
        agent_id=execution.agent_id,
        agent_version=execution.agent_version,
        operation="specialist.execute",
        input_fingerprint="c" * 64,
        kind="specialist",
        effect=execution.effect,
    )
    store.complete(
        invocation_id=execution.invocation_id,
        result_payload=execution.model_dump(mode="json"),
        committed_usage=execution.committed_usage,
    )


def test_evidence_and_artifact_metadata_survive_sqlite_reopen(
    tmp_path: Path,
) -> None:
    execution = _completed_execution()
    invocation_store = InMemoryInvocationStore()
    _complete_invocation(invocation_store, execution)
    artifact = build_test_artifact_reference(
        artifact_id=uuid4(),
        content=b"bounded fake artifact",
        media_type="application/octet-stream",
        request_id=execution.request_id,
        invocation_id=execution.invocation_id,
        producer_agent_id=execution.agent_id,
        producer_agent_version=execution.agent_version,
        privacy=PrivacyClassification.SENSITIVE,
        retention=RetentionDisposition.LONG_LIVED,
        created_at_ms=2_500,
    )
    evidence = EvidenceReference(
        evidence_id=uuid4(),
        source_id="fake.github.pull-request",
        connector_id="github.fake",
        tool_id="github.read.pull-request",
        observed_at_ms=2_400,
        fresh_until_ms=4_000,
        cache_disposition=EvidenceCacheDisposition.CACHE_HIT,
        untrusted_source=True,
        tainted=True,
        projection_sha256="a" * 64,
        citation_reference="pull-request:48",
        artifact_id=artifact.artifact_id,
        privacy=PrivacyClassification.SENSITIVE,
    )
    path = tmp_path / "results.sqlite3"
    first_store = SQLiteResultStore(path)
    first = _terminalizer(
        invocation_store=invocation_store,
        result_store=first_store,
    ).terminalize(
        execution,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
        artifacts=(artifact,),
        evidence=(evidence,),
    )
    first_store.close()

    reopened = SQLiteResultStore(path)
    restored = reopened.get(first.result_id)
    presentation = PersianSpecialistPlanRenderer().render(restored)

    assert restored == first
    assert restored.artifacts == (artifact,)
    assert restored.evidence == (evidence,)
    assert restored.privacy == PrivacyClassification.SENSITIVE
    assert restored.retention == RetentionDisposition.LONG_LIVED
    assert evidence.source_id not in presentation.text
    assert evidence.citation_reference not in presentation.text
    reopened.close()


def test_oversized_private_inline_payload_is_rejected_without_echo() -> None:
    private_marker = "PRIVATE_RESULT_MARKER_54c7"
    steps = tuple(
        f"{index:03d}-{private_marker}-" + ("x" * 1_060)
        for index in range(256)
    )

    with pytest.raises(ValidationError) as raised:
        SpecialistExecutionResult(
            request_id=uuid4(),
            invocation_id=uuid4(),
            agent_id="development.planner",
            agent_version="1.0.0",
            effect=InvocationEffect.PROPOSAL,
            outcome=SpecialistExecutionOutcome.COMPLETED,
            output_contract="simorgh.typed-plan.v1",
            payload={"summary": "bounded", "steps": steps},
            started_at_ms=2_000,
            completed_at_ms=3_000,
        )

    assert "durable payload limit" in str(raised.value)
    assert private_marker not in str(raised.value)


def test_reference_models_reject_unregistered_extra_shape() -> None:
    execution = _completed_execution()
    artifact = build_test_artifact_reference(
        artifact_id=uuid4(),
        content=b"fake",
        media_type="application/octet-stream",
        request_id=execution.request_id,
        invocation_id=execution.invocation_id,
        producer_agent_id=execution.agent_id,
        producer_agent_version=execution.agent_version,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
        created_at_ms=2_500,
    )
    artifact_data = artifact.model_dump(mode="json")
    artifact_data["raw_bytes"] = "forbidden"

    with pytest.raises(ValidationError):
        ArtifactReference.model_validate(artifact_data)
