from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import ModelTier, TaskBudget
from simorgh_core.agents.invocations import InMemoryInvocationStore
from simorgh_core.agents.model_gateway import (
    BudgetedModelGateway,
    BudgetedModelRequest,
    ModelCatalog,
    ModelGatewayError,
    ModelInvocationTerminalError,
    ModelOutputContractError,
    ModelSpec,
)
from simorgh_core.agents.tracing import InMemoryTraceSink, TraceEventKind
from simorgh_core.providers.base import ModelOutput


class RecordingProvider:
    def __init__(
        self,
        *,
        output: ModelOutput | None = None,
        error: Exception | None = None,
        before_return: Callable[[], None] | None = None,
    ) -> None:
        self.output = output or ModelOutput(
            text="ok",
            model="cheap-fast",
            provider="fake",
            request_id="provider-request-1",
            usage={"input_tokens": 12, "output_tokens": 4},
        )
        self.error = error
        self.before_return = before_return
        self.calls = 0
        self.models: list[str | None] = []
        self.output_limits: list[int | None] = []

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        del input_text, instructions
        self.calls += 1
        self.models.append(model)
        self.output_limits.append(max_output_tokens)
        if self.before_return is not None:
            self.before_return()
        if self.error is not None:
            raise self.error
        return self.output

    async def list_models(self) -> list[str]:
        return ["cheap-fast", "expensive-fast", "general"]


def _catalog() -> ModelCatalog:
    return ModelCatalog(
        (
            ModelSpec(
                provider_id="fake",
                model_id="expensive-fast",
                tier=ModelTier.FAST,
                input_price_microusd_per_million_tokens=5_000_000,
                output_price_microusd_per_million_tokens=10_000_000,
                maximum_output_tokens=1_000,
            ),
            ModelSpec(
                provider_id="fake",
                model_id="cheap-fast",
                tier=ModelTier.FAST,
                input_price_microusd_per_million_tokens=1_000_000,
                output_price_microusd_per_million_tokens=2_000_000,
                maximum_output_tokens=500,
            ),
            ModelSpec(
                provider_id="fake",
                model_id="general",
                tier=ModelTier.GENERAL,
                input_price_microusd_per_million_tokens=500_000,
                output_price_microusd_per_million_tokens=500_000,
                maximum_output_tokens=2_000,
            ),
        )
    )


def _request(invocation_id=None) -> BudgetedModelRequest:
    return BudgetedModelRequest(
        invocation_id=invocation_id or uuid4(),
        request_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        operation="classify",
        input_text="تحلیل سئوی سایت",
        instructions="Return JSON",
        allowed_tiers=(ModelTier.FAST, ModelTier.GENERAL),
        minimum_tier=ModelTier.FAST,
        maximum_output_tokens=200,
        policy_hash="a" * 64,
    )


def _budget(request: BudgetedModelRequest) -> BudgetAccount:
    return BudgetAccount(
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


def test_gateway_reserves_before_provider_and_selects_cheapest_sufficient_model() -> None:
    request = _request()
    budget = _budget(request)

    def assert_reserved() -> None:
        snapshot = budget.snapshot()
        assert snapshot.reserved.model_calls == 1
        assert snapshot.committed.model_calls == 0

    provider = RecordingProvider(before_return=assert_reserved)
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=InMemoryInvocationStore(),
    )

    result = asyncio.run(gateway.generate(request=request, budget=budget))

    assert provider.calls == 1
    assert provider.models == ["cheap-fast"]
    assert provider.output_limits == [200]
    assert result.model_id == "cheap-fast"
    assert result.input_tokens == 12
    assert result.output_tokens == 4
    snapshot = budget.snapshot()
    assert snapshot.reserved.model_calls == 0
    assert snapshot.committed.model_calls == 1
    assert snapshot.committed.input_tokens == 12
    assert snapshot.committed.output_tokens == 4


