from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.contracts import InvocationState
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationConflictError,
    InvocationStartKind,
    InvocationStateError,
    canonical_fingerprint,
    stable_invocation_id,
)


def test_completed_invocation_replays_without_new_work() -> None:
    request_id = uuid4()
    invocation_id = stable_invocation_id(
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="github.search",
    )
    fingerprint = canonical_fingerprint({"query": "simorgh"})
    store = InMemoryInvocationStore()

    started = store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="github.search",
        input_fingerprint=fingerprint,
    )
    assert started.kind == InvocationStartKind.NEW
    completed = store.complete(
        invocation_id=invocation_id,
        result_payload={"items": ["Emad211/Simorgh"]},
    )
    assert completed.state == InvocationState.COMPLETED

    replay = store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="github.search",
        input_fingerprint=fingerprint,
    )
    assert replay.kind == InvocationStartKind.REPLAY
    assert replay.record.result_payload == {"items": ["Emad211/Simorgh"]}


def test_same_invocation_id_with_different_input_fails_closed() -> None:
    request_id = uuid4()
    invocation_id = stable_invocation_id(
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="github.search",
    )
    store = InMemoryInvocationStore()
    store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        operation="github.search",
        input_fingerprint=canonical_fingerprint({"query": "one"}),
    )

    with pytest.raises(InvocationConflictError):
        store.begin(
            invocation_id=invocation_id,
            request_id=request_id,
            agent_id="github.read",
            agent_version="1.0.0",
            operation="github.search",
            input_fingerprint=canonical_fingerprint({"query": "two"}),
        )


def test_pending_and_terminal_invocations_do_not_start_automatic_retries() -> None:
    request_id = uuid4()
    invocation_id = uuid4()
    store = InMemoryInvocationStore()
    first = store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="plan",
        input_fingerprint=canonical_fingerprint({"task": "build"}),
    )
    assert first.kind == InvocationStartKind.NEW

    pending = store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="plan",
        input_fingerprint=canonical_fingerprint({"task": "build"}),
    )
    assert pending.kind == InvocationStartKind.IN_PROGRESS

    store.fail(
        invocation_id=invocation_id,
        failure_code="provider_failure",
        failure_detail="upstream unavailable",
    )
    terminal = store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="development.planner",
        agent_version="1.0.0",
        operation="plan",
        input_fingerprint=canonical_fingerprint({"task": "build"}),
    )
    assert terminal.kind == InvocationStartKind.TERMINAL
    assert terminal.record.state == InvocationState.FAILED

    with pytest.raises(InvocationStateError):
        store.complete(
            invocation_id=invocation_id,
            result_payload={"unexpected": True},
        )


def test_completed_result_content_is_immutable() -> None:
    invocation_id = uuid4()
    request_id = uuid4()
    store = InMemoryInvocationStore()
    store.begin(
        invocation_id=invocation_id,
        request_id=request_id,
        agent_id="calendar.read",
        agent_version="1.0.0",
        operation="calendar.search",
        input_fingerprint=canonical_fingerprint({"date": "2026-07-25"}),
    )
    store.complete(
        invocation_id=invocation_id,
        result_payload={"events": []},
    )

    with pytest.raises(InvocationConflictError):
        store.complete(
            invocation_id=invocation_id,
            result_payload={"events": ["changed"]},
        )
