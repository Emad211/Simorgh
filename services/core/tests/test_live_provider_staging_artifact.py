from __future__ import annotations

import json
import stat
from pathlib import Path
from uuid import UUID

import pytest

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.live_provider_staging_artifact import (
    LiveProviderExternalCallCounts,
    LiveProviderStagingArtifactDisposition,
    LiveProviderStagingArtifactError,
    LiveProviderStagingArtifactFailureCode,
    new_live_provider_staging_artifact,
    require_sanitized_artifact_bytes,
    verify_live_provider_staging_artifact,
    write_live_provider_staging_artifact,
)

_STAGING_RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
_REQUEST_ID = UUID("22222222-2222-4222-8222-222222222222")
_INVOCATION_ID = UUID("33333333-3333-4333-8333-333333333333")
_SOURCE_COMMIT = "a" * 40


def _failed_artifact():
    return new_live_provider_staging_artifact(
        source_commit_sha=_SOURCE_COMMIT,
        workflow_run_id=123,
        workflow_run_attempt=1,
        generated_at_ms=1_000,
        staging_run_id=_STAGING_RUN_ID,
        request_id=_REQUEST_ID,
        invocation_id=_INVOCATION_ID,
        disposition=LiveProviderStagingArtifactDisposition.FAILED,
        failure_code=LiveProviderStagingArtifactFailureCode.EXECUTION_FAILED,
        result=None,
        trace_evidence=None,
        first_run_calls=LiveProviderExternalCallCounts(),
        replay_delta_calls=LiveProviderExternalCallCounts(),
        usage_before_replay=UsageVector(),
        usage_after_replay=UsageVector(),
        replay_observed=False,
        replay_result_sha256=None,
    )


def test_sanitized_artifact_round_trip_is_canonical_and_private(tmp_path: Path) -> None:
    artifact = _failed_artifact()
    path = tmp_path / "staging.json"

    write_live_provider_staging_artifact(
        path,
        artifact,
        forbidden_values=("super-secret-value",),
    )
    loaded = verify_live_provider_staging_artifact(
        path,
        forbidden_values=("super-secret-value",),
    )

    assert loaded == artifact
    assert path.read_bytes().endswith(b"\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    serialized = path.read_text(encoding="utf-8")
    assert "super-secret-value" not in serialized
    assert "SIMORGH_CANARY" not in serialized


def test_artifact_tampering_fails_even_when_json_is_valid(tmp_path: Path) -> None:
    artifact = _failed_artifact()
    path = tmp_path / "staging.json"
    write_live_provider_staging_artifact(path, artifact)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["workflow_run_attempt"] = 2
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(
        LiveProviderStagingArtifactError,
        match="contract is invalid",
    ):
        verify_live_provider_staging_artifact(path)


def test_privacy_scan_rejects_canary_markers_and_exact_secret() -> None:
    with pytest.raises(
        LiveProviderStagingArtifactError,
        match="forbidden marker",
    ):
        require_sanitized_artifact_bytes(b'{"value":"SIMORGH_CANARY_OK"}')

    with pytest.raises(
        LiveProviderStagingArtifactError,
        match="forbidden secret value",
    ):
        require_sanitized_artifact_bytes(
            b'{"value":"secret-live-token"}',
            forbidden_values=("secret-live-token",),
        )


def test_failed_artifact_cannot_claim_success_without_evidence() -> None:
    with pytest.raises(ValueError, match="requires result and Trace evidence"):
        new_live_provider_staging_artifact(
            source_commit_sha=_SOURCE_COMMIT,
            workflow_run_id=123,
            workflow_run_attempt=1,
            generated_at_ms=1_000,
            staging_run_id=_STAGING_RUN_ID,
            request_id=_REQUEST_ID,
            invocation_id=_INVOCATION_ID,
            disposition=LiveProviderStagingArtifactDisposition.PASSED,
            failure_code=LiveProviderStagingArtifactFailureCode.NONE,
            result=None,
            trace_evidence=None,
            first_run_calls=LiveProviderExternalCallCounts(),
            replay_delta_calls=LiveProviderExternalCallCounts(),
            usage_before_replay=UsageVector(),
            usage_after_replay=UsageVector(),
            replay_observed=False,
            replay_result_sha256=None,
        )
