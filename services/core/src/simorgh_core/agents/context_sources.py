from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from simorgh_core.agents.context_contracts import (
    ContextMaterial,
    ContextSourceKind,
    ContextTrustClass,
    context_material_id_for,
    context_text_sha256,
)
from simorgh_core.agents.github_read_contracts import GitHubReadProjectionEnvelope
from simorgh_core.agents.invocations import canonical_fingerprint, canonical_json
from simorgh_core.agents.result_authority import RetentionDisposition


class ContextSourceAuthorityError(RuntimeError):
    """A context material is outside approved native source authority."""


class DuplicateContextMaterialError(ContextSourceAuthorityError):
    pass


class UnknownContextMaterialError(ContextSourceAuthorityError):
    pass


class ContextMaterialConflictError(ContextSourceAuthorityError):
    pass


class ContextMaterialRegistry:
    """Immutable exact-material registry populated from approved native sources."""

    def __init__(self, materials: Iterable[ContextMaterial] = ()) -> None:
        compiled: dict[UUID, ContextMaterial] = {}
        for material in materials:
            candidate = ContextMaterial.model_validate(material.model_dump(mode="json"))
            if candidate.material_id in compiled:
                raise DuplicateContextMaterialError(
                    f"context material {candidate.material_id} was registered more than once"
                )
            compiled[candidate.material_id] = candidate
        self._materials = compiled
        self._canonical_sha256 = canonical_fingerprint(
            [
                item.model_dump(mode="json")
                for item in sorted(
                    compiled.values(),
                    key=lambda candidate: str(candidate.material_id),
                )
            ]
        )

    @property
    def canonical_sha256(self) -> str:
        return self._canonical_sha256

    def require(self, material: ContextMaterial) -> ContextMaterial:
        approved = self._materials.get(material.material_id)
        if approved is None:
            raise UnknownContextMaterialError(
                f"context material {material.material_id} is not approved"
            )
        if approved != material:
            raise ContextMaterialConflictError(
                "context material conflicts with approved source authority"
            )
        return approved

    def get(self, material_id: UUID) -> ContextMaterial | None:
        return self._materials.get(material_id)

    def load(self) -> tuple[ContextMaterial, ...]:
        return tuple(
            sorted(
                self._materials.values(),
                key=lambda candidate: str(candidate.material_id),
            )
        )


def context_material_from_github_projection(
    *,
    request_id: UUID,
    envelope: GitHubReadProjectionEnvelope,
    required: bool = False,
    priority: int = 100,
    retention: RetentionDisposition = RetentionDisposition.SESSION,
) -> ContextMaterial:
    """Derive tainted context data from a validated typed GitHub projection."""

    validated = GitHubReadProjectionEnvelope.model_validate(
        envelope.model_dump(mode="json")
    )
    content = canonical_json(validated.projection)
    source_id = f"github.projection:{validated.tool_id}"
    return ContextMaterial(
        material_id=context_material_id_for(
            request_id=request_id,
            source_kind=ContextSourceKind.EVIDENCE,
            source_id=source_id,
            source_sha256=validated.projection_sha256,
        ),
        source_kind=ContextSourceKind.EVIDENCE,
        trust=ContextTrustClass.UNTRUSTED_EXTERNAL_EVIDENCE,
        source_id=source_id,
        source_sha256=validated.projection_sha256,
        content_sha256=context_text_sha256(content),
        content=content,
        required=required,
        priority=priority,
        observed_at_ms=validated.observed_at_ms,
        fresh_until_ms=validated.fresh_until_ms,
        cache_disposition=validated.cache_disposition,
        content_addressed=False,
        tainted=True,
        privacy=validated.privacy,
        retention=retention,
        citation_reference=validated.citation_reference,
    )


__all__ = [
    "ContextMaterialConflictError",
    "ContextMaterialRegistry",
    "ContextSourceAuthorityError",
    "DuplicateContextMaterialError",
    "UnknownContextMaterialError",
    "context_material_from_github_projection",
]
