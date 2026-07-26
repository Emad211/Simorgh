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
    InvocationPhase,
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


class CancelledProvider:
    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        del input_text, model, instructions, max_output_tokens
        raise asyncio.CancelledError

    async def list_models(self) -> list[str]:
        return ["model-a"]


class CancelledInvoker:
    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del tool_id, arguments
        raise asyncio.CancelledError


class RecordingProvider:
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
        del input_text, instructions, max_output_tokens
        self.calls += 1
        return ModelOutput(
            text="پاسخ",
            model=model or "model-a",
            provider="fake",
            usage={"input_tokens": 5, "output_tokens": 3},
        )

    async def list_models(self) -> list[str]:
        return ["model-a"]


class RecordingInvoker:
    def __init__(self) -> None:
        self.calls = 0

    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls += 1
        return {"tool_id": tool_id, "query": arguments.get("query")}


class UnknownFailingStore(InMemoryInvocationStore):
    def mark_unknown(
        self,
        *,
        invocation_id: UUID,
        failure_code: str,
        failure_detail: str,
    ) -> InvocationRecord:
        del invocation_id, failure_code, failure_detail
        raise InvocationStoreCorruptionError("PRIVATE_STORE_UNKNOWN_FAILURE")


class CompleteFailingStore(InMemoryInvocationStore):
    def complete(
        self,
        *,
        invocation_id: UUID,
        result_payload: dict[str, Any],
        committed_usage: UsageVector | None = None,
    ) -> InvocationRecord:
        del invocation_id, result_payload, committed_usage
        raise InvocationStoreCorruptionError("PRIVATE_STORE_COMPLETE_FAILURE")


def _catalog() -> ModelCatalog:
    return ModelCatalog((
        ModelSpec(
            provider_id="fake",
            model_id="model-a",
            tier=ModelTier.FAST,
            input_price_microusd_per_million_tokens=1,
            output_price_microusd_per_million_tokens=1,
            maximum_output_tokens=100,
        ),
    ))


def _model_request() -> BudgetedModelRequest:
    return BudgetedModelRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        operation="rc3-model-fixture",
        input_text="تحلیل",
        allowed_tiers=(ModelTier.FAST,),
        minimum_tier=ModelTier.FAST,
        maximum_output_tokens=100,
        policy_hash="a" * 64,
    )


def _model_budget(request: BudgetedModelRequest) -> BudgetAccount:
    return BudgetAccount(
        request_id=request.request_id,
        limits=TaskBudget(max_model_calls=1, max_output_tokens=100),
        monotonic_millis=lambda: 100,
    )


def _tool_request() -> ToolCallRequest:
    return ToolCallRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="github.read",
        agent_version="1.0.0",
        tool_id="github.search",
        connector_id="github",
        allowed_data_sources=frozenset({"github"}),
        arguments={"query": "Simorgh"},
    )


def _tool_budget(request: ToolCallRequest) -> BudgetAccount:
    return BudgetAccount(
        request_id=request.request_id,
        limits=TaskBudget(max_model_calls=0, max_tool_calls=1),
        monotonic_millis=lambda: 100,
    )


def test_model_cancelled_error_survives_uncertainty_store_failure() -> None:
    request = _model_request()
    budget = _model_budget(request)
    store = UnknownFailingStore()
    gateway = BudgetedModelGateway(
        provider=CancelledProvider(),
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(gateway.generate(request=request, budget=budget))
    assert budget.snapshot().committed.model_calls == 1
    assert store.get(request.invocation_id).state == InvocationPhase.RESERVED


def test_tool_cancelled_error_survives_uncertainty_store_failure() -> None:
    request = _tool_request()
    budget = _tool_budget(request)
    store = UnknownFailingStore()
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=CancelledInvoker(),
        invocation_store=store,
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(gateway.invoke(request=request, budget=budget))
    assert budget.snapshot().committed.tool_calls == 1
    assert store.get(request.invocation_id).state == InvocationPhase.RESERVED


def test_model_result_store_failure_reports_commit_failure() -> None:
    request = _model_request()
    budget = _model_budget(request)
    provider = RecordingProvider()
    store = CompleteFailingStore()
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
    )
    with pytest.raises(
        ModelGatewayError,
        match="model result could not be durably committed",
    ) as raised:
        asyncio.run(gateway.generate(request=request, budget=budget))
    assert provider.calls == 1
    assert budget.snapshot().committed.model_calls == 1
    assert budget.snapshot().reserved == UsageVector()
    assert store.get(request.invocation_id).state == InvocationPhase.RESERVED
    assert "PRIVATE_STORE_COMPLETE_FAILURE" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_tool_result_store_failure_reports_commit_failure() -> None:
    request = _tool_request()
    budget = _tool_budget(request)
    invoker = RecordingInvoker()
    store = CompleteFailingStore()
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=store,
    )
    with pytest.raises(
        ToolGatewayError,
        match="tool result could not be durably committed",
    ) as raised:
        asyncio.run(gateway.invoke(request=request, budget=budget))
    assert invoker.calls == 1
    assert budget.snapshot().committed.tool_calls == 1
    assert budget.snapshot().reserved == UsageVector()
    assert store.get(request.invocation_id).state == InvocationPhase.RESERVED
    assert "PRIVATE_STORE_COMPLETE_FAILURE" not in str(raised.value)
    assert raised.value.__cause__ is None
