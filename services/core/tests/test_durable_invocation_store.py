from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import (
    MAX_INVOCATION_RESULT_BYTES,
    InMemoryInvocationStore,
    InvocationConflictError,
    InvocationEffect,
    InvocationKind,
    InvocationPhase,
    InvocationStartKind,
    InvocationStoreCorruptionError,
    InvocationStoreSchemaError,
    InvocationStoreUnhealthyError,
    canonical_fingerprint,
)


def _begin_tool(
    store: SQLiteInvocationStore | InMemoryInvocationStore,
    *,
    invocation_id: UUID | None = None,
    request_id: UUID | None = None,
    query: str = "simorgh",
) -> tuple[UUID, UUID]:
    invocation = invocation_id or uuid4()
    request = request_id or uuid4()
    started = store.begin(
        invocation_id=invocation,
        request_id=request,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.search",
        input_fingerprint=canonical_fingerprint({"query": query}),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.search",
        connector_id="github",
    )
    assert started.kind == InvocationStartKind.NEW
    return invocation, request


def test_completed_invocation_replays_after_store_reopen(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path, wall_clock_millis=lambda: 1_000)
    invocation_id, request_id = _begin_tool(store)
    reserved_usage = UsageVector(tool_calls=1)
    store.reserve(invocation_id=invocation_id, usage=reserved_usage)
    completed = store.complete(
        invocation_id=invocation_id,
        result_payload={"repository": "Emad211/Simorgh", "items": 3},
        committed_usage=reserved_usage,
    )
    store.close()

    reopened = SQLiteInvocationStore(path, wall_clock_millis=lambda: 2_000)
    replay = reopened.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.search",
        input_fingerprint=canonical_fingerprint({"query": "simorgh"}),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.search",
        connector_id="github",
    )

    assert replay.kind == InvocationStartKind.REPLAY
    assert replay.record == completed
    assert replay.record.committed_usage == reserved_usage
    assert replay.record.reserved_usage == UsageVector()
    reopened.close()


def test_same_invocation_id_with_changed_target_or_input_conflicts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path)
    invocation_id, request_id = _begin_tool(store)

    with pytest.raises(InvocationConflictError, match="immutable identity"):
        store.begin(
            invocation_id=invocation_id,
            request_id=request_id,
            agent_id="github.read",
            agent_version="1.0.0",
            operation="tool:github.search",
            input_fingerprint=canonical_fingerprint({"query": "changed"}),
            kind=InvocationKind.TOOL,
            effect=InvocationEffect.READ_ONLY,
            tool_id="github.search",
            connector_id="github",
        )
    store.close()


def test_reserved_read_invocation_recovers_unknown_and_keeps_conservative_usage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path, wall_clock_millis=lambda: 1_000)
    invocation_id, request_id = _begin_tool(store)
    reserved_usage = UsageVector(tool_calls=1)
    store.reserve(invocation_id=invocation_id, usage=reserved_usage)
    store.close()

    reopened = SQLiteInvocationStore(path, wall_clock_millis=lambda: 2_000)
    recovered = reopened.get(invocation_id)
    terminal = reopened.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.search",
        input_fingerprint=canonical_fingerprint({"query": "simorgh"}),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.search",
        connector_id="github",
    )

    assert recovered.state == InvocationPhase.UNKNOWN
    assert recovered.committed_usage == reserved_usage
    assert recovered.reserved_usage == UsageVector()
    assert recovered.failure_code == "process_interrupted"
    assert terminal.kind == InvocationStartKind.TERMINAL
    reopened.close()


def test_pending_invocation_recovers_unknown_without_claiming_external_cost(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path, wall_clock_millis=lambda: 1_000)
    invocation_id, _ = _begin_tool(store)
    store.close()

    reopened = SQLiteInvocationStore(path, wall_clock_millis=lambda: 2_000)
    recovered = reopened.get(invocation_id)

    assert recovered.state == InvocationPhase.UNKNOWN
    assert recovered.committed_usage == UsageVector()
    assert recovered.reserved_usage == UsageVector()
    reopened.close()


