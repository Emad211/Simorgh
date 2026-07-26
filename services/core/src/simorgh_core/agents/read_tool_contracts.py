from __future__ import annotations

from typing import Protocol, TypeVar

RequestT = TypeVar("RequestT", contravariant=True)
ProjectionT = TypeVar("ProjectionT", covariant=True)


class GovernedReadAdapter(Protocol[RequestT, ProjectionT]):
    """Provider-neutral boundary for one reviewed structured read connector."""

    @property
    def connector_id(self) -> str: ...

    @property
    def connector_version(self) -> str: ...

    async def invoke(self, request: RequestT) -> ProjectionT: ...
