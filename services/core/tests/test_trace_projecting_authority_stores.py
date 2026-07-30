from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.context_contracts import SpecialistContextBundle
from simorgh_core.agents.context_store import ContextClaim, ContextClaimKind
from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import (
    InvocationEffect,
    InvocationKind,
    InvocationRecord,
    InvocationStart,
    InvocationStartKind,
)
from simorgh_core.agents.result_authority import AuthoritativeSpecialistResult
from simorgh_core.agents.result_store import ResultClaim, ResultClaimKind
from simorgh_core.agents.trace_projecting_authority_stores import (
    ContextTraceProjectionError,
    ResultTraceProjectionError,
    TraceProjectingContextStore,
    TraceProjectingResultStore,
)
from simorgh_core.agents.trace_projecting_invocation_store import (
    InvocationTraceProjectionError,
    TraceProjectingInvocationStore,
)
from simorgh_core.agents.trace_projection import request_trace_projector_registry
from simorgh_core.agents.trace_reconciliation import TraceReconciliationReport


class _RecordingProjector:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.requests: list[UUID] = []

    def project_request(self, request_id: UUID) -> TraceReconciliationReport:
        self.requests.append(request_id)
        if self.failure is not None:
            raise self.failure
        return TraceReconciliationReport(
            request_count=1,
            projected_event_count=1,
            replayed_event_count=0,
            gap_event_count=0,
        )


class _InvocationDelegate:
    def __init__(self, request_id: UUID) -> None:
        self.record = InvocationRecord.model_construct(
            invocation_id=uuid4(),
            request_id=request_id,
        )
        self.reserve_calls = 0
        self.complete_calls = 0

    def begin(self, **kwargs: Any) -> InvocationStart:
        self.record = self.record.model_copy(
            update={
                "invocation_id": kwargs["invocation_id"],
                "request_id": kwargs["request_id"],
            }
        )
        return InvocationStart.model_construct(
            kind=InvocationStartKind.NEW,
            record=self.record,
        )

    def reserve(self, **kwargs: Any) -> InvocationRecord:
        del kwargs
        self.reserve_calls += 1
        return self.record

    def complete(self, **kwargs: Any) -> InvocationRecord:
        del kwargs
        self.complete_calls += 1
        return self.record

    def fail(self, **kwargs: Any) -> InvocationRecord:
        del kwargs
        return self.record

    def mark_unknown(self, **kwargs: Any) -> InvocationRecord:
        del kwargs
        return self.record

    def cancel(self, invocation_id: UUID) -> InvocationRecord:
        del invocation_id
        return self.record

    def expire(self, invocation_id: UUID) -> InvocationRecord:
        del invocation_id
        return self.record

    def get(self, invocation_id: UUID) -> InvocationRecord:
        del invocation_id
        return self.record

    def load(self) -> list[InvocationRecord]:
        return [self.record]

    def list_owned(
        self,
        *,
        request_id: UUID,
        terminal: bool | None = None,
    ) -> tuple[InvocationRecord, ...]:
        del request_id, terminal
        return (self.record,)

    def accept_cancellation(self, request: object) -> object:
        return request

    def get_cancellation_fence(self, request_id: UUID) -> None:
        del request_id
        return None

    def settle_pending_cancellation(
        self,
        request_id: UUID,
    ) -> tuple[InvocationRecord, ...]:
        del request_id
        return ()

    def settle_reserved_cancellation(
        self,
        request_id: UUID,
        *,
        proven_not_entered: frozenset[UUID] = frozenset(),
    ) -> tuple[InvocationRecord, ...]:
        del request_id, proven_not_entered
        return ()

    def settle_cancellation(
        self,
        request_id: UUID,
    ) -> tuple[InvocationRecord, ...]:
        del request_id
        return ()

    def clear(self) -> None:
        return None

    def close(self) -> None:
        return None


class _ContextDelegate:
    def __init__(self, request_id: UUID) -> None:
        self.record = SpecialistContextBundle.model_construct(
            context_bundle_id=uuid4(),
            request_id=request_id,
            specialist_invocation_id=uuid4(),
        )
        self.claim_calls = 0

    def claim(self, record: SpecialistContextBundle) -> ContextClaim:
        del record
        self.claim_calls += 1
        return ContextClaim.model_construct(
            kind=ContextClaimKind.NEW,
            record=self.record,
        )

    def get(self, context_bundle_id: UUID) -> SpecialistContextBundle:
        del context_bundle_id
        return self.record

    def get_by_invocation(self, invocation_id: UUID) -> SpecialistContextBundle:
        del invocation_id
        return self.record

    def load(self) -> list[SpecialistContextBundle]:
        return [self.record]

    def close(self) -> None:
        return None


