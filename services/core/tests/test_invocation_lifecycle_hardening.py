from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
    InvocationPhase,
    InvocationStateError,
    canonical_fingerprint,
)


def test_empty_failure_detail_replay_is_idempotent() -> None:
    store = InMemoryInvocationStore()
    invocation_id = uuid4()
    store.begin(
        invocation_id=invocation_id,
        request_id=uuid4(),
        agent_id="general.planner",
        agent_version="1.0.0",
        operation="empty-detail-fixture",
        input_fingerprint=canonical_fingerprint({"fixture": True}),
    )

    first = store.fail(
        invocation_id=invocation_id,
        failure_code="fixture_failed",
        failure_detail="   ",
    )
    replay = store.fail(
        invocation_id=invocation_id,
        failure_code="fixture_failed",
        failure_detail="",
    )

    assert first == replay
    assert first.failure_detail is None


def test_repeated_cancel_after_reserved_uncertainty_is_idempotent() -> None:
    store = InMemoryInvocationStore()
    invocation_id = uuid4()
    store.begin(
        invocation_id=invocation_id,
        request_id=uuid4(),
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.search",
        input_fingerprint=canonical_fingerprint({"query": "fixture"}),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.search",
        connector_id="github",
    )
    store.reserve(
        invocation_id=invocation_id,
        usage=UsageVector(tool_calls=1),
    )

    first = store.cancel(invocation_id)
    replay = store.cancel(invocation_id)

    assert first == replay
    assert first.state == InvocationPhase.UNKNOWN
    assert first.committed_usage == UsageVector(tool_calls=1)


def test_repeated_expiry_after_reserved_mutation_uncertainty_is_idempotent() -> None:
    store = InMemoryInvocationStore()
    invocation_id = uuid4()
    store.begin(
        invocation_id=invocation_id,
        request_id=uuid4(),
        agent_id="android.executor",
        agent_version="1.0.0",
        operation="mutation-fixture",
        input_fingerprint=canonical_fingerprint({"plan_hash": "a" * 64}),
        kind=InvocationKind.SPECIALIST,
        effect=InvocationEffect.MUTATION,
    )
    store.reserve(
        invocation_id=invocation_id,
        usage=UsageVector(tool_calls=1),
    )

    first = store.expire(invocation_id)
    replay = store.expire(invocation_id)

    assert first == replay
    assert first.state == InvocationPhase.UNKNOWN_SIDE_EFFECT


def test_retry_metadata_is_rejected_until_retry_boundary_is_implemented() -> None:
    store = InMemoryInvocationStore()

    with pytest.raises(InvocationStateError, match="retry invocation chains"):
        store.begin(
            invocation_id=uuid4(),
            request_id=uuid4(),
            agent_id="github.read",
            agent_version="1.0.0",
            operation="retry-fixture",
            input_fingerprint=canonical_fingerprint({"fixture": True}),
            parent_invocation_id=uuid4(),
            attempt=2,
        )
