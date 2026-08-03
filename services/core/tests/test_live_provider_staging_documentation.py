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
_WORKFLOW = Path(".github/workflows/live-provider-staging.yml")


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


def test_adr_preserves_manual_no_retry_authority_boundary() -> None:
    text = " ".join(_read(_ADR).split())

    required = (
        "Status: Accepted",
        "workflow_dispatch",
        "live-provider-staging",
        "AVALAI_API_KEY",
        "lowercase 40-character commit SHA",
        "exactly one model call",
        "zero retries",
        "only the AvalAI User API transaction lookup",
        "pending` or `unavailable` reconciliation is incomplete",
        "default branch",
        "bootstrap/default-branch strategy",
        "Ordinary CI remains fake and zero-external",
    )
    for marker in required:
        assert marker in text


def test_runbook_matches_reviewed_policy_and_workflow() -> None:
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
    assert "do not start another model request" in text.casefold()
    assert "gh workflow disable live-provider-staging.yml" in text
    assert "gh run cancel <RUN_ID>" in text


def test_readiness_audit_fails_closed_on_external_configuration() -> None:
    text = _read(_READINESS)

    assert "Overall readiness: **NOT READY FOR LIVE DISPATCH**" in text
    assert "workflow is absent from the default branch" in text
    assert "Environment object exists | UNVERIFIED" in text
    assert "Required reviewers configured | UNVERIFIED" in text
    assert "Environment secret exists | UNVERIFIED" in text
    assert "Explicit user spend approval | NOT GRANTED" in text
    assert "No live workflow may be dispatched from this state." in text
    assert (
        "Live workflow dispatches observed or initiated by this audit: `0`"
        in text
    )
    assert (
        "Real AvalAI/User API calls initiated by this audit: `0`" in text
    )


def test_live_acceptance_checklist_locks_limits_and_rejection_states() -> None:
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

    assert "approved_commit_sha" in text
    assert "approved_ref" in text
    assert "approved_by_user" in text
    assert "Reconciliation disposition is `exact`" in text
    assert "`pending`, `unavailable`, `mismatch`, `unknown`" in text
    assert "do not issue another model request" in text


def test_pre_secret_workflow_runs_documentation_contract_tests() -> None:
    text = _read(_WORKFLOW)
    gate = text.index("Run pre-secret quality and fake acceptance gates")
    live_job = text.index("live-canary:")
    test_path = "services/core/tests/test_live_provider_staging_documentation.py"

    assert test_path in text
    assert gate < text.index(test_path) < live_job