class _ResultDelegate:
    def __init__(self, request_id: UUID) -> None:
        self.record = AuthoritativeSpecialistResult.model_construct(
            result_id=uuid4(),
            request_id=request_id,
            invocation_id=uuid4(),
        )
        self.claim_calls = 0

    def claim(self, record: AuthoritativeSpecialistResult) -> ResultClaim:
        del record
        self.claim_calls += 1
        return ResultClaim.model_construct(
            kind=ResultClaimKind.NEW,
            record=self.record,
        )

    def get(self, result_id: UUID) -> AuthoritativeSpecialistResult:
        del result_id
        return self.record

    def get_by_invocation(self, invocation_id: UUID) -> AuthoritativeSpecialistResult:
        del invocation_id
        return self.record

    def load(self) -> list[AuthoritativeSpecialistResult]:
        return [self.record]

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_projector_registry() -> None:
    request_trace_projector_registry.reset_to_null()
    yield
    request_trace_projector_registry.reset_to_null()


def test_invocation_begin_and_terminal_project_but_reserve_does_not() -> None:
    request_id = uuid4()
    delegate = _InvocationDelegate(request_id)
    store = TraceProjectingInvocationStore(delegate)  # type: ignore[arg-type]
    projector = _RecordingProjector()
    request_trace_projector_registry.configure(projector)
    invocation_id = uuid4()

    started = store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="specialist.execute",
        input_fingerprint="a" * 64,
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.PROPOSAL,
    )
    store.reserve(
        invocation_id=invocation_id,
        usage=UsageVector(input_tokens=1),
    )
    store.complete(
        invocation_id=invocation_id,
        result_payload={"schema_version": "1.0"},
    )

    assert started.record.request_id == request_id
    assert projector.requests == [request_id, request_id]
    assert delegate.reserve_calls == 1
    assert delegate.complete_calls == 1


def test_invocation_projection_failure_keeps_underlying_begin() -> None:
    request_id = uuid4()
    delegate = _InvocationDelegate(request_id)
    store = TraceProjectingInvocationStore(delegate)  # type: ignore[arg-type]
    private_marker = "private-model-output"
    request_trace_projector_registry.configure(
        _RecordingProjector(failure=ValueError(private_marker))
    )
    invocation_id = uuid4()

    with pytest.raises(
        InvocationTraceProjectionError,
        match="invocation authority committed but trace projection failed",
    ) as error:
        store.begin(
            invocation_id=invocation_id,
            request_id=request_id,
            agent_id="development.planner",
            agent_version="1.0.0",
            operation="specialist.execute",
            input_fingerprint="a" * 64,
        )

    assert private_marker not in str(error.value)
    assert delegate.record.invocation_id == invocation_id


def test_context_claim_and_get_project_after_authority() -> None:
    request_id = uuid4()
    delegate = _ContextDelegate(request_id)
    store = TraceProjectingContextStore(delegate)  # type: ignore[arg-type]
    projector = _RecordingProjector()
    request_trace_projector_registry.configure(projector)

    store.claim(delegate.record)
    store.get(delegate.record.context_bundle_id)

    assert delegate.claim_calls == 1
    assert projector.requests == [request_id, request_id]


def test_context_projection_failure_preserves_claim() -> None:
    request_id = uuid4()
    delegate = _ContextDelegate(request_id)
    store = TraceProjectingContextStore(delegate)  # type: ignore[arg-type]
    private_marker = "private-context-body"
    request_trace_projector_registry.configure(
        _RecordingProjector(failure=ValueError(private_marker))
    )

    with pytest.raises(
        ContextTraceProjectionError,
        match="context authority committed but trace projection failed",
    ) as error:
        store.claim(delegate.record)

    assert private_marker not in str(error.value)
    assert delegate.claim_calls == 1


def test_result_claim_and_get_project_after_authority() -> None:
    request_id = uuid4()
    delegate = _ResultDelegate(request_id)
    store = TraceProjectingResultStore(delegate)  # type: ignore[arg-type]
    projector = _RecordingProjector()
    request_trace_projector_registry.configure(projector)

    store.claim(delegate.record)
    store.get(delegate.record.result_id)

    assert delegate.claim_calls == 1
    assert projector.requests == [request_id, request_id]


def test_result_projection_failure_preserves_claim() -> None:
    request_id = uuid4()
    delegate = _ResultDelegate(request_id)
    store = TraceProjectingResultStore(delegate)  # type: ignore[arg-type]
    private_marker = "private-result-payload"
    request_trace_projector_registry.configure(
        _RecordingProjector(failure=ValueError(private_marker))
    )

    with pytest.raises(
        ResultTraceProjectionError,
        match="result authority committed but trace projection failed",
    ) as error:
        store.claim(delegate.record)

    assert private_marker not in str(error.value)
    assert delegate.claim_calls == 1
