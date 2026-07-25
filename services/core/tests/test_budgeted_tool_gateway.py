from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import TaskBudget
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import InMemoryInvocationStore
from simorgh_core.agents.registry import SpecialistPolicyError
from simorgh_core.agents.tool_gateway import (
    BudgetedToolGateway,
    ToolCallRequest,
    ToolEffect,
    ToolMutationBlockedError,
)


class RecordingInvoker:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls += 1
        self.requests.append((tool_id, arguments))
        return {"repository": "Emad211/Simorgh", "query": arguments.get("query")}


def _budget(request_id) -> BudgetAccount:
    return BudgetAccount(
        request_id=request_id,
        limits=TaskBudget(
            max_model_calls=0,
            max_tool_calls=1,
            max_input_tokens=0,
            max_output_tokens=0,
            max_estimated_cost_microusd=0,
            max_elapsed_ms=10_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
        monotonic_millis=lambda: 100,
    )


def test_allowed_read_tool_is_budgeted_and_exact_retry_is_replayed() -> None:
    request_id = uuid4()
    request = ToolCallRequest(
        invocation_id=uuid4(),
        request_id=request_id,
        agent_id="github.read",
        agent_version="1.0.0",
        tool_id="github.search",
        connector_id="github",
        arguments={"query": "Simorgh"},
    )
    invoker = RecordingInvoker()
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=InMemoryInvocationStore(),
    )
    budget = _budget(request_id)

    first = asyncio.run(gateway.invoke(request=request, budget=budget))
    replay = asyncio.run(gateway.invoke(request=request, budget=budget))

    assert invoker.calls == 1
    assert not first.replayed
    assert replay.replayed
    assert replay.payload == first.payload
    assert budget.snapshot().committed.tool_calls == 1


def test_unlisted_tool_or_connector_is_rejected_before_invoker() -> None:
    request_id = uuid4()
    invoker = RecordingInvoker()
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=InMemoryInvocationStore(),
    )

    with pytest.raises(SpecialistPolicyError, match="not allowed to invoke tool"):
        asyncio.run(
            gateway.invoke(
                request=ToolCallRequest(
                    invocation_id=uuid4(),
                    request_id=request_id,
                    agent_id="github.read",
                    agent_version="1.0.0",
                    tool_id="gmail.send",
                    connector_id="gmail",
                    arguments={},
                ),
                budget=_budget(request_id),
            )
        )
    assert invoker.calls == 0

    with pytest.raises(SpecialistPolicyError, match="not allowed to invoke connector"):
        asyncio.run(
            gateway.invoke(
                request=ToolCallRequest(
                    invocation_id=uuid4(),
                    request_id=request_id,
                    agent_id="github.read",
                    agent_version="1.0.0",
                    tool_id="github.search",
                    connector_id="gmail",
                    arguments={},
                ),
                budget=_budget(request_id),
            )
        )
    assert invoker.calls == 0


def test_planning_agent_cannot_execute_mutation_tool() -> None:
    request_id = uuid4()
    invoker = RecordingInvoker()
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=InMemoryInvocationStore(),
    )

    with pytest.raises(ToolMutationBlockedError, match="does not permit mutation"):
        asyncio.run(
            gateway.invoke(
                request=ToolCallRequest(
                    invocation_id=uuid4(),
                    request_id=request_id,
                    agent_id="development.planner",
                    agent_version="1.0.0",
                    tool_id="github.fetch-file",
                    connector_id="github",
                    effect=ToolEffect.MUTATION,
                    arguments={"path": "README.md"},
                ),
                budget=_budget(request_id),
            )
        )
    assert invoker.calls == 0
