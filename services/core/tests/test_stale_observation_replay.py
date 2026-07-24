from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID, uuid4

from fastapi import WebSocket

from simorgh_core.devices.protocol import (
    AccessibilitySnapshotPayload,
    DeviceObservationPayload,
    DeviceRegistrationPayload,
    calculate_accessibility_state_fingerprint,
)
from simorgh_core.devices.registry import DeviceRegistry, DeviceSession

DEVICE_ID = UUID("11111111-1111-1111-1111-111111111111")
STREAM_ID = UUID("22222222-2222-2222-2222-222222222222")


def _session() -> DeviceSession:
    return DeviceSession.create(
        device_id=DEVICE_ID,
        websocket=cast(WebSocket, object()),
        registration=DeviceRegistrationPayload(
            app_version="0.1.0",
            sdk_int=31,
            android_release="12",
            manufacturer="Samsung",
            model="SM-A536B",
            build_fingerprint="samsung/a53/stale-replay-test",
            support_tier="FULL",
            capabilities=["android.accessibility.observe.platform"],
        ),
    )


def _observation(sequence: int, captured_at_ms: int) -> DeviceObservationPayload:
    snapshot = AccessibilitySnapshotPayload(
        snapshot_id=uuid4(),
        captured_at_ms=captured_at_ms,
        active_package="com.example",
        active_window_id=None,
        root_node_id=None,
        windows=[],
        nodes=[],
        truncated=False,
        truncation_reasons=[],
        max_depth_observed=0,
    )
    return DeviceObservationPayload(
        stream_id=STREAM_ID,
        sequence=sequence,
        state_fingerprint=calculate_accessibility_state_fingerprint(snapshot),
        snapshot=snapshot,
    )


def test_exact_replay_of_stale_message_remains_stale_and_has_no_evidence() -> None:
    async def scenario() -> None:
        registry = DeviceRegistry()
        session = _session()
        await registry.register(session)

        current = _observation(sequence=5, captured_at_ms=20_000)
        assert await registry.record_observation(
            session=session,
            message_id=uuid4(),
            observation=current,
            received_at_ms=20_010,
        ) == "accepted"

        stale_message_id = uuid4()
        stale = _observation(sequence=4, captured_at_ms=19_000)
        assert await registry.record_observation(
            session=session,
            message_id=stale_message_id,
            observation=stale,
            received_at_ms=20_020,
        ) == "stale"

        assert await registry.observation_evidence(
            device_id=DEVICE_ID,
            stream_id=stale.stream_id,
            sequence=stale.sequence,
            snapshot_id=stale.snapshot.snapshot_id,
            state_fingerprint=stale.state_fingerprint,
        ) is None

        assert await registry.record_observation(
            session=session,
            message_id=stale_message_id,
            observation=stale,
            received_at_ms=30_000,
        ) == "stale"

        assert await registry.observation_evidence(
            device_id=DEVICE_ID,
            stream_id=stale.stream_id,
            sequence=stale.sequence,
            snapshot_id=stale.snapshot.snapshot_id,
            state_fingerprint=stale.state_fingerprint,
        ) is None

    asyncio.run(scenario())
