from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simorgh_core.agents.contracts import UsageVector
from simorgh_core.agents.invocations import canonical_fingerprint
from simorgh_core.agents.live_provider_staging_contracts import (
    LIVE_PROVIDER_CANARY_INPUT,
    LIVE_PROVIDER_CANARY_INSTRUCTIONS,
    LIVE_PROVIDER_CANARY_OUTPUT,
    LiveProviderReconciliationDisposition,
    LiveProviderStagingDisposition,
    LiveProviderStagingResult,
)
from simorgh_core.agents.live_provider_staging_trace import (
    LiveProviderStagingTraceEvidence,
)

LIVE_PROVIDER_STAGING_ARTIFACT_VERSION: Literal["1.0"] = "1.0"
_MAX_ARTIFACT_BYTES = 1_000_000
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
_STATIC_FORBIDDEN_MARKERS = (
    LIVE_PROVIDER_CANARY_INPUT,
    LIVE_PROVIDER_CANARY_INSTRUCTIONS,
    LIVE_PROVIDER_CANARY_OUTPUT,
    "authorization",
    "bearer ",
    "api_key",
    "api-key",
    "cookie",
    "headers",
    "ip_address",
    "safety_identifier",
    "raw_response",
    "environment_dump",
)


class LiveProviderStagingArtifactError(RuntimeError):
    """Sanitized artifact construction or verification failure."""


