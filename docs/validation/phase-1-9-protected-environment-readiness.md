# Phase 1.9 protected-environment readiness audit

- Audit date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Repository visibility: public
- Default branch: `main`
- Pull request: #70
- Issue: #65
- Audited implementation Head: `9326c29bbdaf804e7d3f9abd8902b0385edf7378`
- Audited CI: run `30776943802`, run number `1026`, success
- Live workflow dispatches observed or initiated by this audit: `0`
- Real AvalAI/User API calls initiated by this audit: `0`
- Overall readiness: **NOT READY FOR LIVE DISPATCH**

The current documentation commit is not self-referenced here. Resolve the final
branch Head and rerun ordinary CI after this audit is committed.

## Audit method

Repository, PR, issue, changed-file and CI evidence were read through the
connected GitHub repository tools. The available connector surface exposed
repository metadata, files, PR/issue state, reviews and workflow runs, but did
not expose deployment-environment protection rules or environment-secret
metadata.

GitHub's official Actions documentation was used to establish external
requirements:

- a manual `workflow_dispatch` workflow must exist on the default branch;
- jobs referencing an environment must satisfy its configured protection rules;
- environment secrets become available only to jobs referencing that
  environment and, when approval is required, only after approval;
- required reviewers, prevention of self-review and branch/tag restrictions are
  GitHub environment settings rather than repository-file state.

No unavailable setting was inferred from YAML or from the existence of a secret
reference.

## Verified repository evidence

| Evidence | Status | Observation |
|---|---|---|
| Repository access | VERIFIED | Repository is public and the authenticated operator has admin access. |
| Default branch | VERIFIED | `main` |
| Phase branch | VERIFIED | `core/live-provider-staging` |
| PR state | VERIFIED | PR #70 is open, Draft and mergeable. |
| Issue state | VERIFIED | Issue #65 is open. |
| Review comments | VERIFIED | No PR comments were present at audit time. |
| Review submissions | VERIFIED | No review submissions were present at audit time. |
| Inline review threads | VERIFIED | No inline review threads were present at audit time. |
| Exact-head CI | VERIFIED | Run #1026 passed Core and Android jobs. |
| Trigger | VERIFIED | `workflow_dispatch` only; no push, PR or schedule trigger. |
| Environment name in YAML | VERIFIED | `live-provider-staging` |
| Secret reference placement | VERIFIED | `AVALAI_API_KEY` appears once in the protected live step. |
| Repository permissions | VERIFIED | Workflow requests `contents: read`. |
| Concurrency | VERIFIED | One `live-provider-staging` group, active run is not cancelled. |
| Commit binding | VERIFIED | Input SHA must equal dispatch SHA and checkout SHA. |
| Model allowlist | VERIFIED | Only `gpt-5.4-mini`. |
| Pre-secret gates | VERIFIED | Ruff, strict MyPy and fake tests run before live job. |
| Ordinary CI isolation | VERIFIED | Ordinary CI does not invoke the live CLI or reference the key. |
| Artifact boundary | VERIFIED | Strict verification precedes sanitized artifact upload. |
| Live execution | NOT EXECUTED | No live workflow was dispatched. |

## Unverified external prerequisites

| Prerequisite | Status | Required proof before approval |
|---|---|---|
| Environment object exists | UNVERIFIED | GitHub Settings screenshot or independent UI/API inspection showing exact name. |
| Required reviewers configured | UNVERIFIED | Reviewer list and approval policy from environment settings. |
| Self-review prevention enabled | UNVERIFIED | Environment protection setting. |
| Deployment branch/tag restrictions | UNVERIFIED | Selected branch/tag policy matching the approved ref. |
| Environment secret exists | UNVERIFIED | Secret name and update timestamp; never the value. |
| Secret is environment-scoped only | UNVERIFIED | Check that no repository/organization duplicate is relied upon. |
| Credential is active and restricted | UNVERIFIED | Provider-side administrative confirmation without exposing value. |
| Provider account credit | UNVERIFIED | Reviewed preflight during an approved run. |
| Model currently available | UNVERIFIED | Reviewed dynamic catalog preflight during an approved run. |
| Workflow enabled in Actions | UNVERIFIED | GitHub Actions UI or workflow API status. |
| Independent deployment approval | UNVERIFIED | Pending deployment approval record on the exact run. |
| Explicit user spend approval | NOT GRANTED | Exact SHA/ref/model/ceilings and approval timestamp. |

## Blocking findings

### B1 — workflow is absent from the default branch

Status: **BLOCKING**

The repository default branch is `main`. The manual workflow is introduced by
PR #70 and is not present on `main`. GitHub requires a `workflow_dispatch`
workflow to exist on the default branch before manual dispatch is available.

Consequences:

- the current PR branch cannot yet satisfy its live acceptance gate through the
  intended GitHub UI/CLI/REST manual-dispatch surface;
- adding push, pull-request or schedule triggers is forbidden;
- executing a standalone provider script would bypass the reviewed environment
  and native authority boundary;
- a separately reviewed bootstrap/default-branch strategy is required.

This audit does not choose or implement that strategy because this increment is
limited to documentation and readiness evidence.

### B2 — environment protections are not observable

Status: **BLOCKING**

Workflow YAML naming `live-provider-staging` does not prove the environment,
reviewer, self-review or deployment-ref rules exist. Live approval is forbidden
until an operator independently verifies and records those controls.

### B3 — credential state is not observable

Status: **BLOCKING**

The connector cannot prove that `AVALAI_API_KEY` exists, is current, is scoped to
the environment or remains valid. The secret value must never be retrieved for
this audit.

### B4 — explicit live approval is absent

Status: **BLOCKING**

The user has not approved an exact live commit, ref, model and maximum spend.
Approval to build the boundary is not approval to execute it.

### B5 — no exact live transaction evidence exists

Status: **EXPECTED / BLOCKING FOR MERGE ACCEPTANCE**

No real canary, provider request ID, transaction lookup or sanitized live
artifact exists. Pending or unavailable reconciliation would not satisfy issue
#65 even after a run.

## Readiness conclusion

```text
repository implementation: READY FOR DOCUMENTED REVIEW
ordinary fake CI: GREEN
protected environment: UNVERIFIED
manual dispatchability: BLOCKED BY DEFAULT-BRANCH REQUIREMENT
credential readiness: UNVERIFIED
explicit spend approval: NOT GRANTED
live acceptance: NOT EXECUTED
Phase 1.9 merge acceptance: NOT COMPLETE
```

No live workflow may be dispatched from this state.

## Permitted next actions

1. Review and select a zero-live-call strategy that makes the reviewed workflow
   definition available on `main` without adding automatic triggers or weakening
   commit binding.
2. Configure and independently verify the GitHub environment, reviewer policy,
   self-review prevention, deployment-ref restriction and environment secret.
3. Re-run full Core and Android CI on the exact resulting Head.
4. Populate the live acceptance checklist.
5. Ask the user for separate explicit approval of exact SHA, ref, model and hard
   maximum spend.

Only after all five steps may an operator open the manual dispatch form.
