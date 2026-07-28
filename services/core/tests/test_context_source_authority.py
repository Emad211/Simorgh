from __future__ import annotations

from uuid import uuid4

import pytest

from simorgh_core.agents.context_sources import (
    ContextMaterialConflictError,
    ContextMaterialRegistry,
    DuplicateContextMaterialError,
    context_material_from_github_projection,
)
from simorgh_core.agents.github_read_contracts import (
    GITHUB_SEARCH_TOOL_ID,
    GitHubReadProjectionEnvelope,
    GitHubSearchProjection,
)
from simorgh_core.agents.invocations import canonical_fingerprint, canonical_size_bytes
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
)


def _envelope() -> GitHubReadProjectionEnvelope:
    projection = GitHubSearchProjection(
        query="context compiler",
        items=(),
        total_count_lower_bound=0,
        truncated=False,
    )
    return GitHubReadProjectionEnvelope(
        tool_id=GITHUB_SEARCH_TOOL_ID,
        projection=projection,
        projection_sha256=canonical_fingerprint(projection),
        response_bytes=canonical_size_bytes(projection),
        observed_at_ms=2_000,
        fresh_until_ms=12_000,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        citation_reference="github:search:context-compiler",
        privacy=PrivacyClassification.INTERNAL,
    )


def test_typed_github_projection_becomes_task_bound_tainted_material() -> None:
    request_id = uuid4()
    envelope = _envelope()

    material = context_material_from_github_projection(
        request_id=request_id,
        envelope=envelope,
        required=True,
        priority=700,
    )

    assert material.request_id == request_id
    assert material.source_sha256 == envelope.projection_sha256
    assert material.content_addressed is False
    assert material.tainted
    assert material.trust.value == "untrusted_external_evidence"
    assert material.fresh_until_ms == envelope.fresh_until_ms
    assert material.citation_reference == envelope.citation_reference
    assert "context compiler" in material.content


def test_material_registry_rejects_duplicate_and_changed_content() -> None:
    material = context_material_from_github_projection(
        request_id=uuid4(),
        envelope=_envelope(),
    )

    with pytest.raises(DuplicateContextMaterialError, match="more than once"):
        ContextMaterialRegistry((material, material))

    registry = ContextMaterialRegistry((material,))
    assert registry.require(material) == material
    assert registry.canonical_sha256 == ContextMaterialRegistry((material,)).canonical_sha256

    changed = material.model_copy(update={"priority": material.priority + 1})
    with pytest.raises(ContextMaterialConflictError, match="conflicts"):
        registry.require(changed)
