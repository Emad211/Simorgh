from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import ModelTier, TaskBudget, UsageVector
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocations import (
    InMemoryInvocationStore,
    InvocationEffect,
    InvocationKind,
    InvocationStateError,
    canonical_fingerprint,
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
        raise AssertionError("invoker must not be called")


def _catalog() -> ModelCatalog:
    return ModelCatalog(
        (
            ModelSpec(
                provider_id="fake",
                model_id="cheap-fast",
                tier=ModelTier.FAST,
                input_price_microusd_per_million_tokens=1_000_000,
                output_price_microusd_per_million_tokens=2_000_000,
                maximum_output_tokens=256,
            ),
        )
    )


def test_model_gateway_rejects_budget_owned_by_another_task() -> None:
    provider = NeverCalledProvider()
    store = InMemoryInvocationStore()
    request = BudgetedModelRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        operation="budget-owner-fixture",
        input_text="تحلیل سئو",
        instructions="Return concise output",
        allowed_tiers=(ModelTier.FAST,),
        minimum_tier=ModelTier.FAST,
        maximum_output_tokens=100,
        policy_hash="a" * 64,
    )
    wrong_budget = BudgetAccount(
        request_id=uuid4(),
        limits=TaskBudget(max_model_calls=1),
        monotonic_millis=lambda: 100,
    )
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
    )

    with pytest.raises(ModelGatewayError, match="identity does not match"):
        asyncio.run(gateway.generate(request=request, budget=wrong_budget))

    assert provider.calls == 0
    assert store.load() == []
    assert wrong_budget.snapshot().committed == UsageVector()


def test_tool_gateway_rejects_budget_owned_by_another_task() -> None:
    invoker = NeverCalledInvoker()
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
    wrong_budget = BudgetAccount(
        request_id=uuid4(),
        limits=TaskBudget(max_model_calls=0, max_tool_calls=1),
        monotonic_millis=lambda: 100,
    )
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=store,
    )

    with pytest.raises(ToolGatewayError, match="identity does not match"):
        asyncio.run(gateway.invoke(request=request, budget=wrong_budget))

    assert invoker.calls == 0
    assert store.load() == []
    assert wrong_budget.snapshot().committed == UsageVector()


def test_model_completion_requires_durable_reservation() -> None:
    store = InMemoryInvocationStore()
    invocation_id = uuid4()
    store.begin(
        invocation_id=invocation_id,
        request_id=uuid4(),
        agent_id="system.router",
        agent_version="1.0.0",
        operation="model-fixture",
        input_fingerprint=canonical_fingerprint({"input": "fixture"}),
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="fake",
        model_id="cheap-fast",
    )

    with pytest.raises(InvocationStateError, match="pre-call reservation"):
        store.complete(
            invocation_id=invocation_id,
            result_payload={"text": "invalid direct completion"},
            committed_usage=UsageVector(model_calls=1),
        )


def test_nonzero_tool_failure_usage_requires_durable_reservation() -> None:
    store = InMemoryInvocationStore()
    invocation_id = uuid4()
    store.begin(
        invocation_id=invocation_id,
        request_id=uuid4(),
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool:github.search",
        input_fingerprint=canonical_fingerprint({"query": "fixture"}),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.search",
        connector_id="github",
    )

    with pytest.raises(InvocationStateError, match="requires a durable reservation"):
        store.fail(
            invocation_id=invocation_id,
            failure_code="invalid_cost",
            failure_detail="fixture",
            committed_usage=UsageVector(tool_calls=1),
        )


def test_model_and_tool_usage_vectors_cannot_cross_domains() -> None:
    model_store = InMemoryInvocationStore()
    model_id = uuid4()
    model_store.begin(
        invocation_id=model_id,
        request_id=uuid4(),
        agent_id="system.router",
        agent_version="1.0.0",
        operation="model-domain-fixture",
        input_fingerprint=canonical_fingerprint({"input": "fixture"}),
        kind=InvocationKind.MODEL,
        effect=InvocationEffect.READ_ONLY,
        provider_id="fake",
        model_id="cheap-fast",
    )
    with pytest.raises(InvocationStateError, match="typed validation"):
        model_store.reserve(
            invocation_id=model_id,
            usage=UsageVector(model_calls=1, tool_calls=1),
        )

    tool_store = InMemoryInvocationStore()
    tool_id = uuid4()
    tool_store.begin(
        invocation_id=tool_id,
        request_id=uuid4(),
        agent_id="github.read",
        agent_version="1.0.0",
        operation="tool-domain-fixture",
        input_fingerprint=canonical_fingerprint({"query": "fixture"}),
        kind=InvocationKind.TOOL,
        effect=InvocationEffect.READ_ONLY,
        tool_id="github.search",
        connector_id="github",
    )
    with pytest.raises(InvocationStateError, match="typed validation"):
        tool_store.reserve(
            invocation_id=tool_id,
            usage=UsageVector(tool_calls=1, input_tokens=10),
        )
