from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import ModelTier, TaskBudget, UsageVector
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationRecord,
    InvocationStoreCorruptionError,
)
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


class NeverCalledProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        del input_text, model, instructions, max_output_tokens
        self.calls += 1
        raise AssertionError("provider must not be called")

    async def list_models(self) -> list[str]:
        return ["cheap-fast"]


class NeverCalledInvoker:
    def __init__(self) -> None:
        self.calls = 0

    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del tool_id, arguments
        self.calls += 1
        raise AssertionError("tool invoker must not be called")


class ReserveFailingInvocationStore(InMemoryInvocationStore):
    def reserve(
        self,
        *,
        invocation_id: UUID,
        usage: UsageVector,
    ) -> InvocationRecord:
        del invocation_id, usage
        raise InvocationStoreCorruptionError(
            "simulated durable reservation failure"
        )


def _model_catalog() -> ModelCatalog:
    return ModelCatalog(
        (
            ModelSpec(
                provider_id="fake",
                model_id="cheap-fast",
                tier=ModelTier.FAST,
                input_price_microusd_per_million_tokens=1_000_000,
                output_price_microusd_per_million_tokens=2_000_000,
                maximum_output_tokens=500,
            ),
        )
    )


def test_model_provider_is_not_called_when_durable_reservation_fails() -> None:
    provider = NeverCalledProvider()
    request = BudgetedModelRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        operation="durable-reservation-failure",
        input_text="تحلیل سئو",
        instructions="Return concise output",
        allowed_tiers=(ModelTier.FAST,),
        minimum_tier=ModelTier.FAST,
        maximum_output_tokens=100,
        policy_hash="a" * 64,
    )
    budget = BudgetAccount(
        request_id=request.request_id,
        limits=TaskBudget(
            max_model_calls=1,
            max_tool_calls=0,
            max_input_tokens=10_000,
            max_output_tokens=1_000,
            max_estimated_cost_microusd=10_000_000,
            max_elapsed_ms=10_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
        monotonic_millis=lambda: 100,
    )
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_model_catalog(),
        invocation_store=ReserveFailingInvocationStore(),
    )

    with pytest.raises(ModelGatewayError, match="durably reserved"):
        asyncio.run(gateway.generate(request=request, budget=budget))

    assert provider.calls == 0
    assert budget.snapshot().reserved == UsageVector()
    assert budget.snapshot().committed == UsageVector()


def test_tool_invoker_is_not_called_when_durable_reservation_fails() -> None:
    invoker = NeverCalledInvoker()
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
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=ReserveFailingInvocationStore(),
    )

    with pytest.raises(ToolGatewayError, match="durably reserved"):
        asyncio.run(gateway.invoke(request=request, budget=budget))

    assert invoker.calls == 0
    assert budget.snapshot().reserved == UsageVector()
    assert budget.snapshot().committed == UsageVector()
