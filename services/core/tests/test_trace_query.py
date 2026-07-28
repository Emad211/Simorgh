from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.result_authority import (
    PrivacyClassification,
    RetentionDisposition,
)
from simorgh_core.agents.trace_authority import (
    TraceEventCandidate,
    TracePhase,
    TraceSafeMetadata,
    materialize_trace_event,
)
from simorgh_core.agents.trace_query import (
    TraceQueryError,
    TraceQueryService,
    derive_trace_summary,
)
from simorgh_core.agents.trace_store import InMemoryTraceStore
from simorgh_core.agents.tracing import TraceEventKind


def _candidates():
    request_id = uuid4()
    invocation_id = uuid4()
    context_id = uuid4()
    result_id = uuid4()
    cancellation_id = uuid4()
    return (
        TraceEventCandidate(
            request_id=request_id,
            occurred_at_ms=1_000,
            kind=TraceEventKind.ROUTING_COMPLETED,
            phase=TracePhase.ROUTING,
            operation_id=uuid4(),
            agent_id="github.read",
            agent_version="1.0.0",
            outcome="routed",
        ),
        TraceEventCandidate(
            request_id=request_id,
            occurred_at_ms=2_000,
            kind=TraceEventKind.CONTEXT_COMPILED,
            phase=TracePhase.CONTEXT,
            invocation_id=invocation_id,
            context_bundle_id=context_id,
            agent_id="github.read",
            agent_version="1.0.0",
            outcome="completed",
            privacy=PrivacyClassification.INTERNAL,
            retention=RetentionDisposition.PROJECT,
            tainted=True,
            metadata=TraceSafeMetadata(
                context_sha256="a" * 64,
                section_count=3,
                evidence_count=1,
            ),
        ),
        TraceEventCandidate(
            request_id=request_id,
            occurred_at_ms=3_000,
            kind=TraceEventKind.TOOL_COMPLETED,
            phase=TracePhase.TOOL,
            invocation_id=invocation_id,
            tool_id="github.fetch-file",
            connector_id="github",
            usage_delta=UsageVector(tool_calls=1),
            outcome="completed",
            privacy=PrivacyClassification.SENSITIVE,
            retention=RetentionDisposition.LEGAL_HOLD,
            tainted=True,
        ),
        TraceEventCandidate(
            request_id=request_id,
            occurred_at_ms=4_000,
            kind=TraceEventKind.RESULT_COMMITTED,
            phase=TracePhase.RESULT,
            invocation_id=invocation_id,
            result_id=result_id,
            agent_id="github.read",
            agent_version="1.0.0",
            outcome="completed",
            privacy=PrivacyClassification.SENSITIVE,
            retention=RetentionDisposition.LEGAL_HOLD,
            metadata=TraceSafeMetadata(result_sha256="b" * 64),
        ),
        TraceEventCandidate(
            request_id=request_id,
            occurred_at_ms=5_000,
            kind=TraceEventKind.CANCELLATION_REPLAYED,
            phase=TracePhase.CANCELLATION,
            operation_id=uuid4(),
            cancellation_id=cancellation_id,
            outcome="cancelled",
            metadata=TraceSafeMetadata(replayed=True),
        ),
        TraceEventCandidate(
            request_id=request_id,
            occurred_at_ms=6_000,
            kind=TraceEventKind.TERMINAL,
            phase=TracePhase.TERMINAL,
            outcome="completed",
        ),
    )


def test_summary_is_deterministic_metadata_only_and_strictest() -> None:
    store = InMemoryTraceStore()
    candidates = _candidates()
    for candidate in candidates:
        store.append(candidate)
    query = TraceQueryService(store)

    first = query.summary_for_request(candidates[0].request_id)
    second = query.summary_for_request(candidates[0].request_id)

    assert first == second
    assert first.event_count == len(candidates)
    assert first.first_sequence == 1
    assert first.last_sequence == len(candidates)
    assert first.route_covered
    assert first.context_covered
    assert first.tool_covered
    assert first.result_covered
    assert first.cancellation_covered
    assert first.replay_covered
    assert first.terminal_covered
    assert not first.model_covered
    assert first.committed_usage == UsageVector(tool_calls=1)
    assert first.privacy == PrivacyClassification.SENSITIVE
    assert first.retention == RetentionDisposition.LEGAL_HOLD
    assert first.tainted
    assert len(first.canonical_sha256) == 64
    assert "Simorgh" not in str(first.model_dump(mode="json"))


def test_queries_find_exact_correlation_metadata() -> None:
    store = InMemoryTraceStore()
    candidates = _candidates()
    records = tuple(store.append(candidate).record for candidate in candidates)
    query = TraceQueryService(store)

    assert query.events_for_invocation(records[1].invocation_id) == records[1:4]
    assert query.events_for_context(records[1].context_bundle_id) == (records[1],)
    assert query.events_for_result(records[3].result_id) == (records[3],)
    assert query.events_for_cancellation(records[4].cancellation_id) == (records[4],)
    assert query.events_for_trace(records[0].trace_id) == records


def test_summary_rejects_sequence_gap_and_cross_request_mix() -> None:
    candidates = _candidates()
    first = materialize_trace_event(candidates[0], causal_sequence=1)
    gap = materialize_trace_event(candidates[1], causal_sequence=3)

    with pytest.raises(TraceQueryError, match="not contiguous"):
        derive_trace_summary((first, gap))

    other = materialize_trace_event(
        TraceEventCandidate(
            request_id=uuid4(),
            occurred_at_ms=2_000,
            kind=TraceEventKind.ROUTING_COMPLETED,
            phase=TracePhase.ROUTING,
            operation_id=uuid4(),
            agent_id="github.read",
            agent_version="1.0.0",
            outcome="routed",
        ),
        causal_sequence=2,
    )
    with pytest.raises(TraceQueryError, match="cross-request"):
        derive_trace_summary((first, other))


def test_missing_trace_has_typed_query_error() -> None:
    with pytest.raises(TraceQueryError, match="no correlated trace"):
        TraceQueryService(InMemoryTraceStore()).summary_for_request(uuid4())
