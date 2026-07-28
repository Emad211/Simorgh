from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from simorgh_core.agents.invocations import (
    InvocationPhase,
    InvocationStore,
    InvocationStoreError,
)
from simorgh_core.agents.result_authority import RetentionDisposition
from simorgh_core.agents.task_state import AgentTaskPhase
from simorgh_core.agents.task_store import AgentTaskStore, AgentTaskStoreError
from simorgh_core.agents.trace_authority import CorrelatedTraceEvent
from simorgh_core.agents.trace_store import TraceStore

_PROTECTED_INVOCATION_PHASES = frozenset(
    {
        InvocationPhase.PENDING,
        InvocationPhase.RESERVED,
        InvocationPhase.UNKNOWN,
        InvocationPhase.UNKNOWN_SIDE_EFFECT,
    }
)
_PROTECTED_RETENTION = frozenset(
    {
        RetentionDisposition.LONG_LIVED,
        RetentionDisposition.LEGAL_HOLD,
    }
)


class TraceRetentionError(RuntimeError):
    pass


class TraceRetentionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    pruned_trace_count: int = Field(ge=0)
    pruned_event_count: int = Field(ge=0)
    protected_trace_count: int = Field(ge=0)
    retained_terminal_trace_count: int = Field(ge=0)


class TraceRetentionService:
    """Prune whole eligible terminal traces while preserving active authority."""

    def __init__(
        self,
        *,
        trace_store: TraceStore,
        task_store: AgentTaskStore,
        invocation_store: InvocationStore,
    ) -> None:
        self._traces = trace_store
        self._tasks = task_store
        self._invocations = invocation_store

    def prune(self, *, max_terminal_traces: int) -> TraceRetentionResult:
        if max_terminal_traces < 0:
            raise ValueError("max_terminal_traces cannot be negative")
        grouped: dict[UUID, list[CorrelatedTraceEvent]] = defaultdict(list)
        for event in self._traces.load():
            grouped[event.trace_id].append(event)

        protected = 0
        eligible: list[tuple[int, str, UUID]] = []
        for trace_id, events in grouped.items():
            ordered = sorted(events, key=lambda event: event.causal_sequence)
            request_id = ordered[0].request_id
            if self._is_protected(request_id=request_id, events=ordered):
                protected += 1
                continue
            eligible.append(
                (
                    max(event.occurred_at_ms for event in ordered),
                    str(trace_id),
                    trace_id,
                )
            )

        eligible.sort()
        prune_count = max(0, len(eligible) - max_terminal_traces)
        pruned_events = 0
        for _, _, trace_id in eligible[:prune_count]:
            pruned_events += self._traces.prune_trace(trace_id)
        return TraceRetentionResult(
            pruned_trace_count=prune_count,
            pruned_event_count=pruned_events,
            protected_trace_count=protected,
            retained_terminal_trace_count=len(eligible) - prune_count,
        )

    def _is_protected(
        self,
        *,
        request_id: UUID,
        events: list[CorrelatedTraceEvent],
    ) -> bool:
        try:
            task_entry = self._tasks.get(request_id)
        except AgentTaskStoreError:
            raise TraceRetentionError("task authority is unavailable for retention") from None
        if task_entry is None:
            return True
        task = task_entry.record
        if not task.terminal or task.phase == AgentTaskPhase.UNKNOWN:
            return True
        if any(event.retention in _PROTECTED_RETENTION for event in events):
            return True
        try:
            invocations = self._invocations.list_owned(request_id=request_id)
        except InvocationStoreError:
            raise TraceRetentionError(
                "invocation authority is unavailable for retention"
            ) from None
        return any(
            (not invocation.terminal)
            or invocation.state in _PROTECTED_INVOCATION_PHASES
            for invocation in invocations
        )


__all__ = [
    "TraceRetentionError",
    "TraceRetentionResult",
    "TraceRetentionService",
]
