from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from simorgh_core import __version__
from simorgh_core.agents.api import agent_task_control_plane
from simorgh_core.agents.api import router as agent_task_router
from simorgh_core.agents.context_retention import RetentionAwareSQLiteContextStore
from simorgh_core.agents.context_store import ContextStore, context_store_registry
from simorgh_core.agents.invocation_store import (
    SQLiteInvocationStore,
    invocation_store_registry,
)
from simorgh_core.agents.invocations import InvocationStore
from simorgh_core.agents.live_provider_staging_sqlite_store import (
    SQLiteLiveProviderStagingResultStore,
)
from simorgh_core.agents.live_provider_staging_store import (
    LiveProviderStagingResultStore,
)
from simorgh_core.agents.live_provider_staging_store_registry import (
    live_provider_staging_result_store_registry,
)
from simorgh_core.agents.result_store import (
    ResultStore,
    SQLiteResultStore,
    result_store_registry,
)
from simorgh_core.agents.sqlite_trace_store import SQLiteTraceStore
from simorgh_core.agents.task_store import SQLiteAgentTaskStore
from simorgh_core.agents.trace_projecting_authority_stores import (
    TraceProjectingContextStore,
    TraceProjectingResultStore,
)
from simorgh_core.agents.trace_projecting_invocation_store import (
    TraceProjectingInvocationStore,
)
from simorgh_core.agents.trace_projection import (
    StoreBackedRequestTraceProjector,
    request_trace_projector_registry,
)
from simorgh_core.agents.trace_reconciliation import (
    reconcile_retained_trace_authority,
)
from simorgh_core.agents.trace_retention import (
    RetentionAwareTraceStore,
    StoreBackedTraceProtection,
)
from simorgh_core.agents.trace_store_registry import trace_store_registry
from simorgh_core.agents.usage_recovery import (
    reconcile_task_store_invocation_usage,
)
from simorgh_core.config import Settings, get_settings
from simorgh_core.devices.action_api import OperatorDependency
from simorgh_core.devices.action_api import router as device_action_router
from simorgh_core.devices.action_broker import action_broker
from simorgh_core.devices.action_journal import SQLiteActionJournal
from simorgh_core.devices.gateway import router as device_router
from simorgh_core.devices.observation_refresh_api import (
    router as observation_refresh_router,
)