def test_reserved_mutation_recovers_unknown_side_effect(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path, wall_clock_millis=lambda: 1_000)
    invocation_id = uuid4()
    store.begin(
        invocation_id=invocation_id,
        request_id=uuid4(),
        agent_id="android.executor",
        agent_version="1.0.0",
        operation="typed-mutation-fixture",
        input_fingerprint=canonical_fingerprint({"plan_hash": "a" * 64}),
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.MUTATION,
    )
    reserved = UsageVector(tool_calls=1)
    store.reserve(invocation_id=invocation_id, usage=reserved)
    store.close()

    reopened = SQLiteInvocationStore(path, wall_clock_millis=lambda: 2_000)
    recovered = reopened.get(invocation_id)

    assert recovered.state == InvocationPhase.UNKNOWN_SIDE_EFFECT
    assert recovered.effect == InvocationEffect.MUTATION
    assert recovered.committed_usage == reserved
    reopened.close()


def test_cancel_before_reservation_is_terminal_without_usage(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path)
    invocation_id, _ = _begin_tool(store)
    cancelled = store.cancel(invocation_id)
    store.close()

    reopened = SQLiteInvocationStore(path)
    recovered = reopened.get(invocation_id)
    assert recovered == cancelled
    assert recovered.state == InvocationPhase.CANCELLED
    assert recovered.committed_usage == UsageVector()
    reopened.close()


def test_completed_result_and_actual_usage_are_immutable(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path)
    invocation_id, _ = _begin_tool(store)
    usage = UsageVector(tool_calls=1)
    store.reserve(invocation_id=invocation_id, usage=usage)
    store.complete(
        invocation_id=invocation_id,
        result_payload={"items": []},
        committed_usage=usage,
    )

    with pytest.raises(InvocationConflictError, match="different result or usage"):
        store.complete(
            invocation_id=invocation_id,
            result_payload={"items": ["changed"]},
            committed_usage=usage,
        )
    store.close()


def test_oversized_result_is_rejected_before_persistence() -> None:
    store = InMemoryInvocationStore()
    invocation_id = uuid4()
    store.begin(
        invocation_id=invocation_id,
        request_id=uuid4(),
        agent_id="research.read",
        agent_version="1.0.0",
        operation="oversized-result-fixture",
        input_fingerprint=canonical_fingerprint({"query": "fixture"}),
    )

    with pytest.raises(ValueError, match="durable payload limit"):
        store.complete(
            invocation_id=invocation_id,
            result_payload={"text": "x" * (MAX_INVOCATION_RESULT_BYTES + 1)},
        )


def test_payload_hash_tampering_fails_closed_and_latches_store(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path)
    invocation_id, _ = _begin_tool(store)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE invocation_records SET payload_json = payload_json || ' '",
    )
    connection.commit()
    connection.close()

    reopened = SQLiteInvocationStore(path, recover_interrupted=False)
    with pytest.raises(InvocationStoreCorruptionError, match="hash mismatch"):
        reopened.load()
    with pytest.raises(InvocationStoreUnhealthyError, match="unhealthy"):
        reopened.get(invocation_id)
    reopened.close()


def test_indexed_column_tampering_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path)
    invocation_id, _ = _begin_tool(store)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE invocation_records SET agent_id = 'changed.agent' WHERE invocation_id = ?",
        (str(invocation_id),),
    )
    connection.commit()
    connection.close()

    reopened = SQLiteInvocationStore(path, recover_interrupted=False)
    with pytest.raises(
        InvocationStoreCorruptionError,
        match="indexed columns do not match payload",
    ):
        reopened.load()
    reopened.close()


def test_unsupported_schema_fails_at_open(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    store = SQLiteInvocationStore(path)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        """
        UPDATE invocation_store_metadata
        SET value = '999'
        WHERE key = 'schema_version'
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(InvocationStoreSchemaError, match="unsupported"):
        SQLiteInvocationStore(path)