def test_model_trace_records_cost_without_prompt_or_output_content() -> None:
    request = _request()
    trace_sink = InMemoryTraceSink()
    gateway = BudgetedModelGateway(
        provider=RecordingProvider(),
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=InMemoryInvocationStore(),
        trace_sink=trace_sink,
    )

    result = asyncio.run(gateway.generate(request=request, budget=_budget(request)))
    events = trace_sink.for_request(request.request_id)

    assert [event.kind for event in events] == [
        TraceEventKind.BUDGET_RESERVED,
        TraceEventKind.MODEL_STARTED,
        TraceEventKind.BUDGET_RECONCILED,
        TraceEventKind.MODEL_COMPLETED,
    ]
    assert events[-1].usage.model_calls == 1
    assert events[-1].usage.input_tokens == result.input_tokens
    assert events[-1].usage.output_tokens == result.output_tokens
    assert events[-1].usage.estimated_cost_microusd == result.cost_microusd
    encoded = "\n".join(event.model_dump_json() for event in events)
    assert request.input_text not in encoded
    assert request.instructions not in encoded
    assert result.text not in encoded


def test_exact_retry_replays_completed_model_result_without_provider_cost() -> None:
    request = _request()
    provider = RecordingProvider()
    store = InMemoryInvocationStore()
    trace_sink = InMemoryTraceSink()
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
        trace_sink=trace_sink,
    )
    budget = _budget(request)

    first = asyncio.run(gateway.generate(request=request, budget=budget))
    replay = asyncio.run(gateway.generate(request=request, budget=budget))

    assert provider.calls == 1
    assert not first.replayed
    assert replay.replayed
    assert replay.text == first.text
    assert budget.snapshot().committed.model_calls == 1
    assert trace_sink.for_request(request.request_id)[-1].kind == (
        TraceEventKind.INVOCATION_REPLAYED
    )
    assert trace_sink.for_request(request.request_id)[-1].usage.model_calls == 0


def test_provider_transport_failure_commits_conservative_reservation_once() -> None:
    request = _request()
    provider = RecordingProvider(error=TimeoutError("provider timeout"))
    store = InMemoryInvocationStore()
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
    )
    budget = _budget(request)

    with pytest.raises(ModelGatewayError, match="provider invocation failed"):
        asyncio.run(gateway.generate(request=request, budget=budget))

    assert provider.calls == 1
    snapshot = budget.snapshot()
    assert snapshot.committed.model_calls == 1
    assert snapshot.committed.input_tokens > 0
    assert snapshot.committed.output_tokens == 200

    with pytest.raises(ModelInvocationTerminalError):
        asyncio.run(gateway.generate(request=request, budget=budget))
    assert provider.calls == 1


def test_provider_identity_mismatch_is_charged_but_never_accepted() -> None:
    request = _request()
    provider = RecordingProvider(
        output=ModelOutput(
            text="untrusted output",
            model="cheap-fast",
            provider="unexpected-provider",
            usage={"input_tokens": 12, "output_tokens": 4},
        )
    )
    store = InMemoryInvocationStore()
    budget = _budget(request)
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
    )

    with pytest.raises(ModelOutputContractError, match="provider identity"):
        asyncio.run(gateway.generate(request=request, budget=budget))

    assert provider.calls == 1
    assert budget.snapshot().committed.model_calls == 1
    with pytest.raises(ModelInvocationTerminalError):
        asyncio.run(gateway.generate(request=request, budget=budget))
    assert provider.calls == 1


def test_minimum_general_tier_skips_cheaper_fast_models() -> None:
    request = _request().model_copy(
        update={
            "allowed_tiers": (ModelTier.FAST, ModelTier.GENERAL),
            "minimum_tier": ModelTier.GENERAL,
        }
    )
    provider = RecordingProvider(
        output=ModelOutput(
            text="general output",
            model="general",
            provider="fake",
            usage={"input_tokens": 10, "output_tokens": 2},
        )
    )
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=InMemoryInvocationStore(),
    )

    result = asyncio.run(gateway.generate(request=request, budget=_budget(request)))

    assert provider.models == ["general"]
    assert result.model_id == "general"
