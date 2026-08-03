from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocation_store import invocation_store_registry
from simorgh_core.agents.live_provider_staging import (
    LiveProviderPreflightError,
    LiveProviderStagingService,
)
from simorgh_core.agents.live_provider_staging_artifact import (
    LiveProviderExternalCallCounts,
    LiveProviderStagingArtifact,
    LiveProviderStagingArtifactDisposition,
    LiveProviderStagingArtifactError,
    LiveProviderStagingArtifactFailureCode,
    new_live_provider_staging_artifact,
    verify_live_provider_staging_artifact,
    write_live_provider_staging_artifact,
)
from simorgh_core.agents.live_provider_staging_contracts import (
    AVALAI_API_BASE_URL,
    AVALAI_USER_API_BASE_URL,
    LiveProviderModelPricing,
    LiveProviderReconciliationDisposition,
    LiveProviderStagingDisposition,
    LiveProviderStagingPolicy,
    LiveProviderStagingRequest,
    LiveProviderStagingResult,
)
from simorgh_core.agents.live_provider_staging_store_registry import (
    live_provider_staging_result_store_registry,
)
from simorgh_core.agents.live_provider_staging_trace import (
    LiveProviderStagingTraceEvidence,
    live_provider_staging_trace_evidence,
)
from simorgh_core.agents.trace_store_registry import trace_store_registry
from simorgh_core.app import app, lifespan
from simorgh_core.config import Settings, get_settings
from simorgh_core.providers.avalai import AvalAIProvider
from simorgh_core.providers.avalai_user_api import (
    AvalAICreditSummary,
    AvalAITransactionLookupResult,
    AvalAIUserAPI,
    HttpAvalAIUserAPI,
)
from simorgh_core.providers.base import ModelOutput, ModelProvider

_REVIEWED_MODEL_IDS = ("gpt-5.4-mini",)
_CONSERVATIVE_INPUT_PRICE_MICROUSD_PER_MILLION = 100_000_000
_CONSERVATIVE_OUTPUT_PRICE_MICROUSD_PER_MILLION = 100_000_000


class CountingModelProvider:
    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider
        self.model_catalog_calls = 0
        self.model_generate_calls = 0

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        self.model_generate_calls += 1
        return await self._provider.generate_text(
            input_text=input_text,
            model=model,
            instructions=instructions,
            max_output_tokens=max_output_tokens,
        )

    async def list_models(self) -> list[str]:
        self.model_catalog_calls += 1
        return await self._provider.list_models()


class CountingAvalAIUserAPI:
    def __init__(self, user_api: AvalAIUserAPI) -> None:
        self._user_api = user_api
        self.credit_calls = 0
        self.transaction_lookup_calls = 0

    async def get_credit(self) -> AvalAICreditSummary:
        self.credit_calls += 1
        return await self._user_api.get_credit()

    async def lookup_transaction(
        self,
        transaction_id: UUID,
    ) -> AvalAITransactionLookupResult:
        self.transaction_lookup_calls += 1
        return await self._user_api.lookup_transaction(transaction_id)


def reviewed_live_provider_staging_policy(
    model_id: str,
) -> LiveProviderStagingPolicy:
    if model_id not in _REVIEWED_MODEL_IDS:
        raise LiveProviderStagingArtifactError(
            "requested staging model is outside reviewed allowlist"
        )
    return LiveProviderStagingPolicy(
        enabled=True,
        allowed_model_ids=_REVIEWED_MODEL_IDS,
        selected_model_id=model_id,
        max_model_calls=1,
        max_input_tokens=128,
        max_output_tokens=16,
        max_estimated_cost_microusd=20_000,
        minimum_credit_floor_unit=Decimal("0.10"),
        max_exact_cost_unit=Decimal("0.01"),
        max_elapsed_ms=60_000,
        transaction_poll_attempts=6,
        transaction_poll_interval_ms=5_000,
        user_api_timeout_ms=10_000,
        user_api_max_response_bytes=256_000,
    )


def reviewed_live_provider_staging_pricing(
    model_id: str,
) -> LiveProviderModelPricing:
    if model_id not in _REVIEWED_MODEL_IDS:
        raise LiveProviderStagingArtifactError(
            "requested staging model is outside reviewed pricing"
        )
    return LiveProviderModelPricing(
        model_id=model_id,
        transaction_provider_id="openai",
        input_price_microusd_per_million_tokens=(
            _CONSERVATIVE_INPUT_PRICE_MICROUSD_PER_MILLION
        ),
        output_price_microusd_per_million_tokens=(
            _CONSERVATIVE_OUTPUT_PRICE_MICROUSD_PER_MILLION
        ),
        maximum_output_tokens=16,
    )


