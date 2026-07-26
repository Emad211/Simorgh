from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.github_read_adapter import (
    FakeGitHubReadAdapter,
    GitHubResponseLimitError,
    default_github_read_manifest,
    github_fixture_key,
)
from simorgh_core.agents.github_read_contracts import (
    GITHUB_FETCH_FILE_TOOL_ID,
    GitHubFileArguments,
    GitHubFileProjection,
    GitHubReadLimits,
    GitHubReadProjectionEnvelope,
    GitHubTextDisposition,
    GovernedGitHubReadRequest,
)
from simorgh_core.agents.invocations import canonical_fingerprint, canonical_size_bytes
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
)


def _request(*, max_text: int = 8_000) -> GovernedGitHubReadRequest:
    return GovernedGitHubReadRequest(
        request_id=uuid4(),
        invocation_id=uuid4(),
        agent_version="1.0.0",
        arguments=GitHubFileArguments(
            repository="Emad211/Simorgh",
            ref="main",
            path="README.md",
        ),
        limits=GitHubReadLimits(
            max_response_bytes=32_000,
            max_text_characters=max_text,
            max_items=10,
        ),
        privacy_ceiling=PrivacyClassification.INTERNAL,
        deadline_at_ms=60_000,
        monotonic_timeout_ms=30_000,
        cancellation_owner_id=uuid4(),
    )


def _envelope(text: str = "# Simorgh\n") -> GitHubReadProjectionEnvelope:
    projection = GitHubFileProjection(
        repository="Emad211/Simorgh",
        ref="main",
        path="README.md",
        blob_sha="a" * 40,
        byte_count=len(text.encode("utf-8")),
        text=text,
        text_disposition=GitHubTextDisposition.COMPLETE,
    )
    return GitHubReadProjectionEnvelope(
        tool_id=GITHUB_FETCH_FILE_TOOL_ID,
        projection=projection,
        projection_sha256=canonical_fingerprint(projection),
        response_bytes=canonical_size_bytes(projection),
        observed_at_ms=2_000,
        fresh_until_ms=12_000,
        cache_disposition=EvidenceCacheDisposition.LIVE,
        citation_reference="github:Emad211/Simorgh@main:README.md",
        privacy=PrivacyClassification.INTERNAL,
    )


def test_file_arguments_reject_path_escape() -> None:
    with pytest.raises(ValidationError, match="unsafe"):
        GitHubFileArguments(
            repository="Emad211/Simorgh",
            ref="main",
            path="../outside.txt",
        )


def test_projection_envelope_rejects_hash_and_byte_mismatch() -> None:
    envelope = _envelope()
    payload = envelope.model_dump(mode="json")

    with pytest.raises(ValidationError, match="hash"):
        GitHubReadProjectionEnvelope.model_validate(
            {**payload, "projection_sha256": "f" * 64}
        )
    with pytest.raises(ValidationError, match="byte count"):
        GitHubReadProjectionEnvelope.model_validate(
            {**payload, "response_bytes": envelope.response_bytes + 1}
        )


def test_manifest_contains_exact_read_only_operations() -> None:
    manifest = default_github_read_manifest()

    assert manifest.connector_id == "github"
    assert manifest.maximum_pages == 1
    assert {tool.tool_id for tool in manifest.tools} == {
        "github.search",
        "github.fetch-file",
        "github.fetch-issue",
        "github.fetch-pr",
    }
    assert all(tool.read_only for tool in manifest.tools)


@pytest.mark.asyncio
async def test_fake_adapter_enforces_typed_text_limit() -> None:
    request = _request(max_text=4)
    envelope = _envelope(text="long fixture")
    adapter = FakeGitHubReadAdapter(
        fixtures={github_fixture_key(request): envelope}
    )

    with pytest.raises(GitHubResponseLimitError, match="text limit"):
        await adapter.invoke(request)

    assert adapter.calls == 1
