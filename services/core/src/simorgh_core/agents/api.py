from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.cancellation_contracts import (
    CancellationRequesterAuthority,
)
from simorgh_core.agents.cancellation_runtime import (
    cancellation_owner_registry,
    invocation_cancellation_adapter_registry,
)
from simorgh_core.agents.contracts import TaskEnvelope
from simorgh_core.agents.control_plane import (
    AgentTaskConflictError,
    AgentTaskControlPlane,
    AgentTaskNotFoundError,
    AgentTaskRoutingUnknownError,
    AgentTaskStoreUnavailableError,
)
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.router import SpecialistRouter
from simorgh_core.agents.task_state import AgentTaskRecord
from simorgh_core.agents.tracing import InMemoryTraceSink
from simorgh_core.devices.action_api import OperatorDependency

router = APIRouter(prefix="/v1/agent-tasks", tags=["agent-tasks"])
agent_trace_sink = InMemoryTraceSink(maximum_events=20_000)
agent_task_control_plane = AgentTaskControlPlane(
    router=SpecialistRouter(
        registry=default_specialist_registry(),
        trace_sink=agent_trace_sink,
    ),
    cancellation_registry=cancellation_owner_registry,
    adapter_cancellation_registry=(
        invocation_cancellation_adapter_registry
    ),
    trace_sink=agent_trace_sink,
)


class AgentTaskCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cancellation_id: UUID | None = None
    reason_code: str = Field(
        default="operator_requested",
        pattern=r"^[a-z][a-z0-9_.-]{0,127}$",
        max_length=128,
    )
    reason: str = Field(
        default="operator requested cancellation", max_length=1_000
    )


def _store_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "agent_task_store_unavailable",
            "message": str(exc),
        },
    )


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
    except AgentTaskRoutingUnknownError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agent_task_routing_unknown",
                "message": str(exc),
                "request_id": str(task.request_id),
            },
        ) from exc
    except AgentTaskStoreUnavailableError as exc:
        raise _store_unavailable(exc) from exc


@router.get("/{request_id}", response_model=AgentTaskRecord)
async def get_agent_task(
    request_id: UUID,
    _: OperatorDependency,
) -> AgentTaskRecord:
    try:
        return await agent_task_control_plane.get(request_id)
    except AgentTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentTaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AgentTaskStoreUnavailableError as exc:
        raise _store_unavailable(exc) from exc


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
            cancellation_id=payload.cancellation_id,
            reason_code=payload.reason_code,
            requester_authority=CancellationRequesterAuthority.OPERATOR,
        )
    except AgentTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentTaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AgentTaskStoreUnavailableError as exc:
        raise _store_unavailable(exc) from exc
