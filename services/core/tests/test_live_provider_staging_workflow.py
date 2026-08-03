from __future__ import annotations

import re
from pathlib import Path

from simorgh_core.agents.live_provider_staging_cli import (
    reviewed_live_provider_staging_policy,
)

_DISPATCHER = Path(".github/workflows/live-provider-staging-dispatch.yml")
_WORKER = Path(".github/workflows/live-provider-staging.yml")
_CI_WORKFLOW = Path(".github/workflows/ci.yml")
_CONSTRAINTS = Path(".github/constraints/live-provider-staging.txt")
_REVIEWED_WORKER_SHA = "47b65f359fd844067346d987f9102f6eeab911d9"
_ACTION_SHA = re.compile(r"uses: [^@\s]+@[0-9a-f]{40}$", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dispatcher_is_manual_only_main_bound_and_non_cancelling() -> None:
    text = _read(_DISPATCHER)

    assert text.count("workflow_dispatch:") == 1
    assert "workflow_call:" not in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "schedule:" not in text
    assert "group: live-provider-staging-dispatch" in text
    assert "cancel-in-progress: false" in text
    assert "permissions:\n  contents: read" in text
    assert 'test "$DISPATCH_REPOSITORY" = "Emad211/Simorgh"' in text
    assert 'test "$DISPATCH_REF" = "refs/heads/main"' in text
    assert 'test "$APPROVED_DISPATCHER_SHA" = "$DISPATCH_SHA"' in text


def test_dispatcher_exposes_only_its_approval_sha() -> None:
    text = _read(_DISPATCHER)
    inputs = text[text.index("inputs:") : text.index("permissions:")]

    assert inputs.count("approved_dispatcher_sha:") == 1
    assert "reviewed_commit_sha:" not in inputs
    assert "model_id:" not in inputs
    assert "provider" not in inputs.casefold()
    assert "budget" not in inputs.casefold()
    assert "prompt" not in inputs.casefold()


def test_dispatcher_pins_exact_worker_and_model_without_secrets() -> None:
    text = _read(_DISPATCHER)
    expected_uses = (
        "uses: Emad211/Simorgh/.github/workflows/live-provider-staging.yml@"
        f"{_REVIEWED_WORKER_SHA}"
    )

    assert expected_uses in text
    assert f"reviewed_commit_sha: {_REVIEWED_WORKER_SHA}" in text
    assert text.count(_REVIEWED_WORKER_SHA) == 3
    assert "model_id: gpt-5.4-mini" in text
    assert 'test "$REVIEWED_MODEL_ID" = "gpt-5.4-mini"' in text
    assert "secrets:" not in text
    assert "secrets: inherit" not in text
    assert "AVALAI_API_KEY" not in text


def test_live_worker_is_callable_only_and_single_concurrency() -> None:
    text = _read(_WORKER)

    assert text.count("workflow_call:") == 1
    assert "workflow_dispatch:" not in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "schedule:" not in text
    assert "group: live-provider-staging" in text
    assert "cancel-in-progress: false" in text
    assert "permissions:\n  contents: read" in text


def test_live_worker_uses_protected_environment_and_secret_once() -> None:
    text = _read(_WORKER)

    assert "environment:\n      name: live-provider-staging" in text
    assert text.count("secrets.AVALAI_API_KEY") == 1
    secret_offset = text.index("secrets.AVALAI_API_KEY")
    fake_gate_offset = text.index("Run pre-secret quality and fake acceptance gates")
    live_job_offset = text.index("live-canary:")
    assert fake_gate_offset < live_job_offset < secret_offset
    assert "AVALAI_API_KEY" not in text[:live_job_offset]


def test_live_worker_checks_exact_caller_commit_and_fixed_model() -> None:
    text = _read(_WORKER)
    policy = reviewed_live_provider_staging_policy("gpt-5.4-mini")

    assert "^[0-9a-f]{40}$" in text
    assert text.count('test "$(git rev-parse HEAD)" = "$REVIEWED_COMMIT_SHA"') == 2
    assert text.count('test "$CALLER_REPOSITORY" = "Emad211/Simorgh"') == 2
    assert text.count('test "$CALLER_REF" = "refs/heads/main"') == 2
    assert text.count(
        'test "$CALLER_WORKFLOW_REF" = "Emad211/Simorgh/.github/workflows/'
        'live-provider-staging-dispatch.yml@refs/heads/main"'
    ) == 2
    assert text.count('test "$MODEL_ID" = "gpt-5.4-mini"') == 2
    assert "reviewed_commit_sha:" in text
    assert "model_id:" in text
    assert policy.max_model_calls == 1
    assert policy.allowed_model_ids == ("gpt-5.4-mini",)
    assert "SIMORGH_CANARY" not in text
    assert "input_text" not in text


def test_live_worker_runs_quality_before_secret_and_verifies_artifact() -> None:
    text = _read(_WORKER)

    assert "ruff check ." in text
    assert "mypy services/core/src" in text
    assert "test_live_provider_staging_artifact.py" in text
    assert "test_live_provider_staging_cli.py" in text
    assert "test_live_provider_staging_documentation.py" in text
    assert "test_live_provider_staging_workflow.py" in text
    assert "live_provider_staging_cli run" in text
    assert "live_provider_staging_cli verify" in text
    assert "--require-passed" in text
    assert text.count("if: always()") == 2
    assert "if-no-files-found: error" in text
    assert "retention-days: 30" in text


def test_live_worker_actions_and_direct_dependencies_are_pinned() -> None:
    text = _read(_WORKER)
    uses_lines = "\n".join(
        line.strip() for line in text.splitlines() if line.strip().startswith("uses:")
    )
    matches = _ACTION_SHA.findall(uses_lines)

    assert len(matches) == 5
    constraints = _CONSTRAINTS.read_text(encoding="utf-8").splitlines()
    assert constraints
    assert all("==" in line for line in constraints)
    assert "pip==26.2" in text
    assert "--constraint .github/constraints/live-provider-staging.txt" in text


def test_ordinary_ci_cannot_invoke_live_staging_or_read_live_secret() -> None:
    text = _read(_CI_WORKFLOW)

    assert "live_provider_staging_cli" not in text
    assert "AVALAI_API_KEY" not in text
    assert "live-provider-staging" not in text
