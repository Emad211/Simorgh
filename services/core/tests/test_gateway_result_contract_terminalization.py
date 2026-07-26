from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import ModelTier, TaskBudget, UsageVector
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import InMemoryInvocationStore, InvocationPhase
from simorgh_core.agents.model_gateway import (
    BudgetedModelGateway,
    BudgetedModelRequest,
    ModelCatalog,
    ModelOutputContractError,
    ModelSpec,
)
from simorgh_core.agents.tool_gateway import (
    BudgetedToolGateway,
    ToolCallRequest,
    ToolGatewayError,
)
from simorgh_core.providers.base import ModelOutput


class OversizedProvider:
    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        del input_text, instructions, max_output_tokens
        return ModelOutput(
            text="PRIVATE_OVERSIZED_MODEL_RESULT_239a" + "x" * 1_000_000,
            model=model or "cheap-fast",
            provider="fake",
            usage={"input_tokens": 10, "output_tokens": 1},
        )

    async def list_models(self) -> list[str]:
        return ["cheap-fast"]


class PrivateObject:
    def __repr__(self) -> str:
        return "PRIVATE_TOOL_OBJECT_90d1"


class NonJsonInvoker:
    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del tool_id, arguments
        return {"non_json": PrivateObject()}


def _catalog() -> ModelCatalog:
    return ModelCatalog(
        (
            ModelSpec(
                provider_id="fake",
                model_id="cheap-fast",
                tier=ModelTier.FAST,
                input_price_microusd_per_million_tokens=1_000_000,
                output_price_microusd_per_million_tokens=2_000_000,
                maximum_output_tokens=100,
            ),
        )
    )


def test_oversized_model_result_becomes_terminal_failed_not_reserved() -> None:
    store = InMemoryInvocationStore()
    request = BudgetedModelRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        operation="oversized-model-result",
        input_text="تحلیل",
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
            max_output_tokens=100,
            max_estimated_cost_microusd=10_000_000,
            max_elapsed_ms=10_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
        monotonic_millis=lambda: 100,
    )
    gateway = BudgetedModelGateway(
        provider=OversizedProvider(),
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
    )

    with pytest.raises(
        ModelOutputContractError,
        match="failed durable contract validation",
    ) as raised:
        asyncio.run(gateway.generate(request=request, budget=budget))

    record = store.get(request.invocation_id)
    assert record.state == InvocationPhase.FAILED
    assert record.failure_code == "result_contract_invalid"
    assert record.failure_detail == "typed_model_result_rejected"
    assert record.reserved_usage == UsageVector()
    assert record.committed_usage.model_calls == 1
    assert "PRIVATE_OVERSIZED_MODEL_RESULT_239a" not in str(raised.value)


def test_non_json_tool_result_becomes_terminal_failed_without_private_echo() -> None:
    store = InMemoryInvocationStore()
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
        invoker=NonJsonInvoker(),
        invocation_store=store,
    )

    with pytest.raises(
        ToolGatewayError,
        match="failed durable contract validation",
    ) as raised:
        asyncio.run(gateway.invoke(request=request, budget=budget))

    record = store.get(request.invocation_id)
    assert record.state == InvocationPhase.FAILED
    assert record.failure_code == "result_contract_invalid"
    assert record.failure_detail == "typed_tool_result_rejected"
    assert record.reserved_usage == UsageVector()
    assert record.committed_usage == UsageVector(tool_calls=1)
    assert "PRIVATE_TOOL_OBJECT_90d1" not in str(raised.value)
