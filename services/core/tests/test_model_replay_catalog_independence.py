from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from simorgh_core.agents.budget import BudgetAccount
from simorgh_core.agents.contracts import ModelTier, TaskBudget, UsageVector
from simorgh_core.agents.invocation_store import SQLiteInvocationStore
from simorgh_core.agents.model_gateway import (
    BudgetedModelGateway,
    BudgetedModelRequest,
    ModelCatalog,
    ModelSpec,
)
from simorgh_core.providers.base import ModelOutput


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
            text="پاسخ پایدار",
            model=model or "model-a",
            provider="fake",
            usage={"input_tokens": 5, "output_tokens": 3},
        )

    async def list_models(self) -> list[str]:
        return []


def _request() -> BudgetedModelRequest:
    return BudgetedModelRequest(
        invocation_id=uuid4(),
        request_id=uuid4(),
        agent_id="seo.planner",
        agent_version="1.0.0",
        operation="catalog-independent-replay",
        input_text="تحلیل سئو",
        instructions="Return concise output",
        allowed_tiers=(ModelTier.FAST,),
        minimum_tier=ModelTier.FAST,
        maximum_output_tokens=100,
        policy_hash="a" * 64,
    )


def _budget(request: BudgetedModelRequest) -> BudgetAccount:
    return BudgetAccount(
        request_id=request.request_id,
        limits=TaskBudget(
            max_model_calls=1,
            max_tool_calls=0,
            max_input_tokens=1000,
            max_output_tokens=100,
            max_estimated_cost_microusd=1_000_000,
            max_elapsed_ms=10_000,
            max_retries=0,
            max_parallel_branches=1,
        ),
        monotonic_millis=lambda: 100,
    )


def test_completed_model_replays_after_old_model_disappears_from_catalog(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invocations.sqlite3"
    request = _request()
    provider = RecordingProvider()
    first_store = SQLiteInvocationStore(path)
    first_gateway = BudgetedModelGateway(
        provider=provider,
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
        invocation_store=first_store,
    )
    first = asyncio.run(first_gateway.generate(request=request, budget=_budget(request)))
    first_store.close()

    replay_store = SQLiteInvocationStore(path)
    replay_gateway = BudgetedModelGateway(
        provider=provider,
        provider_id="fake",
        catalog=ModelCatalog(()),
        invocation_store=replay_store,
    )
    replay_budget = _budget(request)
    replay = asyncio.run(replay_gateway.generate(request=request, budget=replay_budget))

    assert provider.calls == 1
    assert replay.replayed
    assert replay.text == first.text
    assert replay.model_id == "model-a"
    assert replay_budget.snapshot().committed == UsageVector()
    assert replay_budget.snapshot().reserved == UsageVector()
    replay_store.close()