class LiveProviderStagingArtifactDisposition(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class LiveProviderStagingArtifactFailureCode(StrEnum):
    NONE = "none"
    PREFLIGHT_FAILED = "preflight_failed"
    EXECUTION_FAILED = "execution_failed"
    RESULT_INCOMPLETE = "result_incomplete"
    TRACE_INVALID = "trace_invalid"
    REPLAY_FAILED = "replay_failed"


class LiveProviderExternalCallCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    model_catalog_calls: int = Field(default=0, ge=0, le=16)
    model_generate_calls: int = Field(default=0, ge=0, le=16)
    credit_calls: int = Field(default=0, ge=0, le=16)
    transaction_lookup_calls: int = Field(default=0, ge=0, le=64)

    def minus(
        self,
        earlier: LiveProviderExternalCallCounts,
    ) -> LiveProviderExternalCallCounts:
        fields = (
            "model_catalog_calls",
            "model_generate_calls",
            "credit_calls",
            "transaction_lookup_calls",
        )
        values = {
            field: getattr(self, field) - getattr(earlier, field)
            for field in fields
        }
        if any(value < 0 for value in values.values()):
            raise LiveProviderStagingArtifactError(
                "live-provider call counters are not monotonic"
            )
        return LiveProviderExternalCallCounts(**values)


class LiveProviderStagingArtifact(BaseModel):
    """Versioned sanitized evidence emitted by the protected manual workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = LIVE_PROVIDER_STAGING_ARTIFACT_VERSION
    artifact_id: UUID
    canonical_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )
    source_commit_sha: str = Field(
        min_length=40,
        max_length=40,
        pattern=_COMMIT_SHA_PATTERN,
    )
    workflow_run_id: int = Field(ge=1)
    workflow_run_attempt: int = Field(ge=1, le=100)
    generated_at_ms: int = Field(ge=0)
    staging_run_id: UUID
    request_id: UUID
    invocation_id: UUID
    disposition: LiveProviderStagingArtifactDisposition
    failure_code: LiveProviderStagingArtifactFailureCode
    result: LiveProviderStagingResult | None = None
    trace_evidence: LiveProviderStagingTraceEvidence | None = None
    first_run_calls: LiveProviderExternalCallCounts = Field(
        default_factory=LiveProviderExternalCallCounts
    )
    replay_delta_calls: LiveProviderExternalCallCounts = Field(
        default_factory=LiveProviderExternalCallCounts
    )
    usage_before_replay: UsageVector = Field(default_factory=UsageVector)
    usage_after_replay: UsageVector = Field(default_factory=UsageVector)
    replay_observed: bool = False
    replay_result_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )
    privacy_disposition: Literal["sanitized"] = "sanitized"

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        if self.result is not None:
            if (
                self.result.staging_run_id != self.staging_run_id
                or self.result.request_id != self.request_id
                or self.result.invocation_id != self.invocation_id
            ):
                raise ValueError("staging artifact result identity is inconsistent")
        if self.trace_evidence is not None:
            if (
                self.trace_evidence.trace_id
                != (self.result.trace_id if self.result is not None else None)
                or self.trace_evidence.request_id != self.request_id
                or self.trace_evidence.invocation_id != self.invocation_id
            ):
                raise ValueError("staging artifact Trace evidence is inconsistent")

        if self.disposition == LiveProviderStagingArtifactDisposition.PASSED:
            if self.failure_code != LiveProviderStagingArtifactFailureCode.NONE:
                raise ValueError("passed staging artifact cannot carry failure code")
            if self.result is None or self.trace_evidence is None:
                raise ValueError(
                    "passed staging artifact requires result and Trace evidence"
                )
            if (
                self.result.disposition != LiveProviderStagingDisposition.COMPLETED
                or self.result.reconciliation_disposition
                != LiveProviderReconciliationDisposition.EXACT
            ):
                raise ValueError(
                    "passed staging artifact requires exact completed result"
                )
            if not self.replay_observed:
                raise ValueError("passed staging artifact requires replay proof")
            if self.replay_result_sha256 != self.result.canonical_sha256:
                raise ValueError("staging replay result identity is inconsistent")
            if self.replay_delta_calls != LiveProviderExternalCallCounts():
                raise ValueError("staging replay must create zero external calls")
            if self.usage_before_replay != self.usage_after_replay:
                raise ValueError("staging replay must not mutate committed usage")
            if self.first_run_calls.model_generate_calls != 1:
                raise ValueError(
                    "passed staging artifact requires exactly one model call"
                )
            if self.first_run_calls.model_catalog_calls != 1:
                raise ValueError(
                    "passed staging artifact requires one model-catalog call"
                )
            if self.first_run_calls.credit_calls != 1:
                raise ValueError(
                    "passed staging artifact requires one credit preflight"
                )
            if self.first_run_calls.transaction_lookup_calls < 1:
                raise ValueError(
                    "passed staging artifact requires transaction lookup"
                )
        elif self.failure_code == LiveProviderStagingArtifactFailureCode.NONE:
            raise ValueError("failed staging artifact requires typed failure code")

        if self.canonical_sha256 != live_provider_staging_artifact_sha256(self):
            raise ValueError(
                "staging artifact hash does not match authoritative content"
            )
        expected_id = live_provider_staging_artifact_id_for(
            staging_run_id=self.staging_run_id,
            canonical_sha256=self.canonical_sha256,
        )
        if self.artifact_id != expected_id:
            raise ValueError("staging artifact ID does not match canonical identity")
        return self


def live_provider_staging_artifact_payload(
    value: LiveProviderStagingArtifact | dict[str, object],
) -> dict[str, object]:
    payload = (
        value.model_dump(mode="json")
        if isinstance(value, LiveProviderStagingArtifact)
        else dict(value)
    )
    payload.pop("artifact_id", None)
    payload.pop("canonical_sha256", None)
    return payload


def live_provider_staging_artifact_sha256(
    value: LiveProviderStagingArtifact | dict[str, object],
) -> str:
    return canonical_fingerprint(live_provider_staging_artifact_payload(value))


def live_provider_staging_artifact_id_for(
    *,
    staging_run_id: UUID,
    canonical_sha256: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"simorgh-live-provider-staging-artifact:{staging_run_id}:{canonical_sha256}",
    )


def new_live_provider_staging_artifact(
    *,
    source_commit_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    generated_at_ms: int,
    staging_run_id: UUID,
    request_id: UUID,
    invocation_id: UUID,
    disposition: LiveProviderStagingArtifactDisposition,
    failure_code: LiveProviderStagingArtifactFailureCode,
    result: LiveProviderStagingResult | None,
    trace_evidence: LiveProviderStagingTraceEvidence | None,
    first_run_calls: LiveProviderExternalCallCounts,
    replay_delta_calls: LiveProviderExternalCallCounts,
    usage_before_replay: UsageVector,
    usage_after_replay: UsageVector,
    replay_observed: bool,
    replay_result_sha256: str | None,
) -> LiveProviderStagingArtifact:
    provisional = LiveProviderStagingArtifact.model_construct(
        schema_version=LIVE_PROVIDER_STAGING_ARTIFACT_VERSION,
        artifact_id=UUID(int=0),
        canonical_sha256="0" * 64,
        source_commit_sha=source_commit_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        generated_at_ms=generated_at_ms,
        staging_run_id=staging_run_id,
        request_id=request_id,
        invocation_id=invocation_id,
        disposition=disposition,
        failure_code=failure_code,
        result=result,
        trace_evidence=trace_evidence,
        first_run_calls=first_run_calls,
        replay_delta_calls=replay_delta_calls,
        usage_before_replay=usage_before_replay,
        usage_after_replay=usage_after_replay,
        replay_observed=replay_observed,
        replay_result_sha256=replay_result_sha256,
        privacy_disposition="sanitized",
    )
    canonical_sha256 = live_provider_staging_artifact_sha256(provisional)
    return LiveProviderStagingArtifact.model_validate(
        {
            **provisional.model_dump(mode="json"),
            "artifact_id": live_provider_staging_artifact_id_for(
                staging_run_id=staging_run_id,
                canonical_sha256=canonical_sha256,
            ),
            "canonical_sha256": canonical_sha256,
        }
    )


def live_provider_staging_artifact_bytes(
    artifact: LiveProviderStagingArtifact,
) -> bytes:
    encoded = json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    if len(encoded) > _MAX_ARTIFACT_BYTES:
        raise LiveProviderStagingArtifactError(
            "staging artifact exceeds byte limit"
        )
    return encoded


def require_sanitized_artifact_bytes(
    payload: bytes,
    *,
    forbidden_values: tuple[str, ...] = (),
) -> None:
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise LiveProviderStagingArtifactError(
            "staging artifact is not valid UTF-8"
        ) from None
    lowered = decoded.casefold()
    for marker in _STATIC_FORBIDDEN_MARKERS:
        if marker.casefold() in lowered:
            raise LiveProviderStagingArtifactError(
                "staging artifact contains a forbidden marker"
            )
    for value in forbidden_values:
        if value and value in decoded:
            raise LiveProviderStagingArtifactError(
                "staging artifact contains a forbidden secret value"
            )


def write_live_provider_staging_artifact(
    path: str | Path,
    artifact: LiveProviderStagingArtifact,
    *,
    forbidden_values: tuple[str, ...] = (),
) -> None:
    target = Path(path)
    payload = live_provider_staging_artifact_bytes(artifact)
    require_sanitized_artifact_bytes(payload, forbidden_values=forbidden_values)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.chmod(temporary, 0o600)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_live_provider_staging_artifact(
    path: str | Path,
    *,
    forbidden_values: tuple[str, ...] = (),
) -> LiveProviderStagingArtifact:
    target = Path(path)
    try:
        payload = target.read_bytes()
    except OSError:
        raise LiveProviderStagingArtifactError(
            "staging artifact could not be read"
        ) from None
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise LiveProviderStagingArtifactError(
            "staging artifact exceeds byte limit"
        )
    require_sanitized_artifact_bytes(payload, forbidden_values=forbidden_values)
    try:
        return LiveProviderStagingArtifact.model_validate_json(payload)
    except Exception:
        raise LiveProviderStagingArtifactError(
            "staging artifact contract is invalid"
        ) from None


__all__ = [
    "LIVE_PROVIDER_STAGING_ARTIFACT_VERSION",
    "LiveProviderExternalCallCounts",
    "LiveProviderStagingArtifact",
    "LiveProviderStagingArtifactDisposition",
    "LiveProviderStagingArtifactError",
    "LiveProviderStagingArtifactFailureCode",
    "live_provider_staging_artifact_bytes",
    "live_provider_staging_artifact_id_for",
    "live_provider_staging_artifact_payload",
    "live_provider_staging_artifact_sha256",
    "new_live_provider_staging_artifact",
    "require_sanitized_artifact_bytes",
    "verify_live_provider_staging_artifact",
    "write_live_provider_staging_artifact",
]
