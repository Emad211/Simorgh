from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from simorgh_core.config import Settings, get_settings
from simorgh_core.devices.action_broker import (
    DeviceActionNotFoundError,
    DeviceActionPhase,
    action_broker,
)
from simorgh_core.devices.action_semantics import (
    AndroidActionSemanticError,
    validate_result_semantics,
)
from simorgh_core.devices.actions import AndroidActionResult, ObservationReference
from simorgh_core.devices.observation_refresh_broker import observation_refresh_broker
from simorgh_core.devices.observation_refresh_protocol import (
    OBSERVATION_REFRESH_ACK_TYPE,
    DeviceObservationRefreshAckEnvelope,
    DeviceObservationRefreshAckPayload,
)
from simorgh_core.devices.protocol import (
    ActionResultAckStatus,
    DeviceActionCancelAckPayload,
    DeviceActionCommandAckPayload,
    DeviceActionResultAckPayload,
    DeviceErrorPayload,
    DeviceHeartbeatAckPayload,
    DeviceHeartbeatPayload,
    DeviceObservationAckPayload,
    DeviceObservationPayload,
    DeviceRegisteredPayload,
    DeviceRegistrationPayload,
    ProtocolEnvelope,
)
from simorgh_core.devices.registry import (
    DeviceSession,
    StoredObservationEvidence,
    registry,
)

