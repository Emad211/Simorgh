from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import ModelTier, TaskBudget, UsageVector
from simorgh_core.agents.defaults import default_specialist_registry
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.invocations import InvocationPhase
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
from simorgh_core.agents.tracing import InMemoryTraceSink
from simorgh_core.providers.base import ModelOutput


class DurableRecordingProvider:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        before_return: Callable[[], None] | None = None,
    ) -> None:
        self.error = error
        self.before_return = before_return
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
        if self.before_return is not None:
            self.before_return()
        if self.error is not None:
            raise self.error
        return ModelOutput(
            text="پاسخ پایدار",
            model=model or "cheap-fast",
            provider="fake",
            request_id="provider-request-durable",
            usage={"input_tokens": 12, "output_tokens": 4},
        )

    async def list_models(self) -> list[str]:
        return ["cheap-fast"]


class DurableRecordingInvoker:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        before_return: Callable[[], None] | None = None,
    ) -> None:
        self.error = error
        self.before_return = before_return
        self.calls = 0

    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls += 1
        if self.before_return is not None:
            self.before_return()
        if self.error is not None:
            raise self.error
        return {
            "tool_id": tool_id,
            "query": arguments.get("query"),
            "repository": "Emad211/Simorgh",
        }


def _catalog() -> ModelCatalog:
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


def _model_request() -> BudgetedModelRequest:
    return BudgetedModelRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        operation="durable-model-fixture",
        input_text="تحلیل پایدار سئو",
        instructions="Return a concise result",
        allowed_tiers=(ModelTier.FAST,),
        minimum_tier=ModelTier.FAST,
        maximum_output_tokens=200,
        policy_hash="a" * 64,
    )


def _model_budget(request: BudgetedModelRequest) -> BudgetAccount:
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


def test_completed_model_replays_after_sqlite_reopen_without_provider_or_budget(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    request = _model_request()
    provider = DurableRecordingProvider()
    first_store = SQLiteInvocationStore(path)
    first_gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=first_store,
    )
    first_budget = _model_budget(request)

    first = asyncio.run(first_gateway.generate(request=request, budget=first_budget))
    first_record = first_store.get(request.invocation_id)
    first_store.close()

    replay_store = SQLiteInvocationStore(path)
    replay_gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=replay_store,
    )
    replay_budget = _model_budget(request)
    replay = asyncio.run(
        replay_gateway.generate(request=request, budget=replay_budget)
    )

    assert provider.calls == 1
    assert not first.replayed
    assert replay.replayed
    assert replay.text == first.text
    assert replay.model_dump(exclude={"replayed"}) == first.model_dump(
        exclude={"replayed"}
    )
    assert replay_budget.snapshot().committed == UsageVector()
    assert replay_budget.snapshot().reserved == UsageVector()
    assert replay_store.get(request.invocation_id) == first_record
    replay_store.close()


def test_completed_tool_replays_after_sqlite_reopen_without_invoker_or_budget(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    request = _tool_request()
    invoker = DurableRecordingInvoker()
    first_store = SQLiteInvocationStore(path)
    first_gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=first_store,
    )
    first_budget = _tool_budget(request)

    first = asyncio.run(first_gateway.invoke(request=request, budget=first_budget))
    first_record = first_store.get(request.invocation_id)
    first_store.close()

    replay_store = SQLiteInvocationStore(path)
    replay_gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=replay_store,
    )
    replay_budget = _tool_budget(request)
    replay = asyncio.run(
        replay_gateway.invoke(request=request, budget=replay_budget)
    )

    assert invoker.calls == 1
    assert not first.replayed
    assert replay.replayed
    assert replay.payload == first.payload
    assert replay_budget.snapshot().committed == UsageVector()
    assert replay_budget.snapshot().reserved == UsageVector()
    assert replay_store.get(request.invocation_id) == first_record
    replay_store.close()


def test_model_reservation_is_durable_before_provider_receives_call(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    request = _model_request()
    store = SQLiteInvocationStore(path)

    def assert_durable_reservation() -> None:
        record = store.get(request.invocation_id)
        assert record.state == InvocationPhase.RESERVED
        assert record.reserved_usage.model_calls == 1
        assert record.committed_usage == UsageVector()

    provider = DurableRecordingProvider(before_return=assert_durable_reservation)
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
    )

    asyncio.run(gateway.generate(request=request, budget=_model_budget(request)))
    assert provider.calls == 1
    store.close()


def test_tool_reservation_is_durable_before_invoker_receives_call(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    request = _tool_request()
    store = SQLiteInvocationStore(path)

    def assert_durable_reservation() -> None:
        record = store.get(request.invocation_id)
        assert record.state == InvocationPhase.RESERVED
        assert record.reserved_usage.tool_calls == 1
        assert record.committed_usage == UsageVector()

    invoker = DurableRecordingInvoker(before_return=assert_durable_reservation)
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=store,
    )

    asyncio.run(gateway.invoke(request=request, budget=_tool_budget(request)))
    assert invoker.calls == 1
    store.close()


def test_provider_exception_text_is_not_persisted_or_traced(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    private_marker = "PRIVATE_PROMPT_78a77e"
    request = _model_request()
    store = SQLiteInvocationStore(path)
    traces = InMemoryTraceSink()
    provider = DurableRecordingProvider(
        error=RuntimeError(f"upstream failed near {private_marker}")
    )
    gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=_catalog(),
        invocation_store=store,
        trace_sink=traces,
    )

    with pytest.raises(ModelGatewayError, match="provider invocation failed"):
        asyncio.run(gateway.generate(request=request, budget=_model_budget(request)))

    record = store.get(request.invocation_id)
    assert record.failure_detail == "RuntimeError"
    encoded = record.model_dump_json() + "\n" + "\n".join(
        event.model_dump_json() for event in traces.for_request(request.request_id)
    )
    assert private_marker not in encoded
    store.close()


def test_tool_exception_text_is_not_persisted_or_traced(tmp_path: Path) -> None:
    path = tmp_path / "invocations.sqlite3"
    private_marker = "PRIVATE_ARGUMENT_a1ff92"
    request = _tool_request()
    store = SQLiteInvocationStore(path)
    traces = InMemoryTraceSink()
    invoker = DurableRecordingInvoker(
        error=RuntimeError(f"connector exposed {private_marker}")
    )
    gateway = BudgetedToolGateway(
        registry=default_specialist_registry(),
        invoker=invoker,
        invocation_store=store,
        trace_sink=traces,
    )

    with pytest.raises(ToolGatewayError, match="structured tool invocation failed"):
        asyncio.run(gateway.invoke(request=request, budget=_tool_budget(request)))

    record = store.get(request.invocation_id)
    assert record.failure_detail == "RuntimeError"
    encoded = record.model_dump_json() + "\n" + "\n".join(
        event.model_dump_json() for event in traces.for_request(request.request_id)
    )
    assert private_marker not in encoded
    store.close()
