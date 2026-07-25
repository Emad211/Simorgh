from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.contracts import RoutingMethod, UsageVector
from simorgh_core.agents.tracing import (
    CacheDisposition,
    InMemoryTraceSink,
    TraceEvent,
    TraceEventKind,
    trace_event,
)


def test_trace_records_agent_cost_and_cache_without_task_content() -> None:
    request_id = uuid4()
    event = trace_event(
        request_id=request_id,
        kind=TraceEventKind.MODEL_COMPLETED,
        invocation_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        routing_method=RoutingMethod.DETERMINISTIC_RULE,
        provider_id="avalai",
        model_id="fast-model",
        cache=CacheDisposition.MISS,
        usage=UsageVector(
            model_calls=1,
            input_tokens=100,
            output_tokens=20,
            estimated_cost_microusd=500,
        ),
        outcome="completed",
        reason="typed output validated",
        metadata={"confidence_bps": 9000, "policy_version": "1.0.0"},
        wall_clock_millis=lambda: 1_234,
    )

    dumped = event.model_dump(mode="json")
    assert dumped["occurred_at_ms"] == 1_234
    assert dumped["usage"]["estimated_cost_microusd"] == 500
    assert "input_text" not in dumped
    assert "raw_input" not in dumped
    assert "authorization" not in dumped


def test_secret_or_private_content_metadata_keys_fail_validation() -> None:
    request_id = uuid4()
    for forbidden_key in (
        "authorization",
        "provider_api_key",
        "password_value",
        "input_text",
        "email_body",
        "accessibility_tree",
    ):
        with pytest.raises(ValueError, match="forbidden"):
            TraceEvent(
                request_id=request_id,
                occurred_at_ms=1,
                kind=TraceEventKind.TERMINAL,
                metadata={forbidden_key: "secret"},
            )


def test_in_memory_trace_sink_is_bounded_and_filtered_by_request() -> None:
    first_request = uuid4()
    second_request = uuid4()
    sink = InMemoryTraceSink(maximum_events=2)
    sink.emit(
        trace_event(
            request_id=first_request,
            kind=TraceEventKind.ROUTING_STARTED,
            wall_clock_millis=lambda: 1,
        )
    )
    sink.emit(
        trace_event(
            request_id=second_request,
            kind=TraceEventKind.ROUTING_COMPLETED,
            wall_clock_millis=lambda: 2,
        )
    )
    sink.emit(
        trace_event(
            request_id=first_request,
            kind=TraceEventKind.TERMINAL,
            wall_clock_millis=lambda: 3,
        )
    )

    assert [event.occurred_at_ms for event in sink.for_request(first_request)] == [3]
    assert [event.occurred_at_ms for event in sink.for_request(second_request)] == [2]