router = APIRouter(prefix="/v1/devices", tags=["devices"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]

REGISTRATION_TIMEOUT_SECONDS = 15
HEARTBEAT_INTERVAL_SECONDS = 25
MAX_REGISTRATION_BYTES = 64_000
MAX_DEVICE_MESSAGE_BYTES = 2_000_000


def _is_authorized(websocket: WebSocket, settings: Settings) -> bool:
    configured = settings.simorgh_device_token
    if configured is None:
        return False
    expected = configured.get_secret_value()
    provided = websocket.headers.get("authorization", "")
    scheme, _, token = provided.partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(token, expected)


def _encoded_size(raw_message: str) -> int:
    return len(raw_message.encode("utf-8"))


def _decode_device_envelope(raw_message: str) -> ProtocolEnvelope:
    decoded = json.loads(raw_message)
    if not isinstance(decoded, dict):
        raise ValueError("device message must be a JSON object")
    if decoded.get("type") == OBSERVATION_REFRESH_ACK_TYPE:
        return DeviceObservationRefreshAckEnvelope.model_validate(decoded)
    return ProtocolEnvelope.model_validate(decoded)


async def _send_error(
    websocket: WebSocket,
    *,
    device_id: UUID | None,
    correlation_id: UUID | None,
    code: str,
    message: str,
    session: DeviceSession | None = None,
) -> None:
    envelope = ProtocolEnvelope.create(
        message_type="device.error",
        device_id=device_id,
        correlation_id=correlation_id,
        payload=DeviceErrorPayload(code=code, message=message[:1_000]),
    )
    if session is None:
        await websocket.send_text(envelope.model_dump_json())
    else:
        await session.send_envelope(envelope)


async def _handle_heartbeat(
    *,
    session: DeviceSession,
    envelope: ProtocolEnvelope,
) -> None:
    heartbeat = DeviceHeartbeatPayload.model_validate(envelope.payload)
    acknowledgement = ProtocolEnvelope.create(
        message_type="device.heartbeat_ack",
        device_id=session.device_id,
        correlation_id=envelope.message_id,
        payload=DeviceHeartbeatAckPayload(
            sequence=heartbeat.sequence,
            server_time_ms=int(time.time() * 1000),
        ),
    )
    await session.send_envelope(acknowledgement)


async def _handle_observation(
    *,
    session: DeviceSession,
    envelope: ProtocolEnvelope,
) -> None:
    received_at_ms = int(time.time() * 1000)
    observation = DeviceObservationPayload.model_validate(envelope.payload)
    observation_status = await registry.record_observation(
        session=session,
        message_id=envelope.message_id,
        observation=observation,
        received_at_ms=received_at_ms,
    )

    candidate = None
    if envelope.correlation_id is not None:
        candidate = await observation_refresh_broker.prepare_observation_completion(
            session=session,
            refresh_request_id=envelope.correlation_id,
            observation=observation,
            observation_status=observation_status,
        )

    acknowledgement = ProtocolEnvelope.create(
        message_type="device.observation_ack",
        device_id=session.device_id,
        correlation_id=envelope.message_id,
        payload=DeviceObservationAckPayload(
            stream_id=observation.stream_id,
            sequence=observation.sequence,
            snapshot_id=observation.snapshot.snapshot_id,
            status=observation_status,
            received_at_ms=received_at_ms,
        ),
    )
    await session.send_envelope(acknowledgement)

    if candidate is not None:
        await observation_refresh_broker.complete_observation(
            device_id=session.device_id,
            candidate=candidate,
        )


async def _handle_observation_refresh_ack(
    *,
    session: DeviceSession,
    envelope: DeviceObservationRefreshAckEnvelope,
) -> None:
    acknowledgement = DeviceObservationRefreshAckPayload.model_validate(envelope.payload)
    await observation_refresh_broker.record_ack(
        session=session,
        envelope=envelope,
        acknowledgement=acknowledgement,
    )


async def _handle_action_command_ack(
    *,
    session: DeviceSession,
    envelope: ProtocolEnvelope,
) -> None:
    acknowledgement = DeviceActionCommandAckPayload.model_validate(envelope.payload)
    await action_broker.record_command_ack(
        session=session,
        envelope=envelope,
        acknowledgement=acknowledgement,
    )


async def _send_action_result_ack(
    *,
    session: DeviceSession,
    result_envelope: ProtocolEnvelope,
    result: AndroidActionResult,
    result_status: ActionResultAckStatus,
    detail: str = "",
) -> int:
    sent_at_ms = int(time.time() * 1000)
    acknowledgement = ProtocolEnvelope.create(
        message_type="device.action_result_ack",
        device_id=session.device_id,
        correlation_id=result_envelope.message_id,
        payload=DeviceActionResultAckPayload(
            command_id=result.command_id,
            action_id=result.action_id,
            status=result_status,
            received_at_ms=sent_at_ms,
            detail=detail[:1_000],
        ),
    )
    await session.send_envelope(acknowledgement)
    return sent_at_ms


async def _reject_action_result(
    *,
    session: DeviceSession,
    envelope: ProtocolEnvelope,
    result: AndroidActionResult,
    detail: str,
) -> None:
    await _send_action_result_ack(
        session=session,
        result_envelope=envelope,
        result=result,
        result_status="rejected",
        detail=detail,
    )


async def _evidence_for_reference(
    *,
    device_id: UUID,
    reference: ObservationReference | None,
) -> StoredObservationEvidence | None:
    if reference is None:
        return None
    return await registry.observation_evidence(
        device_id=device_id,
        stream_id=reference.stream_id,
        sequence=reference.sequence,
        snapshot_id=reference.snapshot_id,
        state_fingerprint=reference.state_fingerprint,
    )


async def _handle_action_result(
    *,
    session: DeviceSession,
    envelope: ProtocolEnvelope,
) -> None:
    result = AndroidActionResult.model_validate(envelope.payload)

    try:
        record = await action_broker.get(
            device_id=session.device_id,
            action_id=result.action_id,
        )
    except DeviceActionNotFoundError:
        await _send_action_result_ack(
            session=session,
            result_envelope=envelope,
            result=result,
            result_status="unknown_action",
            detail="Core has no action record for this result",
        )
        return

    if result.command_id != record.command_id:
        await _reject_action_result(
            session=session,
            envelope=envelope,
            result=result,
            detail="result command_id does not match the original command",
        )
        return
    if envelope.correlation_id != record.command_envelope.message_id:
        await _reject_action_result(
            session=session,
            envelope=envelope,
            result=result,
            detail="result correlation_id does not match the command envelope",
        )
        return
    if record.phase == DeviceActionPhase.REJECTED:
        await _reject_action_result(
            session=session,
            envelope=envelope,
            result=result,
            detail="an Android-rejected command cannot later publish a result",
        )
        return

    if record.result is None:
        before_evidence = await _evidence_for_reference(
            device_id=session.device_id,
            reference=result.before_observation,
        )
        after_evidence = await _evidence_for_reference(
            device_id=session.device_id,
            reference=result.after_observation,
        )
        try:
            validate_result_semantics(
                command=record.command,
                result=result,
                before_evidence=before_evidence,
                after_evidence=after_evidence,
            )
        except AndroidActionSemanticError as exc:
            await _reject_action_result(
                session=session,
                envelope=envelope,
                result=result,
                detail=str(exc),
            )
            return

    result_status, durable_record = await action_broker.record_result(
        session=session,
        envelope=envelope,
        result=result,
    )
    sent_at_ms = await _send_action_result_ack(
        session=session,
        result_envelope=envelope,
        result=result,
        result_status=result_status,
    )
    if durable_record is not None and result_status in {"accepted", "duplicate"}:
        await action_broker.record_result_ack_sent(
            device_id=session.device_id,
            action_id=result.action_id,
            result_envelope_id=envelope.message_id,
            status=result_status,
            sent_at_ms=sent_at_ms,
        )


async def _handle_action_cancel_ack(
    *,
    session: DeviceSession,
    envelope: ProtocolEnvelope,
) -> None:
    acknowledgement = DeviceActionCancelAckPayload.model_validate(envelope.payload)
    await action_broker.record_cancel_ack(
        session=session,
        envelope=envelope,
        acknowledgement=acknowledgement,
    )


@router.websocket("/ws")
async def device_websocket(websocket: WebSocket, settings: SettingsDependency) -> None:
    if not _is_authorized(websocket, settings):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid device token")
        return

    await websocket.accept()
    session: DeviceSession | None = None

    try:
        try:
            raw_registration = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=REGISTRATION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="registration timeout",
            )
            return

        if _encoded_size(raw_registration) > MAX_REGISTRATION_BYTES:
            await websocket.close(
                code=status.WS_1009_MESSAGE_TOO_BIG,
                reason="registration message too large",
            )
            return

        try:
            registration_envelope = ProtocolEnvelope.model_validate_json(raw_registration)
            if registration_envelope.type != "device.register":
                raise ValueError("first message must be device.register")
            if registration_envelope.device_id is None:
                raise ValueError("device.register requires device_id")
            registration = DeviceRegistrationPayload.model_validate(
                registration_envelope.payload,
            )
        except (ValidationError, ValueError) as exc:
            await _send_error(
                websocket,
                device_id=None,
                correlation_id=None,
                code="invalid_registration",
                message=str(exc),
            )
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="invalid registration",
            )
            return

        session = DeviceSession.create(
            device_id=registration_envelope.device_id,
            websocket=websocket,
            registration=registration,
        )
        previous = await registry.register(session)
        if previous is not None:
            await previous.websocket.close(code=status.WS_1000_NORMAL_CLOSURE, reason="replaced")

        registered = ProtocolEnvelope.create(
            message_type="device.registered",
            device_id=session.device_id,
            correlation_id=registration_envelope.message_id,
            payload=DeviceRegisteredPayload(
                session_id=session.session_id,
                server_time_ms=int(time.time() * 1000),
                heartbeat_interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
            ),
        )
        await session.send_envelope(registered)
        await observation_refresh_broker.redeliver(session)
        await action_broker.redeliver(session)

        while True:
            raw_message = await websocket.receive_text()
            if _encoded_size(raw_message) > MAX_DEVICE_MESSAGE_BYTES:
                await _send_error(
                    websocket,
                    device_id=session.device_id,
                    correlation_id=None,
                    code="message_too_large",
                    message="device message exceeded the configured byte limit",
                    session=session,
                )
                await websocket.close(
                    code=status.WS_1009_MESSAGE_TOO_BIG,
                    reason="device message too large",
                )
                return

            if not await registry.is_current(session):
                await websocket.close(
                    code=status.WS_1000_NORMAL_CLOSURE,
                    reason="device session replaced",
                )
                return

            envelope: ProtocolEnvelope | None = None
            try:
                envelope = _decode_device_envelope(raw_message)
                if envelope.device_id != session.device_id:
                    raise ValueError("message device_id does not match registered device")

                if envelope.type == "device.heartbeat":
                    await _handle_heartbeat(session=session, envelope=envelope)
                elif envelope.type == "device.observation":
                    await _handle_observation(session=session, envelope=envelope)
                elif envelope.type == OBSERVATION_REFRESH_ACK_TYPE:
                    if not isinstance(envelope, DeviceObservationRefreshAckEnvelope):
                        raise ValueError("refresh ACK did not use typed envelope")
                    await _handle_observation_refresh_ack(
                        session=session,
                        envelope=envelope,
                    )
                elif envelope.type == "device.action_command_ack":
                    await _handle_action_command_ack(session=session, envelope=envelope)
                elif envelope.type == "device.action_result":
                    await _handle_action_result(session=session, envelope=envelope)
                elif envelope.type == "device.action_cancel_ack":
                    await _handle_action_cancel_ack(session=session, envelope=envelope)
                else:
                    raise ValueError(f"unsupported message type: {envelope.type}")
            except (ValidationError, ValueError) as exc:
                await _send_error(
                    websocket,
                    device_id=session.device_id,
                    correlation_id=envelope.message_id if envelope is not None else None,
                    code="invalid_message",
                    message=str(exc),
                    session=session,
                )

    except WebSocketDisconnect:
        pass
    finally:
        if session is not None:
            await registry.unregister(
                device_id=session.device_id,
                session_id=session.session_id,
            )
