from __future__ import annotations

from collections.abc import Iterable

from simorgh_core.agents.contracts import (
    ExecutionMode,
    SideEffectPolicy,
    SpecialistDefinition,
    TaskBudget,
    TaskEnvelope,
    TaskKind,
)


class SpecialistRegistryError(ValueError):
    """Base class for deterministic specialist registry failures."""


class DuplicateSpecialistError(SpecialistRegistryError):
    pass


class UnknownSpecialistError(SpecialistRegistryError):
    pass


class SpecialistPolicyError(SpecialistRegistryError):
    pass


class SpecialistRegistry:
    """Compiled immutable view of active specialist versions and permissions."""

    def __init__(self, definitions: Iterable[SpecialistDefinition] = ()) -> None:
        compiled: dict[str, SpecialistDefinition] = {}
        for definition in definitions:
            if definition.agent_id in compiled:
                raise DuplicateSpecialistError(
                    f"specialist {definition.agent_id!r} was registered more than once"
                )
            compiled[definition.agent_id] = definition
        self._definitions = compiled
        self._validate_escalation_graph()

    def all(self) -> tuple[SpecialistDefinition, ...]:
        return tuple(
            sorted(
                self._definitions.values(),
                key=lambda definition: (
                    definition.routing_priority,
                    definition.agent_id,
                    definition.version,
                ),
            )
        )

    def get(self, agent_id: str) -> SpecialistDefinition:
        definition = self._definitions.get(agent_id)
        if definition is None:
            raise UnknownSpecialistError(f"specialist {agent_id!r} is not registered")
        return definition

    def eligible(self, task: TaskEnvelope) -> tuple[SpecialistDefinition, ...]:
        definitions = (
            definition
            for definition in self._definitions.values()
            if self._locale_matches(definition, task.locale)
            and self._execution_mode_matches(definition, task.execution_mode)
            and (
                task.explicit_task_kind is None
                or task.explicit_task_kind in definition.task_kinds
            )
        )
        return tuple(
            sorted(
                definitions,
                key=lambda definition: (
                    definition.routing_priority,
                    definition.agent_id,
                    definition.version,
                ),
            )
        )

    def for_task_kind(
        self,
        *,
        task_kind: TaskKind,
        locale: str,
        execution_mode: ExecutionMode,
    ) -> tuple[SpecialistDefinition, ...]:
        task = TaskEnvelope(
            received_at_ms=0,
            locale=locale,
            input_text="explicit typed task",
            requested_outcome="route explicit task",
            explicit_task_kind=task_kind,
            execution_mode=execution_mode,
        )
        return self.eligible(task)

    def require_tool(self, *, agent_id: str, tool_id: str) -> None:
        definition = self.get(agent_id)
        if tool_id not in definition.tool_allowlist:
            raise SpecialistPolicyError(
                f"specialist {agent_id!r} is not allowed to invoke tool {tool_id!r}"
            )

    def require_connector(self, *, agent_id: str, connector_id: str) -> None:
        definition = self.get(agent_id)
        if connector_id not in definition.connector_allowlist:
            raise SpecialistPolicyError(
                f"specialist {agent_id!r} is not allowed to invoke connector {connector_id!r}"
            )

    def effective_budget(
        self,
        *,
        agent_id: str,
        request_budget: TaskBudget,
    ) -> TaskBudget:
        ceiling = self.get(agent_id).budget_ceiling
        return intersect_budgets(request_budget, ceiling)

    def _validate_escalation_graph(self) -> None:
        for definition in self._definitions.values():
            for target in definition.model_policy.escalation_agent_ids:
                if target == definition.agent_id:
                    raise SpecialistPolicyError(
                        f"specialist {definition.agent_id!r} cannot escalate to itself"
                    )
                if target not in self._definitions:
                    raise SpecialistPolicyError(
                        f"specialist {definition.agent_id!r} escalates to unknown {target!r}"
                    )

    @staticmethod
    def _locale_matches(definition: SpecialistDefinition, locale: str) -> bool:
        if not definition.locale_prefixes:
            return True
        normalized = locale.casefold()
        return any(
            normalized.startswith(prefix.casefold())
            for prefix in definition.locale_prefixes
        )

    @staticmethod
    def _execution_mode_matches(
        definition: SpecialistDefinition,
        execution_mode: ExecutionMode,
    ) -> bool:
        policy = definition.side_effect_policy
        if execution_mode == ExecutionMode.EXECUTE_TYPED:
            return policy == SideEffectPolicy.TYPED_EXECUTOR_ONLY
        if execution_mode == ExecutionMode.PROPOSE_MUTATION:
            return policy in {
                SideEffectPolicy.PROPOSE_ONLY,
                SideEffectPolicy.TYPED_EXECUTOR_ONLY,
            }
        return True


def intersect_budgets(left: TaskBudget, right: TaskBudget) -> TaskBudget:
    """Return the strictest limit in each dimension."""

    return TaskBudget(
        max_model_calls=min(left.max_model_calls, right.max_model_calls),
        max_tool_calls=min(left.max_tool_calls, right.max_tool_calls),
        max_input_tokens=min(left.max_input_tokens, right.max_input_tokens),
        max_output_tokens=min(left.max_output_tokens, right.max_output_tokens),
        max_estimated_cost_microusd=min(
            left.max_estimated_cost_microusd,
            right.max_estimated_cost_microusd,
        ),
        max_elapsed_ms=min(left.max_elapsed_ms, right.max_elapsed_ms),
        max_retries=min(left.max_retries, right.max_retries),
        max_parallel_branches=min(
            left.max_parallel_branches,
            right.max_parallel_branches,
        ),
    )
