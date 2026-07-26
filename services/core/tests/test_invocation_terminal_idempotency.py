from __future__ import annotations

from uuid import uuid4

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
    canonical_fingerprint,
)


def test_cancel_and_expire_are_noops_for_every_terminal_invocation() -> None:
    store = InMemoryInvocationStore()
    completed_id = uuid4()
    store.begin(
        invocation_id=completed_id,
        request_id=uuid4(),
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:fixture",
        input_fingerprint=canonical_fingerprint({"fixture": True}),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.search",
        connector_id="github",
    )
    store.reserve(invocation_id=completed_id, usage=UsageVector(tool_calls=1))
    completed = store.complete(
        invocation_id=completed_id,
        result_payload={"schema_version": "1.0", "ok": True},
        committed_usage=UsageVector(tool_calls=1),
    )
    assert store.cancel(completed_id) == completed
    assert store.expire(completed_id) == completed

    failed_id = uuid4()
    store.begin(
        invocation_id=failed_id,
        request_id=uuid4(),
        agent_id="general.planner",
        agent_version="1.0.0",
        operation="failure-fixture",
        input_fingerprint=canonical_fingerprint({"fixture": "failed"}),
    )
    failed = store.fail(
        invocation_id=failed_id,
        failure_code="fixture_failed",
        failure_detail="fixture",
    )
    assert store.cancel(failed_id) == failed
    assert store.expire(failed_id) == failed
