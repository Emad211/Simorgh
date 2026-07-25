from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.budget import BudgetSnapshot
from simorgh_core.agents.contracts import RoutingDecision, RoutingState, TaskEnvelope


class AgentTaskPhase(StrEnum):
    ROUTING = "routing"
    ROUTED = "routed"
    NEEDS_CLARIFICATION = "needs_clarification"
    NEEDS_ESCALATION = "needs_escalation"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_BLOCKED = "policy_blocked"
    CONTRACT_INVALID = "contract_invalid"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


DECISION_PHASES: dict[RoutingState, AgentTaskPhase] = {
    RoutingState.ROUTED: AgentTaskPhase.ROUTED,
    RoutingState.NEEDS_CLARIFICATION: AgentTaskPhase.NEEDS_CLARIFICATION,
    RoutingState.NEEDS_ESCALATION: AgentTaskPhase.NEEDS_ESCALATION,
    RoutingState.BUDGET_EXHAUSTED: AgentTaskPhase.BUDGET_EXHAUSTED,
    RoutingState.POLICY_BLOCKED: AgentTaskPhase.POLICY_BLOCKED,
    RoutingState.CONTRACT_INVALID: AgentTaskPhase.CONTRACT_INVALID,
}

TERMINAL_AGENT_TASK_PHASES = frozenset(
    phase for phase in AgentTaskPhase if phase != AgentTaskPhase.ROUTING
)


class AgentTaskRecord(BaseModel):
    """Operator-visible task state; private trace payloads remain outside this record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    phase: AgentTaskPhase
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    task: TaskEnvelope
    routing_decision: RoutingDecision | None = None
    budget: BudgetSnapshot
    cancel_reason: str | None = Field(default=None, max_length=1_000)
    detail: str = Field(default="", max_length=2_000)

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_AGENT_TASK_PHASES

    @model_validator(mode="after")
    def validate_phase_shape(self) -> Self:
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("updated_at_ms cannot precede created_at_ms")
        if self.task.request_id != self.request_id:
            raise ValueError("task request_id does not match record request_id")
        if self.budget.request_id != self.request_id:
            raise ValueError("budget request_id does not match record request_id")

        if self.phase == AgentTaskPhase.ROUTING:
            if self.routing_decision is not None:
                raise ValueError("routing phase cannot already contain a decision")
        elif self.phase == AgentTaskPhase.CANCELLED:
            if self.cancel_reason is None:
                raise ValueError("cancelled task requires a cancel reason")
        elif self.phase in {AgentTaskPhase.EXPIRED, AgentTaskPhase.UNKNOWN}:
            if self.routing_decision is not None:
                raise ValueError(
                    f"{self.phase.value} task cannot contain a routing decision"
                )
        else:
            decision = self.routing_decision
            if decision is None:
                raise ValueError("routed terminal phase requires a routing decision")
            if decision.request_id != self.request_id:
                raise ValueError("routing decision request_id does not match record")
            if DECISION_PHASES[decision.state] != self.phase:
                raise ValueError("record phase does not match routing decision state")

        if self.phase != AgentTaskPhase.CANCELLED and self.cancel_reason is not None:
            raise ValueError("non-cancelled task cannot contain a cancel reason")
        return self
