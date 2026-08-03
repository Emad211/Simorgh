from __future__ import annotations

from pathlib import Path

from simorgh_core.agents.live_provider_staging_cli import (
    reviewed_live_provider_staging_policy,
)

_ADR = Path("docs/adr/0022-explicitly-budgeted-live-provider-staging.md")
_RUNBOOK = Path("docs/LIVE_PROVIDER_STAGING_RUNBOOK.md")
_READINESS = Path(
    "docs/validation/phase-1-9-protected-environment-readiness.md"
)
_CHECKLIST = Path("docs/validation/phase-1-9-live-acceptance-checklist.md")
_WORKER = Path(".github/workflows/live-provider-staging.yml")
_REVIEWED_WORKER_SHA = "47b65f359fd844067346d987f9102f6eeab911d9"
_BOOTSTRAP_MAIN_SHA = "3bcb41437e3b8d2f497516ef9a214de5becf45e9"
_DISPATCHER_BLOB_SHA = "a5fe7be975ee41dd0be222ab1c606f8b4bab87d7"
_AUDITED_PR_HEAD = "096890150c7cf129eab19ebf4ac0bdf05e631e2f"
_AUDITED_MERGE_PREVIEW = "caf563792dfbcf65da6a32965d9479824bd9541a"
_AUDITED_CI_RUN_ID = "30781540524"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_live_staging_documents_cross_link() -> None:
    adr = _read(_ADR)
    runbook = _read(_RUNBOOK)

    assert "docs/LIVE_PROVIDER_STAGING_RUNBOOK.md" in adr
    assert "phase-1-9-protected-environment-readiness.md" in adr
    assert "phase-1-9-live-acceptance-checklist.md" in adr
    assert "ADR 0022" in runbook
    assert "phase-1-9-live-acceptance-checklist.md" in runbook
    assert ".github/workflows/live-provider-staging-dispatch.yml" in runbook
    assert ".github/workflows/live-provider-staging.yml" in runbook


def test_adr_preserves_pinned_manual_no_retry_authority_boundary() -> None:
    text = " ".join(_read(_ADR).split())

    required = (
        "Status: Accepted",
        ".github/workflows/live-provider-staging-dispatch.yml",
        "workflow_dispatch",
        ".github/workflows/live-provider-staging.yml",
        "workflow_call",
        "full 40-character commit SHA",
        "approved_dispatcher_sha",
        "refs/heads/main",
        "does not pass repository or organization secrets",
        "AVALAI_API_KEY",
        "exactly one model call",
        "zero retries",
        "only the AvalAI User API transaction lookup",
        "`pending` or `unavailable` reconciliation is incomplete",
        "Ordinary CI remains fake and zero-external",
    )
    for marker in required:
        assert marker in text


def test_runbook_matches_reviewed_policy_and_topology() -> None:
    text = _read(_RUNBOOK)
    policy = reviewed_live_provider_staging_policy("gpt-5.4-mini")

    expected = (
        f"| Model calls | `{policy.max_model_calls}` |",
        f"| Input-token ceiling | `{policy.max_input_tokens}` |",
        f"| Output-token ceiling | `{policy.max_output_tokens}` |",
        (
            "| Estimated-cost ceiling | "
            f"`{policy.max_estimated_cost_microusd}` micro-USD |"
        ),
        f"| Exact-cost ceiling | `{policy.max_exact_cost_unit} UNIT` |",
        (
            "| Remaining-credit floor | "
            f"`{policy.minimum_credit_floor_unit} UNIT` |"
        ),
        f"| Elapsed-time ceiling | `{policy.max_elapsed_ms} ms` |",
        (
            "| Transaction lookup | "
            f"`{policy.transaction_poll_attempts}` attempts, "
            f"`{policy.transaction_poll_interval_ms} ms` interval |"
        ),
        f"| User API timeout | `{policy.user_api_timeout_ms} ms` |",
        (
            "| User API response ceiling | "
            f"`{policy.user_api_max_response_bytes}` bytes |"
        ),
    )
    for marker in expected:
        assert marker in text

    assert policy.api_base_url in text
    assert policy.user_api_base_url in text
    assert policy.selected_model_id in text
    assert "approved_dispatcher_sha" in text
    assert "secrets: inherit" in text
    assert "do not start another model request" in text.casefold()
    assert "gh workflow disable live-provider-staging-dispatch.yml" in text
    assert "gh run cancel <RUN_ID>" in text


