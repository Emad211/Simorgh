from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str, *, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: count={count}, expected=1")
    file.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "services/core/tests/test_cancellation_acceptance.py",
    "        for event in trace.snapshot()\n",
    "        for event in trace.for_request(task.request_id)\n",
    label="trace fixture accessor",
)

replace_exact(
    "services/core/tests/test_cancellation_invocation_authority.py",
    "    assert store.list_owned(request_id=request_id) == (first, second)\n",
    "    assert store.list_owned(request_id=request_id) == tuple(expected)\n",
    label="deterministic ownership ordering assertion",
)

replace_exact(
    "services/core/tests/test_invocation_lifecycle_hardening.py",
    "    InvocationKind,\n"
    "    InvocationPhase,\n"
    "    InvocationStateError,\n",
    "    InvocationKind,\n"
    "    InvocationNotFoundError,\n"
    "    InvocationPhase,\n"
    "    InvocationStateError,\n",
    label="lifecycle missing-parent import",
)

replace_exact(
    "services/core/tests/test_invocation_lifecycle_hardening.py",
    '''def test_retry_metadata_is_rejected_until_retry_boundary_is_implemented() -> None:
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
''',
    '''def test_child_invocation_requires_an_existing_terminal_parent() -> None:
    store = InMemoryInvocationStore()

    with pytest.raises(InvocationNotFoundError, match="does not exist"):
        store.begin(
            invocation_id=uuid4(),
            request_id=uuid4(),
            agent_id="github.read",
            agent_version="1.0.0",
            operation="child-fixture",
            input_fingerprint=canonical_fingerprint({"fixture": True}),
            parent_invocation_id=uuid4(),
            attempt=2,
        )
''',
    label="legacy retry-boundary test",
)
