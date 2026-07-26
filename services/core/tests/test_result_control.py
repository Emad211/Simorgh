from __future__ import annotations

from uuid import uuid4

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
    canonical_fingerprint,
)
from simorgh_core.agents.result_authority import (
    InMemoryResultStore,
    PrivacyClassification,
    ResultReplayDisposition,
    RetentionClass,
)
from simorgh_core.agents.result_control import ResultAuthorityControlPlane
from simorgh_core.agents.result_terminalizer import SpecialistResultAuthorityService
from simorgh_core.agents.specialist_execution import (
    SpecialistExecutionOutcome,
    SpecialistExecutionResult,
)
from simorgh_core.agents.specialist_results import SPECIALIST_PLAN_OUTPUT_CONTRACT
from simorgh_core.agents.tracing import InMemoryTraceSink, TraceEventKind


def _completed_result(private_marker: str) -> tuple[SpecialistExecutionResult, object]:
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
            "summary": f"برنامه خصوصی {private_marker}",
            "steps": ["ثبت نتیجه", "رندر فارسی"],
            "unresolved_risks": ["منبع زنده متصل نیست"],
            "verification_requirements": ["CI مستقل"],
        },
        committed_usage=UsageVector(),
        started_at_ms=2_000,
        completed_at_ms=3_000,
    )
    store = InMemoryInvocationStore(wall_clock_millis=lambda: 3_000)
    store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id=result.agent_id,
        agent_version=result.agent_version,
        operation="specialist.execute",
        input_fingerprint="e" * 64,
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.PROPOSAL,
    )
    invocation = store.complete(
        invocation_id=invocation_id,
        result_payload=result.model_dump(mode="json"),
        committed_usage=result.committed_usage,
    )
    return result, invocation


def test_control_plane_terminalizes_reads_renders_and_replays_without_content_trace() -> None:
    private_marker = "PRIVATE_RESULT_CONTROL_87ac"
    execution_result, invocation = _completed_result(private_marker)
    traces = InMemoryTraceSink()
    result_store = InMemoryResultStore()
    control = ResultAuthorityControlPlane(
        authority=SpecialistResultAuthorityService(store=result_store),
        trace_sink=traces,
        wall_clock_millis=lambda: 4_000,
    )

    created = control.terminalize(
        execution_result=execution_result,
        invocation=invocation,
        privacy=PrivacyClassification.PRIVATE,
        retention=RetentionClass.PROJECT,
    )
    replayed = control.terminalize(
        execution_result=execution_result,
        invocation=invocation,
        privacy=PrivacyClassification.PRIVATE,
        retention=RetentionClass.PROJECT,
    )

    assert created.disposition == ResultReplayDisposition.CREATED
    assert replayed.disposition == ResultReplayDisposition.REPLAYED
    assert created.record.result_id == replayed.record.result_id
    assert created.record.result_sha256 == replayed.record.result_sha256

    status = control.get_status(created.record.result_id)
    status_by_invocation = control.get_status_for_invocation(invocation.invocation_id)
    assert status == status_by_invocation
    assert status.result_sha256 == created.record.result_sha256
    assert status.invocation_usage_sha256 == canonical_fingerprint(
        invocation.committed_usage
    )
    assert status.invocation_result_sha256 == canonical_fingerprint(
        invocation.result_payload
    )
    assert status.privacy == PrivacyClassification.PRIVATE
    assert status.unresolved_risk_count == 1
    assert status.verification_requirement_count == 1
    assert "payload" not in status.model_dump(mode="json")

    before_hash = created.record.result_sha256
    rendered = control.render(created.record.result_id, locale="fa-IR")
    assert private_marker in rendered.body
    assert rendered.result_sha256 == before_hash
    assert result_store.get(created.record.result_id).result_sha256 == before_hash

    events = traces.for_request(invocation.request_id)
    assert len(events) == 3
    assert {event.kind for event in events} == {
        TraceEventKind.TERMINAL,
        TraceEventKind.INVOCATION_REPLAYED,
    }
    encoded = "\n".join(event.model_dump_json() for event in events)
    assert private_marker not in encoded
    assert str(created.record.result_id) in encoded
    assert created.record.result_sha256 in encoded
    assert created.record.payload_sha256 in encoded
    assert created.record.invocation_usage_sha256 in encoded
    assert created.record.invocation_result_sha256 in encoded
    assert "result_created" in encoded
    assert "result_replayed" in encoded
    assert "result_presentation_rendered" in encoded