def _require_distinct_store_paths(settings: Settings) -> None:
    configured = {
        "action_journal": settings.simorgh_action_journal_path,
        "agent_tasks": settings.simorgh_agent_task_store_path,
        "invocations": settings.simorgh_invocation_store_path,
        "results": settings.simorgh_result_store_path,
        "contexts": settings.simorgh_context_store_path,
        "traces": settings.simorgh_trace_store_path,
        "live_provider_staging_results": (
            settings.simorgh_live_provider_staging_result_store_path
        ),
    }
    normalized: dict[str, Path] = {}
    for name, raw_path in configured.items():
        if raw_path == ":memory:":
            continue
        normalized[name] = Path(raw_path).expanduser().resolve()

    items = list(normalized.items())
    for index, (left_name, left_path) in enumerate(items):
        for right_name, right_path in items[index + 1 :]:
            try:
                same_authority = left_path == right_path or (
                    left_path.exists()
                    and right_path.exists()
                    and left_path.samefile(right_path)
                )
            except OSError:
                raise RuntimeError(
                    "Core durable store path identity could not be verified"
                ) from None
            if same_authority:
                raise RuntimeError(
                    "Core durable task, invocation, result, context, trace, "
                    "live-provider staging result, and Android action store paths "
                    f"must be distinct ({left_name}, {right_name})"
                )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    action_journal: SQLiteActionJournal | None = None
    task_store: SQLiteAgentTaskStore | None = None
    invocation_store: InvocationStore | None = None
    result_store: ResultStore | None = None
    context_store: ContextStore | None = None
    staging_result_store: LiveProviderStagingResultStore | None = None
    raw_trace_store: SQLiteTraceStore | None = None
    trace_store: RetentionAwareTraceStore | None = None
    action_journal_configured = False
    task_store_configured = False
    invocation_store_configured = False
    result_store_configured = False
    context_store_configured = False
    staging_result_store_configured = False
    trace_store_configured = False
    trace_projector_configured = False
    try:
        _require_distinct_store_paths(settings)
        # The wrappers are installed while the projector registry is still a no-op.
        # Startup recovery therefore reads durable authority without recursive projection.
        raw_invocation_store = SQLiteInvocationStore(
            settings.simorgh_invocation_store_path,
        )
        invocation_store = TraceProjectingInvocationStore(raw_invocation_store)
        raw_result_store = SQLiteResultStore(settings.simorgh_result_store_path)
        result_store = TraceProjectingResultStore(raw_result_store)
        raw_context_store = RetentionAwareSQLiteContextStore(
            settings.simorgh_context_store_path,
            invocation_store=invocation_store,
            max_terminal_records=(
                settings.simorgh_context_store_max_terminal_records
            ),
        )
        context_store = TraceProjectingContextStore(raw_context_store)
        staging_result_store = SQLiteLiveProviderStagingResultStore(
            settings.simorgh_live_provider_staging_result_store_path,
        )
        action_journal = SQLiteActionJournal(
            settings.simorgh_action_journal_path,
            max_terminal_records=settings.simorgh_action_journal_max_terminal_records,
        )
        task_store = SQLiteAgentTaskStore(
            settings.simorgh_agent_task_store_path,
            max_terminal_records=(
                settings.simorgh_agent_task_store_max_terminal_records
            ),
        )
        reconcile_task_store_invocation_usage(
            task_store=task_store,
            invocation_records=invocation_store.load(),
        )
        raw_trace_store = SQLiteTraceStore(settings.simorgh_trace_store_path)
        reconcile_retained_trace_authority(
            store=raw_trace_store,
            task_entries=task_store.load(),
            invocation_records=invocation_store.load(),
            context_bundles=context_store.load(),
            result_records=result_store.load(),
            base_ingested_at_ms=int(time.time() * 1_000),
        )
        trace_store = RetentionAwareTraceStore(
            raw_trace_store,
            protection=StoreBackedTraceProtection(
                task_store=task_store,
                invocation_store=invocation_store,
            ),
            max_terminal_records=(
                settings.simorgh_trace_store_max_terminal_records
            ),
        )
        raw_trace_store = None
        trace_store.prune_terminal()
        await action_broker.configure_journal(
            action_journal,
            max_terminal_actions=settings.simorgh_action_journal_max_terminal_records,
        )
        action_journal_configured = True
        await agent_task_control_plane.configure_store(task_store)
        task_store_configured = True
        await agent_task_control_plane.configure_invocation_store(
            invocation_store
        )
        invocation_store_registry.configure(invocation_store)
        invocation_store_configured = True
        result_store_registry.configure(result_store)
        result_store_configured = True
        context_store_registry.configure(context_store)
        context_store_configured = True
        trace_store_registry.configure(trace_store)
        trace_store_configured = True
        live_provider_staging_result_store_registry.configure(
            staging_result_store
        )
        staging_result_store_configured = True
        request_trace_projector_registry.configure(
            StoreBackedRequestTraceProjector(
                task_store=task_store,
                invocation_store=invocation_store,
                context_store=context_store,
                result_store=result_store,
                trace_store=trace_store,
            )
        )
        trace_projector_configured = True
    except BaseException:
        if trace_projector_configured:
            request_trace_projector_registry.reset_to_null()
        if staging_result_store_configured:
            live_provider_staging_result_store_registry.reset_to_memory()
        elif staging_result_store is not None:
            staging_result_store.close()
        if trace_store_configured:
            trace_store_registry.reset_to_memory()
        elif trace_store is not None:
            trace_store.close()
        elif raw_trace_store is not None:
            raw_trace_store.close()
        if context_store_configured:
            context_store_registry.reset_to_memory()
        elif context_store is not None:
            context_store.close()
        if result_store_configured:
            result_store_registry.reset_to_memory()
        elif result_store is not None:
            result_store.close()
        if invocation_store_configured:
            invocation_store_registry.reset_to_memory()
        elif invocation_store is not None:
            invocation_store.close()
        if task_store_configured:
            await agent_task_control_plane.reset_to_memory_store()
        elif task_store is not None:
            task_store.close()
        if action_journal_configured:
            await action_broker.reset_to_memory_journal()
        elif action_journal is not None:
            action_journal.close()
        raise

    try:
        yield
    finally:
        try:
            request_trace_projector_registry.reset_to_null()
        finally:
            try:
                live_provider_staging_result_store_registry.reset_to_memory()
            finally:
                try:
                    trace_store_registry.reset_to_memory()
                finally:
                    try:
                        context_store_registry.reset_to_memory()
                    finally:
                        try:
                            result_store_registry.reset_to_memory()
                        finally:
                            try:
                                invocation_store_registry.reset_to_memory()
                            finally:
                                try:
                                    await agent_task_control_plane.reset_to_memory_store()
                                finally:
                                    await action_broker.reset_to_memory_journal()


app = FastAPI(
    title="Simorgh Core API",
    version=__version__,
    description="Core orchestration API for the Simorgh personal agent operating system.",
    lifespan=lifespan,
)
app.include_router(device_router)
app.include_router(device_action_router)
app.include_router(observation_refresh_router)
app.include_router(agent_task_router)

SettingsDependency = Annotated[Settings, Depends(get_settings)]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    environment: str
    model_gateway_configured: bool
    device_gateway_configured: bool
    operator_gateway_configured: bool


class TextGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, max_length=100_000)
    instructions: str | None = Field(default=None, max_length=20_000)
    model: str | None = None


@app.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDependency) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.simorgh_env,
        model_gateway_configured=settings.has_model_credentials,
        device_gateway_configured=settings.has_device_gateway_credentials,
        operator_gateway_configured=settings.has_operator_credentials,
    )


@app.post("/v1/model/text", status_code=status.HTTP_410_GONE)
async def generate_text_disabled(
    payload: TextGenerationRequest,
    _: OperatorDependency,
) -> None:
    del payload
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "ungoverned_model_endpoint_disabled",
            "message": (
                "Direct model generation is disabled until it is bound to an explicit "
                "model catalog, durable invocation identity, and pre-reserved cost budget."
            ),
        },
    )
