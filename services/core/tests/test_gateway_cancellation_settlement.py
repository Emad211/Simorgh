from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import ModelTier, TaskBudget
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import InMemoryInvocationStore, InvocationPhase
from simorgh_core.agents.model_gateway import (
    BudgetedModelGateway,
    BudgetedModelRequest,
    ModelCatalog,
    ModelGatewayError,
    ModelSpec,
)
from simorgh_core.agents.tool_gateway import (
    BudgetedToolGateway,
    ToolCallRequest,
    ToolGatewayError,
)
from simorgh_core.providers.base import ModelOutput


class CancellingProvider:
    def __init__(self, budget: BudgetAccount) -> None:
        self._budget = budget

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        del input_text, model, instructions, max_output_tokens
        self._budget.cancel()
        raise TimeoutError("PRIVATE_PROVIDER_ERROR")

    async def list_models(self) -> list[str]:
        return ["model-a"]


class CancellingInvoker:
    def __init__(self, budget: BudgetAccount) -> None:
        self._budget = budget

    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del tool_id, arguments
        self._budget.cancel()
        raise TimeoutError("PRIVATE_TOOL_ERROR")


def test_provider_failure_after_task_cancel_terminalizes_invocation_unknown() -> None:
    request = BudgetedModelRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        operation="cancel-race-model",
        input_text="تحلیل",
        allowed_tiers=(ModelTier.FAST,),
        minimum_tier=ModelTier.FAST,
        maximum_output_tokens=100,
        policy_hash="a" * 64,
    )
    budget = BudgetAccount(
        request_id=request.request_id,
        limits=TaskBudget(max_model_calls=1, max_output_tokens=100),
        monotonic_millis=lambda: 100,
    )
    store = InMemoryInvocationStore()
    gateway = BudgetedModelGateway(
        provider=CancellingProvider(budget),
        provider_id="fake",
        catalog=ModelCatalog((
            ModelSpec(
                provider_id="fake",
                model_id="model-a",
                tier=ModelTier.FAST,
                input_price_microusd_per_million_tokens=1,
                output_price_microusd_per_million_tokens=1,
                maximum_output_tokens=100,
            ),
        )),
        invocation_store=store,
    )

    with pytest.raises(ModelGatewayError) as raised:
        asyncio.run(gateway.generate(request=request, budget=budget))
    record = store.get(request.invocation_id)
    assert record.state == InvocationPhase.UNKNOWN
    assert record.committed_usage.model_calls == 1
    assert budget.snapshot().cancelled
    assert "PRIVATE_PROVIDER_ERROR" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_tool_failure_after_task_cancel_terminalizes_invocation_unknown() -> None:
    request = ToolCallRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="github.read",
        agent_version="1.0.0",
        tool_id="github.search",
        connector_id="github",
        allowed_data_sources=frozenset({"github"}),
        arguments={"query": "Simorgh"},
    )
    budget = BudgetAccount(
        request_id=request.request_id,
        limits=TaskBudget(max_model_calls=0, max_tool_calls=1),
        monotonic_millis=lambda: 100,
    )
    store = InMemoryInvocationStore()
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=CancellingInvoker(budget),
        invocation_store=store,
    )

    with pytest.raises(ToolGatewayError) as raised:
        asyncio.run(gateway.invoke(request=request, budget=budget))
    record = store.get(request.invocation_id)
    assert record.state == InvocationPhase.UNKNOWN
    assert record.committed_usage.tool_calls == 1
    assert budget.snapshot().cancelled
    assert "PRIVATE_TOOL_ERROR" not in str(raised.value)
    assert raised.value.__cause__ is None
