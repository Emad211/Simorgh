from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ModelOutput:
    text: str
    model: str
    provider: str
    request_id: str | None = None
    usage: dict[str, Any] | None = None


class ModelProvider(Protocol):
    async def generate_text(
        self,
        *,
        input_text: str,
        model: str | None = None,
        instructions: str | None = None,
    ) -> ModelOutput: ...

    async def list_models(self) -> list[str]: ...
