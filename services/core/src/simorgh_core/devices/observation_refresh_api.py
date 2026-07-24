from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.config import Settings, get_settings
from simorgh_core.devices.observation_refresh_broker import (
    ObservationRefreshBrokerError,
    ObservationRefreshBusyError,
    ObservationRefreshConflictError,
    ObservationRefreshDeviceUnavailableError,
    ObservationRefreshNotFoundError,
    ObservationRefreshPhase,
    ObservationRefreshRecord,
    observation_refresh_broker,
)
from simorgh_core.devices.observation_refresh_protocol import (
    DeviceObservationRefreshAckPayload,
)

router = APIRouter(prefix="/v1/devices", tags=["device-observation-refresh"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


class ObservationRefreshCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_ms: int = Field(default=5_000, ge=250, le=10_000)
    expected_state_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_active_package: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    reason: str = Field(default="operator requested fresh observation", max_length=1_000)


class ObservationRefreshCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="operator cancelled observation refresh", max_length=1_000)


class ObservationRefreshEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    session_id: UUID
    acknowledged_at_ms: int = Field(ge=0)
    stream_id: UUID
    sequence: int = Field(ge=0)
    snapshot_id: UUID
    state_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    captured_at_ms: int = Field(ge=0)
    active_package: str | None = Field(default=None, max_length=512)


class ObservationRefreshStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: UUID
    request_id: UUID
    request_message_id: UUID
    phase: ObservationRefreshPhase
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    deadline_at_ms: int = Field(ge=0)
    delivery_count: int = Field(ge=0)
    last_session_id: UUID | None = None
    acknowledgement: DeviceObservationRefreshAckPayload | None = None
    evidence: ObservationRefreshEvidenceResponse | None = None
    detail: str = Field(default="", max_length=1_000)

    @classmethod
    def from_record(
        cls,
        record: ObservationRefreshRecord,
    ) -> ObservationRefreshStatusResponse:
        evidence = record.evidence
        return cls(
            device_id=record.device_id,
            request_id=record.request_id,
            request_message_id=record.request_envelope.message_id,
            phase=record.phase,
            created_at_ms=record.created_at_ms,
            updated_at_ms=record.updated_at_ms,
            deadline_at_ms=record.deadline_at_ms,
            delivery_count=record.delivery_count,
            last_session_id=record.last_session_id,
            acknowledgement=record.acknowledgement,
            evidence=(
                ObservationRefreshEvidenceResponse(
                    message_id=evidence.message_id,
                    session_id=evidence.session_id,
                    acknowledged_at_ms=evidence.received_at_ms,
                    stream_id=evidence.stream_id,
                    sequence=evidence.sequence,
                    snapshot_id=evidence.snapshot_id,
                    state_fingerprint=evidence.state_fingerprint,
                    captured_at_ms=evidence.captured_at_ms,
                    active_package=evidence.active_package,
                )
                if evidence is not None
                else None
            ),
            detail=record.detail,
        )


def _require_operator(
    settings: SettingsDependency,
    authorization: AuthorizationHeader = None,
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
    "/{device_id}/observation-refreshes",
    response_model=ObservationRefreshStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_observation_refresh(
    device_id: UUID,
    payload: ObservationRefreshCreateRequest,
    _: OperatorDependency,
) -> ObservationRefreshStatusResponse:
    try:
        record = await observation_refresh_broker.create(
            device_id=device_id,
            timeout_ms=payload.timeout_ms,
            expected_state_fingerprint=payload.expected_state_fingerprint,
            expected_active_package=payload.expected_active_package,
            reason=payload.reason,
        )
    except ObservationRefreshBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ObservationRefreshDeviceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ObservationRefreshConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ObservationRefreshBrokerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ObservationRefreshStatusResponse.from_record(record)


@router.get(
    "/{device_id}/observation-refreshes/{request_id}",
    response_model=ObservationRefreshStatusResponse,
)
async def get_observation_refresh(
    device_id: UUID,
    request_id: UUID,
    _: OperatorDependency,
) -> ObservationRefreshStatusResponse:
    try:
        record = await observation_refresh_broker.get(
            device_id=device_id,
            request_id=request_id,
        )
    except ObservationRefreshNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ObservationRefreshStatusResponse.from_record(record)


@router.post(
    "/{device_id}/observation-refreshes/{request_id}/cancel",
    response_model=ObservationRefreshStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_observation_refresh(
    device_id: UUID,
    request_id: UUID,
    payload: ObservationRefreshCancelRequest,
    _: OperatorDependency,
    response: Response,
) -> ObservationRefreshStatusResponse:
    try:
        record = await observation_refresh_broker.cancel(
            device_id=device_id,
            request_id=request_id,
            reason=payload.reason,
        )
    except ObservationRefreshNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if record.phase != ObservationRefreshPhase.CANCELLED:
        response.status_code = status.HTTP_200_OK
    return ObservationRefreshStatusResponse.from_record(record)
