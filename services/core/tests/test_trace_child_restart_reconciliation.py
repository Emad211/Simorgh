from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.contracts import (
    InvocationState,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    InvocationRecord,
)
from simorgh_core.agents.result_authority import (
    AuthoritativeSpecialistResult,
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.sqlite_trace_store import SQLiteTraceStore
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_contracts import DurableTraceEventKind, TraceStage
from simorgh_core.agents.trace_reconciliation import (
    reconcile_retained_trace_authority,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64
_SHA_E = "e" * 64
_SHA_F = "f" * 64


def _task_entry(
    request_id: UUID,
    classifier_invocation_id: UUID,
) -> AgentTaskStoreEntryV1:
    decision = RoutingDecision.model_construct(
        decision_id=uuid4(),
        request_id=request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="development.planner",
        selected_agent_version="1.0.0",
        method=RoutingMethod.MODEL_CLASSIFIER,
        confidence_bps=9_000,
        candidate_agent_ids=("development.planner",),
        matched_rule_ids=(),
        classifier_invocation_id=classifier_invocation_id,
        model_calls=1,
        reason="fixture",
    )
    return AgentTaskStoreEntryV1.model_construct(
        request_id=request_id,
        task_fingerprint=_SHA_A,
        record=AgentTaskRecord.model_construct(
            request_id=request_id,
            phase=AgentTaskPhase.ROUTED,
            created_at_ms=1_000,
            updated_at_ms=1_200,
            routing_decision=decision,
        ),
    )


def _invocation(
    *,
    request_id: UUID,
    invocation_id: UUID,
    kind: InvocationKind,
    agent_id: str,
    operation: str,
    input_fingerprint: str,
    created_at_ms: int,
    updated_at_ms: int,
    committed_usage: UsageVector,
    cancellation_owner_id: UUID | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    tool_id: str | None = None,
    connector_id: str | None = None,
    private_payload: str,
) -> InvocationRecord:
    return InvocationRecord.model_construct(
        schema_version=2,
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id=agent_id,
        agent_version="1.0.0",
        operation=operation,
        input_fingerprint=input_fingerprint,
        kind=kind,
        effect=InvocationEffect.READ_ONLY,
        provider_id=provider_id,
        model_id=model_id,
        tool_id=tool_id,
        connector_id=connector_id,
        parent_invocation_id=None,
        cancellation_owner_id=cancellation_owner_id,
        state=InvocationState.COMPLETED,
        attempt=1,
        created_at_ms=created_at_ms,
        updated_at_ms=updated_at_ms,
        reserved_usage=UsageVector(),
        committed_usage=committed_usage,
        result_payload={"private": private_payload},
        result_payload_sha256=_SHA_E,
        failure_code=None,
        failure_detail=None,
    )


def test_restart_reconstructs_classifier_and_owned_tool_before_terminals(
    tmp_path: Path,
) -> None:
    request_id = uuid4()
    classifier_id = uuid4()
    specialist_id = uuid4()
    tool_invocation_id = uuid4()
    owner_id = uuid4()
    private_model = "private-classifier-output"
    private_tool = "private-github-tool-payload"

    classifier = _invocation(
        request_id=request_id,
        invocation_id=classifier_id,
        kind=InvocationKind.MODEL,
        agent_id="system.specialist-router",
        operation="classify-primary-specialist",
        input_fingerprint=_SHA_B,
        created_at_ms=1_050,
        updated_at_ms=1_150,
        committed_usage=UsageVector(
            model_calls=1,
            input_tokens=9,
            output_tokens=4,
        ),
        provider_id="provider",
        model_id="classifier-model",
        private_payload=private_model,
    )
    specialist = _invocation(
        request_id=request_id,
        invocation_id=specialist_id,
        kind=InvocationKind.SPECIALIST,
        agent_id="development.planner",
        operation="specialist-execute",
        input_fingerprint=_SHA_C,
        created_at_ms=1_400,
        updated_at_ms=1_800,
        committed_usage=UsageVector(),
        cancellation_owner_id=owner_id,
        private_payload="private-specialist-result",
    )
    tool = _invocation(
        request_id=request_id,
        invocation_id=tool_invocation_id,
        kind=InvocationKind.TOOL,
        agent_id="development.planner",
        operation="tool-github-read",
        input_fingerprint=_SHA_D,
        created_at_ms=1_500,
        updated_at_ms=1_600,
        committed_usage=UsageVector(tool_calls=1),
        cancellation_owner_id=owner_id,
        tool_id="github-read",
        connector_id="github",
        private_payload=private_tool,
    )
    context = SpecialistContextBundle.model_construct(
        request_id=request_id,
        specialist_invocation_id=specialist_id,
        context_bundle_id=uuid4(),
        canonical_sha256=_SHA_C,
        source_manifest_sha256=_SHA_D,
        section_count=2,
        omission_count=0,
        compiled_at_ms=1_300,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
    )
    result = AuthoritativeSpecialistResult.model_construct(
        result_id=uuid4(),
        canonical_sha256=_SHA_F,
        request_id=request_id,
        invocation_id=specialist_id,
        result_schema_id="simorgh.specialist-plan-result",
        result_schema_version="1.0",
        completed_at_ms=1_900,
        privacy=PrivacyClassification.INTERNAL,
        retention=RetentionDisposition.PROJECT,
    )
    inputs = dict(
        task_entries=(_task_entry(request_id, classifier_id),),
        invocation_records=(classifier, specialist, tool),
        context_bundles=(context,),
        result_records=(result,),
    )
    path = tmp_path / "traces.sqlite3"
    store = SQLiteTraceStore(path)

    first = reconcile_retained_trace_authority(
        store=store,
        **inputs,
        base_ingested_at_ms=10_000,
    )
    first_view = store.view(request_id)
    store.close()

    reopened = SQLiteTraceStore(path)
    second = reconcile_retained_trace_authority(
        store=reopened,
        **inputs,
        base_ingested_at_ms=90_000,
    )
    second_view = reopened.view(request_id)

    assert first.projected_event_count == 11
    assert second.projected_event_count == 0
    assert second.replayed_event_count == 11
    assert first_view == second_view
    assert [event.event_kind for event in second_view.events] == [
        DurableTraceEventKind.TASK_CLAIMED,
        DurableTraceEventKind.INVOCATION_STARTED,
        DurableTraceEventKind.INVOCATION_TERMINAL,
        DurableTraceEventKind.ROUTING_DECIDED,
        DurableTraceEventKind.CONTEXT_COMPILED,
        DurableTraceEventKind.INVOCATION_STARTED,
        DurableTraceEventKind.INVOCATION_STARTED,
        DurableTraceEventKind.INVOCATION_TERMINAL,
        DurableTraceEventKind.INVOCATION_TERMINAL,
        DurableTraceEventKind.RESULT_COMMITTED,
        DurableTraceEventKind.TRACE_TERMINAL,
    ]
    assert [event.stage for event in second_view.events] == [
        TraceStage.TASK,
        TraceStage.MODEL,
        TraceStage.MODEL,
        TraceStage.ROUTING,
        TraceStage.CONTEXT,
        TraceStage.SPECIALIST,
        TraceStage.TOOL,
        TraceStage.TOOL,
        TraceStage.SPECIALIST,
        TraceStage.RESULT,
        TraceStage.TERMINAL,
    ]
    serialized = str(second_view.model_dump(mode="json"))
    assert private_model not in serialized
    assert private_tool not in serialized
    reopened.close()
