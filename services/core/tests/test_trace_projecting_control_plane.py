from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.contracts import (
    ExecutionMode,
    TaskEnvelope,
    TaskKind,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.trace_projecting_control_plane import (
    AgentTaskTraceUnavailableError,
    TraceProjectingAgentTaskControlPlane,
)
from simorgh_core.agents.trace_projection import (
    request_trace_projector_registry,
)
from simorgh_core.agents.trace_reconciliation import TraceReconciliationReport
from simorgh_core.agents.tracing import InMemoryTraceSink, TraceEventKind


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


@pytest.fixture(autouse=True)
def _reset_projector_registry() -> None:
    request_trace_projector_registry.reset_to_null()
    yield
    request_trace_projector_registry.reset_to_null()


def _task() -> TaskEnvelope:
    return TaskEnvelope(
        request_id=uuid4(),
        received_at_ms=1_000,
        deadline_at_ms=20_000,
        locale="fa-IR",
        input_text="برای توسعه پروژه برنامه دقیق بساز",
        requested_outcome="یک برنامه تایپ‌شده توسعه",
        explicit_task_kind=TaskKind.DEVELOPMENT_PLANNING,
        execution_mode=ExecutionMode.PLAN,
    )


def _control_plane(
    *,
    trace_sink: InMemoryTraceSink | None = None,
) -> TraceProjectingAgentTaskControlPlane:
    sink = trace_sink or InMemoryTraceSink()
    return TraceProjectingAgentTaskControlPlane(
        router=SpecialistRouter(
            registry=default_specialist_registry(),
            trace_sink=sink,
        ),
        trace_sink=sink,
        wall_clock_millis=lambda: 2_000,
        monotonic_millis=lambda: 0,
    )


@pytest.mark.asyncio
async def test_projection_failure_preserves_route_and_replay_does_not_reroute() -> None:
    task = _task()
    sink = InMemoryTraceSink()
    plane = _control_plane(trace_sink=sink)
    private_marker = "private-connector-body"
    failing = _RecordingProjector(failure=ValueError(private_marker))
    request_trace_projector_registry.configure(failing)

    with pytest.raises(
        AgentTaskTraceUnavailableError,
        match="trace projection is unavailable",
    ) as error:
        await plane.submit(task)

    assert private_marker not in str(error.value)
    assert failing.requests == [task.request_id]
    routing_started = sum(
        event.kind == TraceEventKind.ROUTING_STARTED
        for event in sink.for_request(task.request_id)
    )
    assert routing_started == 1

    recovered = _RecordingProjector()
    request_trace_projector_registry.configure(recovered)
    record = await plane.submit(task)

    assert record.phase == AgentTaskPhase.ROUTED
    assert recovered.requests == [task.request_id]
    assert sum(
        event.kind == TraceEventKind.ROUTING_STARTED
        for event in sink.for_request(task.request_id)
    ) == 1


@pytest.mark.asyncio
async def test_cancel_projects_only_after_durable_settlement() -> None:
    task = _task()
    plane = _control_plane()
    projector = _RecordingProjector()
    request_trace_projector_registry.configure(projector)
    await plane.submit(task)
    projector.requests.clear()

    cancelled = await plane.cancel(
        request_id=task.request_id,
        reason="operator requested cancellation",
    )

    assert cancelled.phase == AgentTaskPhase.CANCELLED
    assert cancelled.cancellation_result is not None
    assert projector.requests == [task.request_id]


@pytest.mark.asyncio
async def test_status_read_retries_idempotent_projection() -> None:
    task = _task()
    plane = _control_plane()
    projector = _RecordingProjector()
    request_trace_projector_registry.configure(projector)
    await plane.submit(task)
    projector.requests.clear()

    record = await plane.get(task.request_id)

    assert record.phase == AgentTaskPhase.ROUTED
    assert projector.requests == [task.request_id]
