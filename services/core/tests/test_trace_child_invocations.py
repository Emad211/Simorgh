from __future__ import annotations

from uuid import UUID, uuid4

from simorgh_core.agents.contracts import (
    InvocationState,
    RoutingMethod,
    RoutingState,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
)
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_child_invocations import (
    project_classifier_invocation,
    project_specialist_owned_child_invocations,
)
from simorgh_core.agents.trace_contracts import (
    DurableTraceEventKind,
    TraceContextDetails,
    TraceEventRecord,
    TraceInvocationDetails,
    TraceRoutingDetails,
    TraceSourceAuthorityKind,
    TraceStage,
    TraceTaskDetails,
    new_trace_event_candidate,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64


def _task_entry(
    request_id: UUID,
    *,
    classifier_invocation_id: UUID | None = None,
) -> AgentTaskStoreEntryV1:
    decision = type(
        "Decision",
        (),
        {"classifier_invocation_id": classifier_invocation_id},
    )()
    return AgentTaskStoreEntryV1.model_construct(
        request_id=request_id,
        record=AgentTaskRecord.model_construct(
            request_id=request_id,
            phase=AgentTaskPhase.ROUTED,
            routing_decision=decision,
        ),
    )


def _task_claim(
    store: InMemoryTraceStore,
    request_id: UUID,
) -> TraceEventRecord:
    return store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.TASK_CLAIMED,
            stage=TraceStage.TASK,
            source_authority_kind=TraceSourceAuthorityKind.TASK_RECORD,
            source_authority_id=request_id,
            source_authority_sha256=_SHA_A,
            details=TraceTaskDetails(
                task_fingerprint=_SHA_A,
                phase=AgentTaskPhase.ROUTING,
            ),
            occurred_at_ms=1_000,
        ),
        ingested_at_ms=2_000,
    ).record


def _specialist_start(
    store: InMemoryTraceStore,
    *,
    request_id: UUID,
    invocation_id: UUID,
    input_fingerprint: str,
) -> TraceEventRecord:
    task_event = _task_claim(store, request_id)
    decision_id = uuid4()
    routing = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.ROUTING_DECIDED,
            stage=TraceStage.ROUTING,
            source_authority_kind=TraceSourceAuthorityKind.ROUTING_DECISION,
            source_authority_id=decision_id,
            source_authority_sha256=_SHA_B,
            parent_event_id=task_event.event_id,
            causation_event_id=task_event.event_id,
            details=TraceRoutingDetails(
                routing_fingerprint=_SHA_B,
                state=RoutingState.ROUTED,
                method=RoutingMethod.EXPLICIT_TASK_KIND,
                selected_agent_id="development.planner",
                selected_agent_version="1.0.0",
            ),
            occurred_at_ms=1_100,
        ),
        ingested_at_ms=2_100,
    ).record
    context_id = uuid4()
    context = store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.CONTEXT_COMPILED,
            stage=TraceStage.CONTEXT,
            source_authority_kind=TraceSourceAuthorityKind.CONTEXT_BUNDLE,
            source_authority_id=context_id,
            source_authority_sha256=_SHA_C,
            parent_event_id=routing.event_id,
            causation_event_id=routing.event_id,
            invocation_id=invocation_id,
            context_bundle_id=context_id,
            details=TraceContextDetails(
                context_bundle_id=context_id,
                context_sha256=_SHA_C,
                source_manifest_sha256=_SHA_D,
                section_count=1,
                omission_count=0,
            ),
            occurred_at_ms=1_200,
        ),
        ingested_at_ms=2_200,
    ).record
    return store.append(
        new_trace_event_candidate(
            request_id=request_id,
            event_kind=DurableTraceEventKind.INVOCATION_STARTED,
            stage=TraceStage.SPECIALIST,
            source_authority_kind=TraceSourceAuthorityKind.INVOCATION_RECORD,
            source_authority_id=invocation_id,
            source_authority_sha256=_SHA_D,
            parent_event_id=context.event_id,
            causation_event_id=context.event_id,
            invocation_id=invocation_id,
            details=TraceInvocationDetails(
                invocation_kind=InvocationKind.SPECIALIST,
                effect=InvocationEffect.READ_ONLY,
                state=InvocationState.PENDING,
                operation_id="specialist.execute",
                input_fingerprint=input_fingerprint,
            ),
            occurred_at_ms=1_300,
        ),
        ingested_at_ms=2_300,
    ).record


