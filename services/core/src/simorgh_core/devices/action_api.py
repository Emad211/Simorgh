from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.config import Settings, get_settings
from simorgh_core.devices.action_broker import (
    DeviceActionBrokerError,
    DeviceActionBusyError,
    DeviceActionConflictError,
    DeviceActionNotFoundError,
    DeviceActionPhase,
    DeviceActionRecord,
    action_broker,
)
from simorgh_core.devices.actions import AndroidActionCommand, AndroidActionResult
from simorgh_core.devices.protocol import DeviceActionCommandAckPayload

router = APIRouter(prefix="/v1/devices", tags=["device-actions"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


class DeviceActionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: UUID
    command_id: UUID
    action_id: UUID
    command_message_id: UUID
    phase: DeviceActionPhase
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    delivery_count: int = Field(ge=0)
    command_ack: DeviceActionCommandAckPayload | None = None
    result: AndroidActionResult | None = None
    detail: str = Field(default="", max_length=2_000)

    @classmethod
    def from_record(cls, record: DeviceActionRecord) -> DeviceActionStatusResponse:
        return cls(
            device_id=record.device_id,
            command_id=record.command_id,
            action_id=record.action_id,
            command_message_id=record.command_envelope.message_id,
            phase=record.phase,
            created_at_ms=record.created_at_ms,
            updated_at_ms=record.updated_at_ms,
            delivery_count=record.delivery_count,
            command_ack=record.command_ack,
            result=record.result,
            detail=record.detail,
        )


class DeviceActionCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="operator requested cancellation", max_length=1_000)


def _require_operator(
    authorization: AuthorizationHeader,
    settings: SettingsDependency,
) -> None:
    configured = settings.simorgh_operator_token
    if configured is None or not configured.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SIMORGH_OPERATOR_TOKEN is not configured",
        )

    provided = authorization or ""
    scheme, _, token = provided.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        token,
        configured.get_secret_value(),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid operator token",
            headers={"WWW-Authenticate": "Bearer"},
        )


OperatorDependency = Annotated[None, Depends(_require_operator)]


@router.post(
    "/{device_id}/actions",
    response_model=DeviceActionStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_action(
    device_id: UUID,
    command: AndroidActionCommand,
    _: OperatorDependency,
) -> DeviceActionStatusResponse:
    try:
        record = await action_broker.dispatch(device_id=device_id, command=command)
    except DeviceActionBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DeviceActionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DeviceActionBrokerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DeviceActionStatusResponse.from_record(record)


@router.get(
    "/{device_id}/actions/{action_id}",
    response_model=DeviceActionStatusResponse,
)
async def get_action_status(
    device_id: UUID,
    action_id: UUID,
    _: OperatorDependency,
) -> DeviceActionStatusResponse:
    try:
        record = await action_broker.get(device_id=device_id, action_id=action_id)
    except DeviceActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DeviceActionStatusResponse.from_record(record)


@router.post(
    "/{device_id}/actions/{action_id}/cancel",
    response_model=DeviceActionStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_action(
    device_id: UUID,
    action_id: UUID,
    payload: DeviceActionCancelRequest,
    _: OperatorDependency,
    response: Response,
) -> DeviceActionStatusResponse:
    try:
        record = await action_broker.cancel(
            device_id=device_id,
            action_id=action_id,
            reason=payload.reason,
        )
    except DeviceActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if record.terminal:
        response.status_code = status.HTTP_200_OK
    return DeviceActionStatusResponse.from_record(record)