def _call_counts(
    provider: CountingModelProvider,
    user_api: CountingAvalAIUserAPI,
) -> LiveProviderExternalCallCounts:
    return LiveProviderExternalCallCounts(
        model_catalog_calls=provider.model_catalog_calls,
        model_generate_calls=provider.model_generate_calls,
        credit_calls=user_api.credit_calls,
        transaction_lookup_calls=user_api.transaction_lookup_calls,
    )


async def execute_manual_live_provider_staging(
    *,
    policy: LiveProviderStagingPolicy,
    pricing: LiveProviderModelPricing,
    provider: ModelProvider,
    user_api: AvalAIUserAPI,
    source_commit_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    wall_clock_millis: Callable[[], int] | None = None,
    monotonic_millis: Callable[[], int] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    id_factory: Callable[[], UUID] = uuid4,
) -> LiveProviderStagingArtifact:
    now = wall_clock_millis or (lambda: int(time.time() * 1_000))
    monotonic = monotonic_millis or (lambda: int(time.monotonic() * 1_000))
    request = LiveProviderStagingRequest(
        staging_run_id=id_factory(),
        request_id=id_factory(),
        invocation_id=id_factory(),
        manual_approval=True,
    )
    counted_provider = CountingModelProvider(provider)
    counted_user_api = CountingAvalAIUserAPI(user_api)
    first_calls = LiveProviderExternalCallCounts()
    first_calls_captured = False
    replay_delta = LiveProviderExternalCallCounts()
    usage_before = UsageVector()
    usage_after = UsageVector()
    result: LiveProviderStagingResult | None = None
    trace_evidence: LiveProviderStagingTraceEvidence | None = None
    replay_observed = False
    replay_result_sha256: str | None = None
    failure_code = LiveProviderStagingArtifactFailureCode.EXECUTION_FAILED

    try:
        async with lifespan(app):
            invocations = invocation_store_registry.current()
            results = live_provider_staging_result_store_registry.current()
            traces = trace_store_registry.current()
            service = LiveProviderStagingService(
                policy=policy,
                pricing=pricing,
                provider=counted_provider,
                user_api=counted_user_api,
                invocation_store=invocations,
                result_store=results,
                wall_clock_millis=now,
                monotonic_millis=monotonic,
                sleep=sleep,
            )
            try:
                result = await service.run(request)
            except LiveProviderPreflightError:
                failure_code = LiveProviderStagingArtifactFailureCode.PREFLIGHT_FAILED
            except BaseException:
                failure_code = LiveProviderStagingArtifactFailureCode.EXECUTION_FAILED
            else:
                first_calls = _call_counts(counted_provider, counted_user_api)
                first_calls_captured = True
                try:
                    usage_before = invocations.get(
                        request.invocation_id
                    ).committed_usage
                    trace_evidence = live_provider_staging_trace_evidence(
                        result,
                        invocation_store=invocations,
                        trace_store=traces,
                    )
                except Exception:
                    failure_code = LiveProviderStagingArtifactFailureCode.TRACE_INVALID
                else:
                    before_replay = _call_counts(
                        counted_provider,
                        counted_user_api,
                    )
                    try:
                        replay = await service.run(request)
                        usage_after = invocations.get(
                            request.invocation_id
                        ).committed_usage
                    except BaseException:
                        failure_code = (
                            LiveProviderStagingArtifactFailureCode.REPLAY_FAILED
                        )
                    else:
                        replay_observed = replay.replayed
                        replay_result_sha256 = replay.canonical_sha256
                        replay_delta = _call_counts(
                            counted_provider,
                            counted_user_api,
                        ).minus(before_replay)
                        if (
                            result.disposition
                            == LiveProviderStagingDisposition.COMPLETED
                            and result.reconciliation_disposition
                            == LiveProviderReconciliationDisposition.EXACT
                            and replay_observed
                            and replay_result_sha256 == result.canonical_sha256
                            and replay_delta == LiveProviderExternalCallCounts()
                            and usage_before == usage_after
                        ):
                            failure_code = LiveProviderStagingArtifactFailureCode.NONE
                        else:
                            failure_code = (
                                LiveProviderStagingArtifactFailureCode.RESULT_INCOMPLETE
                            )
    except BaseException:
        failure_code = LiveProviderStagingArtifactFailureCode.EXECUTION_FAILED

    if not first_calls_captured:
        first_calls = _call_counts(counted_provider, counted_user_api)
    artifact_disposition = (
        LiveProviderStagingArtifactDisposition.PASSED
        if failure_code == LiveProviderStagingArtifactFailureCode.NONE
        else LiveProviderStagingArtifactDisposition.FAILED
    )
    return new_live_provider_staging_artifact(
        source_commit_sha=source_commit_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        generated_at_ms=now(),
        staging_run_id=request.staging_run_id,
        request_id=request.request_id,
        invocation_id=request.invocation_id,
        disposition=artifact_disposition,
        failure_code=failure_code,
        result=result,
        trace_evidence=trace_evidence,
        first_run_calls=first_calls,
        replay_delta_calls=replay_delta,
        usage_before_replay=usage_before,
        usage_after_replay=usage_after,
        replay_observed=replay_observed,
        replay_result_sha256=replay_result_sha256,
    )