def test_classifier_model_is_linked_to_task_claim_and_usage_is_terminal() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    trace_store = InMemoryTraceStore()
    task_event = _task_claim(trace_store, request_id)
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 1_500)
    invocation_store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="system.specialist-router",
        agent_version="1.0.0",
        operation="classify-primary-specialist",
        input_fingerprint=_SHA_A,
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="provider",
        model_id="model",
    )
    usage = UsageVector(model_calls=1, input_tokens=10, output_tokens=5)
    invocation_store.reserve(invocation_id=invocation_id, usage=usage)
    private_marker = "private-model-output-must-not-enter-trace"
    invocation_store.complete(
        invocation_id=invocation_id,
        result_payload={"text": private_marker},
        committed_usage=usage,
    )

    report = project_classifier_invocation(
        store=trace_store,
        task_entry=_task_entry(
            request_id,
            classifier_invocation_id=invocation_id,
        ),
        invocation_records=tuple(invocation_store.load()),
        task_claim_event=task_event,
        base_ingested_at_ms=3_000,
    )
    view = trace_store.view(request_id)
    model_events = tuple(
        event for event in view.events if event.invocation_id == invocation_id
    )

    assert report.projected_event_count == 2
    assert model_events[0].parent_event_id == task_event.event_id
    assert model_events[0].stage == TraceStage.MODEL
    assert model_events[1].usage == usage
    assert private_marker not in str(view.model_dump(mode="json"))


def test_specialist_owned_tool_is_linked_by_unique_cancellation_owner() -> None:
    request_id = uuid4()
    specialist_id = uuid4()
    tool_id = uuid4()
    owner_id = uuid4()
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 1_500)
    specialist = invocation_store.begin(
        invocation_id=specialist_id,
        request_id=request_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="specialist.execute",
        input_fingerprint=_SHA_A,
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.READ_ONLY,
        cancellation_owner_id=owner_id,
    ).record
    tool = invocation_store.begin(
        invocation_id=tool_id,
        request_id=request_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="tool:github-read",
        input_fingerprint=_SHA_B,
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github-read",
        connector_id="github",
        cancellation_owner_id=owner_id,
    ).record
    trace_store = InMemoryTraceStore()
    specialist_event = _specialist_start(
        trace_store,
        request_id=request_id,
        invocation_id=specialist_id,
        input_fingerprint=specialist.input_fingerprint,
    )

    report = project_specialist_owned_child_invocations(
        store=trace_store,
        specialist_invocation=specialist,
        specialist_start_event=specialist_event,
        invocation_records=(specialist, tool),
        base_ingested_at_ms=3_000,
    )
    tool_event = next(
        event for event in trace_store.view(request_id).events if event.invocation_id == tool_id
    )

    assert report.projected_event_count == 1
    assert tool_event.parent_event_id == specialist_event.event_id
    assert tool_event.parent_invocation_id == specialist_id
    assert tool_event.stage == TraceStage.TOOL


def test_ambiguous_specialist_owner_does_not_guess_child_parent() -> None:
    request_id = uuid4()
    owner_id = uuid4()
    invocation_store = InMemoryInvocationStore(wall_clock_millis=lambda: 1_500)
    specialists = tuple(
        invocation_store.begin(
            invocation_id=uuid4(),
            request_id=request_id,
            agent_id=f"development.planner{index}",
            agent_version="1.0.0",
            operation="specialist.execute",
            input_fingerprint=_SHA_A,
            kind=InvocationKind.SPECIALIST,
            effect=InvocationEffect.READ_ONLY,
            cancellation_owner_id=owner_id,
        ).record
        for index in range(2)
    )
    child = invocation_store.begin(
        invocation_id=uuid4(),
        request_id=request_id,
        agent_id="development.planner0",
        agent_version="1.0.0",
        operation="tool:github-read",
        input_fingerprint=_SHA_B,
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github-read",
        connector_id="github",
        cancellation_owner_id=owner_id,
    ).record
    trace_store = InMemoryTraceStore()
    specialist_event = _specialist_start(
        trace_store,
        request_id=request_id,
        invocation_id=specialists[0].invocation_id,
        input_fingerprint=specialists[0].input_fingerprint,
    )

    report = project_specialist_owned_child_invocations(
        store=trace_store,
        specialist_invocation=specialists[0],
        specialist_start_event=specialist_event,
        invocation_records=(*specialists, child),
        base_ingested_at_ms=3_000,
    )

    assert report.projected_event_count == 0
    assert all(
        event.invocation_id != child.invocation_id
        for event in trace_store.view(request_id).events
    )