def test_readiness_records_repository_evidence_and_external_unknowns() -> None:
    text = _read(_READINESS)

    assert "Overall readiness: **NOT READY FOR LIVE DISPATCH**" in text
    assert "Approval package status: **NOT PREPARED" in text
    assert "Bootstrap pull request: #72 — merged" in text
    assert _BOOTSTRAP_MAIN_SHA in text
    assert _REVIEWED_WORKER_SHA in text
    assert _DISPATCHER_BLOB_SHA in text
    assert _AUDITED_PR_HEAD in text
    assert _AUDITED_MERGE_PREVIEW in text
    assert _AUDITED_CI_RUN_ID in text
    assert "Dispatcher on default branch | VERIFIED" in text
    assert "Dispatcher workflow enabled/visible | UNVERIFIED" in text
    assert "Environment object exists | UNVERIFIED" in text
    assert "Required reviewers configured | UNVERIFIED" in text
    assert "Self-review prevention enabled | UNVERIFIED" in text
    assert "Deployment restriction allows only `main` | UNVERIFIED" in text
    assert "Environment secret exists | UNVERIFIED" in text
    assert "Explicit user spend approval | NOT GRANTED" in text
    assert "No live workflow may be dispatched from this state." in text
    assert "Live dispatcher/worker runs initiated by this audit: `0`" in text
    assert "Real AvalAI/User API calls initiated by this audit: `0`" in text


def test_readiness_does_not_infer_unavailable_connector_settings() -> None:
    text = _read(_READINESS)

    assert "does **not** expose read operations" in text
    assert "workflow metadata/state" in text
    assert "repository deployment environments" in text
    assert "required reviewer configuration" in text
    assert "environment-secret names or update timestamps" in text
    assert "absence of an endpoint is not evidence" in text
    assert "The secret value was neither requested nor read." in text


def test_live_acceptance_checklist_locks_two_shas_and_limits() -> None:
    text = _read(_CHECKLIST)
    policy = reviewed_live_provider_staging_policy("gpt-5.4-mini")

    expected = (
        f"max_model_calls: {policy.max_model_calls}",
        "max_retries: 0",
        f"max_input_tokens: {policy.max_input_tokens}",
        f"max_output_tokens: {policy.max_output_tokens}",
        (
            "max_estimated_cost_microusd: "
            f"{policy.max_estimated_cost_microusd}"
        ),
        f"max_exact_cost_unit: {policy.max_exact_cost_unit} UNIT",
        (
            "minimum_credit_floor_unit: "
            f"{policy.minimum_credit_floor_unit} UNIT"
        ),
        f"max_elapsed_ms: {policy.max_elapsed_ms}",
        f"transaction_poll_attempts: {policy.transaction_poll_attempts}",
        (
            "transaction_poll_interval_ms: "
            f"{policy.transaction_poll_interval_ms}"
        ),
    )
    for marker in expected:
        assert marker in text

    assert "approved_dispatcher_sha" in text
    assert "approved_worker_sha" in text
    assert "approved_ref: refs/heads/main" in text
    assert "approved_by_user" in text
    assert "Reconciliation disposition is `exact`" in text
    assert "`pending`, `unavailable`, `mismatch`, `unknown`" in text
    assert "do not issue another model request" in text


def test_checklist_keeps_approval_package_blocked() -> None:
    text = _read(_CHECKLIST)

    assert "non_live_prerequisites_complete: false" in text
    assert "approval_package_status: NOT PREPARED" in text
    assert "dispatcher_enabled_visible: UNVERIFIED" in text
    assert "environment_exists: UNVERIFIED" in text
    assert "required_reviewer: UNVERIFIED" in text
    assert "self_review_prevention: UNVERIFIED" in text
    assert "deployment_ref_rule: UNVERIFIED" in text
    assert "environment_secret_present: UNVERIFIED" in text
    assert "environment_secret_updated_at: UNVERIFIED" in text
    assert "explicit user approval is `NOT GRANTED`" in text


def test_pre_secret_worker_runs_documentation_contract_tests() -> None:
    text = _read(_WORKER)
    gate = text.index("Run pre-secret quality and fake acceptance gates")
    live_job = text.index("live-canary:")
    test_path = "services/core/tests/test_live_provider_staging_documentation.py"

    assert test_path in text
    assert gate < text.index(test_path) < live_job
