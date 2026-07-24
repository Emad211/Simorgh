from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from simorgh_core import __version__
from simorgh_core.config import Settings, get_settings
from simorgh_core.providers.avalai import AvalAIProvider, MissingAvalAICredentialsError

app = FastAPI(
    title="Simorgh Core API",
    version=__version__,
    description="Core orchestration API for the Simorgh personal agent operating system.",
)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    environment: str
    model_gateway_configured: bool


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
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.simorgh_env,
        model_gateway_configured=settings.has_model_credentials,
    )


@app.post("/v1/model/text", response_model=TextGenerationResponse)
async def generate_text(
    payload: TextGenerationRequest,
    settings: Settings = Depends(get_settings),
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
