from __future__ import annotations

from uuid import UUID

from simorgh_core.agents.cancellation_contracts import (
    CancellationRequesterAuthority,
)
from simorgh_core.agents.contracts import TaskEnvelope
from simorgh_core.agents.control_plane import (
    AgentTaskControlPlane,
    AgentTaskControlPlaneError,
    AgentTaskRoutingUnknownError,
)
from simorgh_core.agents.task_state import AgentTaskRecord
from simorgh_core.agents.trace_projection import (
    request_trace_projector_registry,
)


class AgentTaskTraceUnavailableError(AgentTaskControlPlaneError):
    """Durable task state committed, but its audit projection is unavailable."""


class TraceProjectingAgentTaskControlPlane(AgentTaskControlPlane):
    """Project one request after durable task/cancellation control-plane commits."""

    async def submit(self, task: TaskEnvelope) -> AgentTaskRecord:
        try:
            record = await super().submit(task)
        except AgentTaskRoutingUnknownError as exc:
            try:
                self._project_request(task.request_id)
            except AgentTaskTraceUnavailableError as trace_exc:
                raise trace_exc from exc
            raise
        self._project_request(record.request_id)
        return record

    async def get(self, request_id: UUID) -> AgentTaskRecord:
        record = await super().get(request_id)
        self._project_request(record.request_id)
        return record

    async def cancel(
        self,
        *,
        request_id: UUID,
        reason: str,
        cancellation_id: UUID | None = None,
        reason_code: str = "operator_requested",
        requester_authority: CancellationRequesterAuthority = (
            CancellationRequesterAuthority.OPERATOR
        ),
    ) -> AgentTaskRecord:
        record = await super().cancel(
            request_id=request_id,
            reason=reason,
            cancellation_id=cancellation_id,
            reason_code=reason_code,
            requester_authority=requester_authority,
        )
        self._project_request(record.request_id)
        return record

    @staticmethod
    def _project_request(request_id: UUID) -> None:
        try:
            request_trace_projector_registry.current().project_request(request_id)
        except Exception as exc:
            raise AgentTaskTraceUnavailableError(
                "durable task state committed but trace projection is unavailable"
            ) from exc


__all__ = [
    "AgentTaskTraceUnavailableError",
    "TraceProjectingAgentTaskControlPlane",
]
