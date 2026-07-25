from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.contracts import TaskEnvelope
from simorgh_core.agents.control_plane import (
    AgentTaskConflictError,
    AgentTaskControlPlane,
    AgentTaskNotFoundError,
    AgentTaskRecord,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.tracing import InMemoryTraceSink
from simorgh_core.devices.action_api import OperatorDependency

router = APIRouter(prefix="/v1/agent-tasks", tags=["agent-tasks"])
agent_trace_sink = InMemoryTraceSink(maximum_events=20_000)
agent_task_control_plane = AgentTaskControlPlane(
    router=SpecialistRouter(
        registry=default_specialist_registry(),
        trace_sink=agent_trace_sink,
    )
)


class AgentTaskCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="operator requested cancellation", max_length=1_000)


@router.post(
    "",
    response_model=AgentTaskRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_agent_task(
    task: TaskEnvelope,
    _: OperatorDependency,
) -> AgentTaskRecord:
    try:
        return await agent_task_control_plane.submit(task)
    except AgentTaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{request_id}", response_model=AgentTaskRecord)
async def get_agent_task(
    request_id: UUID,
    _: OperatorDependency,
) -> AgentTaskRecord:
    try:
        return await agent_task_control_plane.get(request_id)
    except AgentTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{request_id}/cancel",
    response_model=AgentTaskRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_agent_task(
    request_id: UUID,
    payload: AgentTaskCancelRequest,
    _: OperatorDependency,
) -> AgentTaskRecord:
    try:
        return await agent_task_control_plane.cancel(
            request_id=request_id,
            reason=payload.reason,
        )
    except AgentTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
