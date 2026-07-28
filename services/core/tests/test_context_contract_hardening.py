from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from simorgh_core.agents.context_contracts import (
    ContextCompilerLimits,
    ContextMaterial,
    ContextSourceKind,
    ContextTrustClass,
    context_bundle_canonical_payload,
    context_material_id_for,
    context_text_sha256,
)
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.result_authority import (
    EvidenceCacheDisposition,
    PrivacyClassification,
    RetentionDisposition,
)


def test_secret_like_credential_material_is_rejected_without_echo() -> None:
    request_id = uuid4()
    secret = "Authorization: Bearer ghp_" + "a" * 32
    source_sha256 = canonical_fingerprint(
        {"request_id": str(request_id), "source": "secret-fixture"}
    )

    with pytest.raises(
        ValidationError,
        match="secret-like credential material",
    ) as error:
        ContextMaterial(
            material_id=context_material_id_for(
                request_id=request_id,
                source_kind=ContextSourceKind.EVIDENCE,
                source_id="github.secret-fixture",
                source_sha256=source_sha256,
            ),
            request_id=request_id,
            source_kind=ContextSourceKind.EVIDENCE,
            trust=ContextTrustClass.UNTRUSTED_EXTERNAL_EVIDENCE,
            source_id="github.secret-fixture",
            source_sha256=source_sha256,
            content_sha256=context_text_sha256(secret),
            content=secret,
            observed_at_ms=1_000,
            fresh_until_ms=2_000,
            cache_disposition=EvidenceCacheDisposition.LIVE,
            content_addressed=False,
            tainted=True,
            privacy=PrivacyClassification.INTERNAL,
            retention=RetentionDisposition.SESSION,
        )

    assert secret not in str(error.value)


def test_canonical_context_identity_ignores_tool_schema_input_order() -> None:
    first = {
        "capabilities": {
            "tool_ids": ["github.search", "github.fetch_file"],
            "connector_ids": ["github"],
            "model_tiers": [],
        },
        "tool_schemas": [
            {"tool_id": "github.search", "connector_id": "github"},
            {"tool_id": "github.fetch_file", "connector_id": "github"},
        ],
    }
    second = {
        "capabilities": {
            "tool_ids": ["github.fetch_file", "github.search"],
            "connector_ids": ["github"],
            "model_tiers": [],
        },
        "tool_schemas": list(reversed(first["tool_schemas"])),
    }

    first_payload = context_bundle_canonical_payload(first)
    second_payload = context_bundle_canonical_payload(second)

    assert first_payload == second_payload
    assert canonical_fingerprint(first_payload) == canonical_fingerprint(second_payload)
    assert [item["tool_id"] for item in first_payload["tool_schemas"]] == [
        "github.fetch_file",
        "github.search",
    ]


def test_project_and_decision_limits_are_strict_versioned_fields() -> None:
    limits = ContextCompilerLimits(max_project_items=3, max_decision_items=5)

    assert limits.max_project_items == 3
    assert limits.max_decision_items == 5

    with pytest.raises(ValidationError):
        ContextCompilerLimits(max_project_items=257)
    with pytest.raises(ValidationError):
        ContextCompilerLimits(max_decision_items=-1)
