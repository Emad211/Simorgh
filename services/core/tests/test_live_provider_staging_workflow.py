from __future__ import annotations

import re
from pathlib import Path

from simorgh_core.agents.live_provider_staging_cli import (
    reviewed_live_provider_staging_policy,
)

_WORKFLOW = Path(".github/workflows/live-provider-staging.yml")
_CI_WORKFLOW = Path(".github/workflows/ci.yml")
_CONSTRAINTS = Path(".github/constraints/live-provider-staging.txt")
_ACTION_SHA = re.compile(r"uses: [^@\s]+@[0-9a-f]{40}$", re.MULTILINE)


def _workflow_text() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_live_workflow_is_manual_only_and_single_concurrency() -> None:
    text = _workflow_text()

    assert text.count("workflow_dispatch:") == 1
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "schedule:" not in text
    assert "group: live-provider-staging" in text
    assert "cancel-in-progress: false" in text
    assert "permissions:\n  contents: read" in text


def test_live_workflow_uses_protected_environment_and_secret_once() -> None:
    text = _workflow_text()

    assert "environment:\n      name: live-provider-staging" in text
    assert text.count("secrets.AVALAI_API_KEY") == 1
    secret_offset = text.index("secrets.AVALAI_API_KEY")
    fake_gate_offset = text.index("Run pre-secret quality and fake acceptance gates")
    live_job_offset = text.index("live-canary:")
    assert fake_gate_offset < live_job_offset < secret_offset
    assert "AVALAI_API_KEY" not in text[:live_job_offset]


def test_live_workflow_checks_exact_commit_and_fixed_reviewed_model() -> None:
    text = _workflow_text()
    policy = reviewed_live_provider_staging_policy("gpt-5.4-mini")

    assert "^[0-9a-f]{40}$" in text
    assert text.count('test "$REVIEWED_COMMIT_SHA" = "$DISPATCH_SHA"') == 2
    assert text.count('test "$(git rev-parse HEAD)" = "$REVIEWED_COMMIT_SHA"') == 2
    assert text.count("DISPATCH_SHA: ${{ github.sha }}") == 2
    assert "options:\n          - gpt-5.4-mini" in text
    assert policy.max_model_calls == 1
    assert policy.allowed_model_ids == ("gpt-5.4-mini",)
    assert "SIMORGH_CANARY" not in text
    assert "input_text" not in text


def test_live_workflow_runs_quality_before_secret_and_verifies_artifact() -> None:
    text = _workflow_text()

    assert "ruff check ." in text
    assert "mypy services/core/src" in text
    assert "test_live_provider_staging_artifact.py" in text
    assert "test_live_provider_staging_cli.py" in text
    assert "test_live_provider_staging_workflow.py" in text
    assert "live_provider_staging_cli run" in text
    assert "live_provider_staging_cli verify" in text
    assert "--require-passed" in text
    assert text.count("if: always()") == 2
    assert "if-no-files-found: error" in text
    assert "retention-days: 30" in text


def test_live_workflow_actions_and_direct_dependencies_are_pinned() -> None:
    text = _workflow_text()
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
    text = _CI_WORKFLOW.read_text(encoding="utf-8")

    assert "live_provider_staging_cli" not in text
    assert "AVALAI_API_KEY" not in text
    assert "live-provider-staging" not in text
