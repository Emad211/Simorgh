from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from simorgh_core.config import Settings
from simorgh_core.providers.base import ModelOutput


class MissingAvalAICredentialsError(RuntimeError):
    pass


class AvalAIProvider:
    """AvalAI adapter using the official OpenAI Python SDK and a custom base URL."""

    provider_name = "avalai"

    def __init__(self, settings: Settings) -> None:
        if not settings.has_model_credentials or settings.avalai_api_key is None:
            raise MissingAvalAICredentialsError(
                "AVALAI_API_KEY is required before invoking a model."
            )

        self._default_model = settings.avalai_default_model
        self._client = AsyncOpenAI(
            api_key=settings.avalai_api_key.get_secret_value(),
            base_url=settings.avalai_base_url,
        )

    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelOutput:
        selected_model = model or self._default_model
        request: dict[str, Any] = {
            "model": selected_model,
            "input": input_text,
        }
        if instructions:
            request["instructions"] = instructions
        if max_output_tokens is not None:
            request["max_output_tokens"] = max_output_tokens

        response = await self._client.responses.create(**request)
        usage = response.usage.model_dump(mode="json") if response.usage else None

        return ModelOutput(
            text=response.output_text,
            model=response.model or selected_model,
            provider=self.provider_name,
            request_id=getattr(response, "_request_id", None),
            usage=usage,
        )

    async def list_models(self) -> list[str]:
        page = await self._client.models.list()
        return sorted(model.id for model in page.data)