def _require_exact_live_settings(settings: Settings, model_id: str) -> None:
    if settings.avalai_base_url != AVALAI_API_BASE_URL:
        raise LiveProviderStagingArtifactError(
            "AvalAI API base URL is outside reviewed allowlist"
        )
    if settings.avalai_user_api_base_url != AVALAI_USER_API_BASE_URL:
        raise LiveProviderStagingArtifactError(
            "AvalAI User API base URL is outside reviewed allowlist"
        )
    if settings.avalai_default_model != model_id:
        raise LiveProviderStagingArtifactError(
            "configured model does not match reviewed staging model"
        )
    if settings.avalai_api_key is None or not settings.has_model_credentials:
        raise LiveProviderStagingArtifactError(
            "protected AvalAI credential is unavailable"
        )


async def _run_command(arguments: argparse.Namespace) -> int:
    settings = get_settings()
    _require_exact_live_settings(settings, arguments.model_id)
    api_key = settings.avalai_api_key
    if api_key is None:
        raise LiveProviderStagingArtifactError(
            "protected AvalAI credential is unavailable"
        )
    policy = reviewed_live_provider_staging_policy(arguments.model_id)
    pricing = reviewed_live_provider_staging_pricing(arguments.model_id)
    provider = AvalAIProvider(settings)
    user_api = HttpAvalAIUserAPI(
        api_key=api_key,
        base_url=settings.avalai_user_api_base_url,
        timeout_ms=policy.user_api_timeout_ms,
        max_response_bytes=policy.user_api_max_response_bytes,
    )
    artifact: LiveProviderStagingArtifact
    try:
        artifact = await execute_manual_live_provider_staging(
            policy=policy,
            pricing=pricing,
            provider=provider,
            user_api=user_api,
            source_commit_sha=arguments.source_commit_sha,
            workflow_run_id=arguments.workflow_run_id,
            workflow_run_attempt=arguments.workflow_run_attempt,
        )
        write_live_provider_staging_artifact(
            arguments.output,
            artifact,
            forbidden_values=(api_key.get_secret_value(),),
        )
    finally:
        await user_api.close()
        await provider.close()
    return (
        0
        if artifact.disposition == LiveProviderStagingArtifactDisposition.PASSED
        else 2
    )


def _verify_command(arguments: argparse.Namespace) -> int:
    artifact = verify_live_provider_staging_artifact(arguments.artifact)
    if (
        arguments.require_passed
        and artifact.disposition != LiveProviderStagingArtifactDisposition.PASSED
    ):
        return 2
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simorgh-live-provider-staging",
        description="Protected one-call Phase 1.9 staging boundary.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run")
    run.add_argument("--source-commit-sha", required=True)
    run.add_argument("--workflow-run-id", required=True, type=int)
    run.add_argument("--workflow-run-attempt", required=True, type=int)
    run.add_argument("--model-id", required=True, choices=_REVIEWED_MODEL_IDS)
    run.add_argument("--output", required=True, type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--artifact", required=True, type=Path)
    verify.add_argument("--require-passed", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "run":
            return asyncio.run(_run_command(arguments))
        return _verify_command(arguments)
    except (LiveProviderStagingArtifactError, ValueError):
        print("live-provider staging command failed safely", file=sys.stderr)
        return 1
    except BaseException:
        print("live-provider staging command failed safely", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CountingAvalAIUserAPI",
    "CountingModelProvider",
    "execute_manual_live_provider_staging",
    "main",
    "reviewed_live_provider_staging_policy",
    "reviewed_live_provider_staging_pricing",
]
