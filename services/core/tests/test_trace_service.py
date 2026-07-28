from __future__ import annotations

from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from simorgh_core.agents.budget import BudgetSnapshot
from simorgh_core.agents.context_store import InMemoryContextStore
from simorgh_core.agents.contracts import (
    ExecutionMode,
    FreshnessClass,
    RiskClass,
    RoutingDecision,
    RoutingMethod,
    RoutingState,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
    UsageVector,
)
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
    canonical_fingerprint,
)
from simorgh_core.agents.result_store import InMemoryResultStore
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import InMemoryAgentTaskStore, new_task_store_entry
from simorgh_core.agents.trace_authority import TraceEventCandidate, TracePhase
from simorgh_core.agents.trace_service import (
    DurableTraceSink,
    NativeTraceCorrelationValidator,
    TraceCorrelationError,
    TraceEventProjector,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore
from simorgh_core.agents.tracing import CacheDisposition, TraceEventKind, trace_event

_NOW_MS = 4_000
_PRIVATE_MARKER = "PRIVATE_TRACE_MARKER_8b9d2f"


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        received_at_ms=1_000,
        deadline_at_ms=50_000,
        locale="fa-IR",
        input_text=f"ریپازیتوری را بررسی کن {_PRIVATE_MARKER}",
        requested_outcome="گزارش ساختاریافته",
        explicit_task_kind=TaskKind.REPOSITORY_RESEARCH,
        risk_class=RiskClass.READ_ONLY,
        freshness=FreshnessClass.CURRENT,
        execution_mode=ExecutionMode.READ_ONLY,
        allowed_data_sources=frozenset({"github"}),
        budget=TaskBudget(
            max_model_calls=1,
            max_tool_calls=2,
            max_input_tokens=12_000,
            max_output_tokens=4_000,
            max_estimated_cost_microusd=40_000,
            max_elapsed_ms=30_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
    )


def _decision(task: TaskEnvelope) -> RoutingDecision:
    return RoutingDecision(
        decision_id=uuid5(NAMESPACE_URL, f"trace-route:{task.request_id}"),
        request_id=task.request_id,
        state=RoutingState.ROUTED,
        selected_agent_id="github.read",
        selected_agent_version="1.0.0",
        method=RoutingMethod.EXPLICIT_TASK_KIND,
        confidence_bps=10_000,
        candidate_agent_ids=("github.read",),
        matched_rule_ids=("github.explicit-terms",),
        reason=f"private routing prose {_PRIVATE_MARKER}",
    )


def _task_store(task: TaskEnvelope) -> InMemoryAgentTaskStore:
    store = InMemoryAgentTaskStore()
    store.upsert(
        new_task_store_entry(
            AgentTaskRecord(
                request_id=task.request_id,
                phase=AgentTaskPhase.ROUTED,
                created_at_ms=task.received_at_ms,
                updated_at_ms=1_500,
                task=task,
                routing_decision=_decision(task),
                budget=BudgetSnapshot(
                    request_id=task.request_id,
                    limits=task.budget,
                    committed=UsageVector(),
                    reserved=UsageVector(),
                    elapsed_ms=500,
                    cancelled=False,
                ),
                detail=f"private durable detail {_PRIVATE_MARKER}",
            )
        )
    )
    return store


def _completed_tool_invocation(
    task: TaskEnvelope,
) -> tuple[InMemoryInvocationStore, object]:
    invocation_id = uuid4()
    store = InMemoryInvocationStore(wall_clock_millis=lambda: _NOW_MS)
    store.begin(
        invocation_id=invocation_id,
        request_id=task.request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.fetch-file",
        input_fingerprint=canonical_fingerprint(
            {"repository": "Emad211/Simorgh", "path": "README.md"}
        ),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.fetch-file",
        connector_id="github",
    )
    usage = UsageVector(tool_calls=1)
    store.reserve(invocation_id=invocation_id, usage=usage)
    record = store.complete(
        invocation_id=invocation_id,
        result_payload={"projection_sha256": "a" * 64},
        committed_usage=usage,
    )
    return store, record


def _validator(
    *,
    task_store: InMemoryAgentTaskStore,
    invocation_store: InMemoryInvocationStore,
) -> NativeTraceCorrelationValidator:
    return NativeTraceCorrelationValidator(
        task_store=task_store,
        invocation_store=invocation_store,
        context_store=InMemoryContextStore(),
        result_store=InMemoryResultStore(),
    )


def test_projector_discards_reason_and_unknown_private_metadata() -> None:
    task = _task()
    invocation_store, invocation = _completed_tool_invocation(task)
    event = trace_event(
        request_id=task.request_id,
        invocation_id=invocation.invocation_id,
        kind=TraceEventKind.TOOL_COMPLETED,
        agent_id="github.read",
        agent_version="1.0.0",
        tool_id="github.fetch-file",
        cache=CacheDisposition.MISS,
        usage=UsageVector(tool_calls=1),
        outcome="completed",
        reason=f"adapter returned {_PRIVATE_MARKER}",
        metadata={
            "connector_id": "github",
            "effect": "read_only",
            "projection_sha256": "a" * 64,
            "private_body": _PRIVATE_MARKER,
        },
        wall_clock_millis=lambda: _NOW_MS,
    )

    candidate = TraceEventProjector().project(event)
    dumped = str(candidate.model_dump(mode="json"))

    assert _PRIVATE_MARKER not in dumped
    assert candidate.reason_code == "completed"
    assert candidate.metadata.projection_sha256 == "a" * 64
    assert candidate.connector_id == "github"
    invocation_store.close()


def test_durable_sink_appends_only_after_native_tool_completion() -> None:
    task = _task()
    task_store = _task_store(task)
    invocation_store, invocation = _completed_tool_invocation(task)
    trace_store = InMemoryTraceStore()
    sink = DurableTraceSink(
        store=trace_store,
        validator=_validator(
            task_store=task_store,
            invocation_store=invocation_store,
        ),
    )
    event = trace_event(
        request_id=task.request_id,
        invocation_id=invocation.invocation_id,
        kind=TraceEventKind.TOOL_COMPLETED,
        agent_id="github.read",
        agent_version="1.0.0",
        tool_id="github.fetch-file",
        cache=CacheDisposition.MISS,
        usage=UsageVector(tool_calls=1),
        outcome="completed",
        metadata={
            "connector_id": "github",
            "effect": "read_only",
            "projection_sha256": "a" * 64,
        },
        wall_clock_millis=lambda: _NOW_MS,
    )

    sink.emit(event)

    records = trace_store.for_request(task.request_id)
    assert len(records) == 1
    assert records[0].invocation_id == invocation.invocation_id
    assert records[0].tool_id == "github.fetch-file"
    assert records[0].usage_delta == invocation.committed_usage


def test_wrong_tool_identity_fails_before_trace_append() -> None:
    task = _task()
    task_store = _task_store(task)
    invocation_store, invocation = _completed_tool_invocation(task)
    trace_store = InMemoryTraceStore()
    sink = DurableTraceSink(
        store=trace_store,
        validator=_validator(
            task_store=task_store,
            invocation_store=invocation_store,
        ),
    )
    event = trace_event(
        request_id=task.request_id,
        invocation_id=invocation.invocation_id,
        kind=TraceEventKind.TOOL_COMPLETED,
        agent_id="github.read",
        agent_version="1.0.0",
        tool_id="github.fetch-issue",
        usage=UsageVector(tool_calls=1),
        outcome="completed",
        metadata={"connector_id": "github", "effect": "read_only"},
        wall_clock_millis=lambda: _NOW_MS,
    )

    with pytest.raises(TraceCorrelationError, match="tool identity"):
        sink.emit(event)

    assert trace_store.load() == []


def test_routing_candidate_must_match_durable_decision() -> None:
    task = _task()
    task_store = _task_store(task)
    validator = _validator(
        task_store=task_store,
        invocation_store=InMemoryInvocationStore(),
    )
    decision = _decision(task)
    valid = TraceEventCandidate(
        request_id=task.request_id,
        occurred_at_ms=1_500,
        kind=TraceEventKind.ROUTING_COMPLETED,
        phase=TracePhase.ROUTING,
        operation_id=decision.decision_id,
        agent_id=decision.selected_agent_id,
        agent_version=decision.selected_agent_version,
        routing_method=decision.method,
        rule_id=decision.matched_rule_ids[0],
        outcome="routed",
    )

    validator.validate(valid)

    with pytest.raises(TraceCorrelationError, match="decision identity"):
        validator.validate(valid.model_copy(update={"operation_id": uuid4()}))
