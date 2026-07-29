from __future__ import annotations

from uuid import UUID, uuid4

from simorgh_core.agents.contracts import (
    ExecutionMode,
    InvocationState,
    TaskEnvelope,
)
from simorgh_core.agents.invocations import InvocationRecord
from simorgh_core.agents.task_state import AgentTaskPhase, AgentTaskRecord
from simorgh_core.agents.task_store import AgentTaskStoreEntryV1
from simorgh_core.agents.trace_retention import protected_trace_request_ids


def _routed_entry(*, execution_mode: ExecutionMode) -> AgentTaskStoreEntryV1:
    request_id = uuid4()
    return AgentTaskStoreEntryV1.model_construct(
        request_id=request_id,
        record=AgentTaskRecord.model_construct(
            request_id=request_id,
            phase=AgentTaskPhase.ROUTED,
            task=TaskEnvelope.model_construct(
                request_id=request_id,
                execution_mode=execution_mode,
            ),
        ),
    )


def _invocation(
    request_id: UUID,
    *,
    state: InvocationState,
) -> InvocationRecord:
    return InvocationRecord.model_construct(
        request_id=request_id,
        state=state,
    )


def test_routed_execution_request_is_protected_before_first_invocation() -> None:
    entry = _routed_entry(execution_mode=ExecutionMode.PLAN)

    protected = protected_trace_request_ids(
        task_entries=(entry,),
        invocation_records=(),
    )

    assert protected == frozenset({entry.request_id})


def test_route_only_request_does_not_require_an_invocation_for_retention() -> None:
    entry = _routed_entry(execution_mode=ExecutionMode.ROUTE_ONLY)

    protected = protected_trace_request_ids(
        task_entries=(entry,),
        invocation_records=(),
    )

    assert protected == frozenset()


def test_routed_request_with_only_terminal_invocations_is_not_active() -> None:
    entry = _routed_entry(execution_mode=ExecutionMode.PLAN)
    invocation = _invocation(
        entry.request_id,
        state=InvocationState.COMPLETED,
    )

    protected = protected_trace_request_ids(
        task_entries=(entry,),
        invocation_records=(invocation,),
    )

    assert protected == frozenset()


def test_routed_request_with_nonterminal_invocation_remains_protected() -> None:
    entry = _routed_entry(execution_mode=ExecutionMode.PLAN)
    invocation = _invocation(
        entry.request_id,
        state=InvocationState.RESERVED,
    )

    protected = protected_trace_request_ids(
        task_entries=(entry,),
        invocation_records=(invocation,),
    )

    assert protected == frozenset({entry.request_id})
