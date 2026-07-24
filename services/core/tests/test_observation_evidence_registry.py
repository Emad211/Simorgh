from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocket

from simorgh_core.devices.protocol import (
    AccessibilitySnapshotPayload,
    DeviceObservationPayload,
    DeviceRegistrationPayload,
    calculate_accessibility_state_fingerprint,
)
from simorgh_core.devices.registry import (
    DeviceRegistry,
    DeviceSession,
    ObservationSequenceConflictError,
    StoredObservationEvidence,
)

DEVICE_ID = UUID("11111111-1111-1111-1111-111111111111")
STREAM_ID = UUID("22222222-2222-2222-2222-222222222222")


def _registration() -> DeviceRegistrationPayload:
    return DeviceRegistrationPayload(
        app_version="0.1.0",
        sdk_int=31,
        android_release="12",
        manufacturer="Samsung",
        model="SM-A536B",
        build_fingerprint="samsung/a53/registry-test",
        support_tier="FULL",
        capabilities=["android.accessibility.observe.platform"],
    )


def _observation(sequence: int) -> DeviceObservationPayload:
    snapshot = AccessibilitySnapshotPayload(
        snapshot_id=uuid4(),
        captured_at_ms=10_000 + sequence,
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


async def _record(
    registry: DeviceRegistry,
    session: DeviceSession,
    *,
    message_id: UUID,
    observation: DeviceObservationPayload,
    received_at_ms: int,
) -> str:
    return await registry.record_observation(
        session=session,
        message_id=message_id,
        observation=observation,
        received_at_ms=received_at_ms,
    )


async def _lookup(
    registry: DeviceRegistry,
    observation: DeviceObservationPayload,
) -> StoredObservationEvidence | None:
    return await registry.observation_evidence(
        device_id=DEVICE_ID,
        stream_id=observation.stream_id,
        sequence=observation.sequence,
        snapshot_id=observation.snapshot.snapshot_id,
        state_fingerprint=observation.state_fingerprint,
    )


def _session() -> DeviceSession:
    return DeviceSession.create(
        device_id=DEVICE_ID,
        websocket=cast(WebSocket, object()),
        registration=_registration(),
    )


def test_exact_replay_refreshes_message_and_evidence_lru_together() -> None:
    async def scenario() -> None:
        registry = DeviceRegistry()
        session = _session()
        await registry.register(session)

        original_message_id = uuid4()
        original = _observation(0)
        assert await _record(
            registry,
            session,
            message_id=original_message_id,
            observation=original,
            received_at_ms=20_000,
        ) == "accepted"

        for sequence in range(1, 256):
            assert await _record(
                registry,
                session,
                message_id=uuid4(),
                observation=_observation(sequence),
                received_at_ms=20_000 + sequence,
            ) == "unchanged"

        assert await _record(
            registry,
            session,
            message_id=original_message_id,
            observation=original,
            received_at_ms=30_000,
        ) == "duplicate"

        assert await _record(
            registry,
            session,
            message_id=uuid4(),
            observation=_observation(256),
            received_at_ms=30_001,
        ) == "unchanged"

        evidence = await _lookup(registry, original)
        assert evidence is not None
        assert evidence.message_id == original_message_id
        assert evidence.received_at_ms == 30_000

    asyncio.run(scenario())


def test_same_message_id_cannot_change_capture_metadata() -> None:
    async def scenario() -> None:
        registry = DeviceRegistry()
        session = _session()
        await registry.register(session)

        message_id = uuid4()
        original = _observation(0)
        assert await _record(
            registry,
            session,
            message_id=message_id,
            observation=original,
            received_at_ms=20_000,
        ) == "accepted"

        changed_snapshot = original.snapshot.model_copy(
            update={"captured_at_ms": original.snapshot.captured_at_ms + 1_000}
        )
        conflicting = original.model_copy(update={"snapshot": changed_snapshot})
        assert conflicting.state_fingerprint == original.state_fingerprint

        with pytest.raises(
            ObservationSequenceConflictError,
            match="different observation payload",
        ):
            await _record(
                registry,
                session,
                message_id=message_id,
                observation=conflicting,
                received_at_ms=21_000,
            )

    asyncio.run(scenario())


def test_non_replayed_evidence_is_evicted_at_the_documented_bound() -> None:
    async def scenario() -> None:
        registry = DeviceRegistry()
        session = _session()
        await registry.register(session)

        original = _observation(0)
        await _record(
            registry,
            session,
            message_id=uuid4(),
            observation=original,
            received_at_ms=20_000,
        )
        for sequence in range(1, 257):
            await _record(
                registry,
                session,
                message_id=uuid4(),
                observation=_observation(sequence),
                received_at_ms=20_000 + sequence,
            )

        assert await _lookup(registry, original) is None

    asyncio.run(scenario())
