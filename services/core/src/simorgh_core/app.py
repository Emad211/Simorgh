from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from simorgh_core import __version__
from simorgh_core.agents.api import (
    agent_task_control_plane,
    router as agent_task_router,
)
from simorgh_core.agents.task_store import SQLiteAgentTaskStore
from simorgh_core.config import Settings, get_settings
from simorgh_core.devices.action_api import router as device_action_router
from simorgh_core.devices.action_broker import action_broker
from simorgh_core.devices.action_journal import SQLiteActionJournal
from simorgh_core.devices.gateway import router as device_router
from simorgh_core.devices.observation_refresh_api import (
    router as observation_refresh_router,
)
from simorgh_core.providers.avalai import AvalAIProvider, MissingAvalAICredentialsError


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    action_journal = SQLiteActionJournal(
        settings.simorgh_action_journal_path,
        max_terminal_records=settings.simorgh_action_journal_max_terminal_records,
    )
    task_store = SQLiteAgentTaskStore(
        settings.simorgh_agent_task_store_path,
        max_terminal_records=settings.simorgh_agent_task_store_max_terminal_records,
    )
    try:
        await action_broker.configure_journal(
            action_journal,
            max_terminal_actions=settings.simorgh_action_journal_max_terminal_records,
        )
        await agent_task_control_plane.configure_store(task_store)
    except BaseException:
        task_store.close()
        action_journal.close()
        raise

    try:
        yield
    finally:
        try:
            await agent_task_control_plane.reset_to_memory_store()
        finally:
            task_store.close()
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


class TextGenerationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: str
    model: str
    provider: str
    request_id: str | None = None
    usage: dict[str, object] | None = None


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


@app.post("/v1/model/text", response_model=TextGenerationResponse)
async def generate_text(
    payload: TextGenerationRequest,
    settings: SettingsDependency,
) -> TextGenerationResponse:
    try:
        provider = AvalAIProvider(settings)
    except MissingAvalAICredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    result = await provider.generate_text(
        input_text=payload.input,
        instructions=payload.instructions,
        model=payload.model,
    )
    return TextGenerationResponse(
        output=result.text,
        model=result.model,
        provider=result.provider,
        request_id=result.request_id,
        usage=result.usage,
    )
