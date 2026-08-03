# Phase 1.9 protected-environment readiness audit

- Audit date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Repository visibility: public
- Default branch: `main`
- Pull request: #70
- Issue: #65
- Live workflow dispatches observed or initiated by this audit: `0`
- Credentials read or configured by this audit: `0`
- Real AvalAI/User API calls initiated by this audit: `0`
- Overall readiness: **NOT READY FOR LIVE DISPATCH**

Resolve the current branch Head and ordinary CI before using this audit. This
file never self-authorizes a live run.

## Audit method

Repository, PR, issue, changed-file and CI evidence were read through connected
GitHub repository tools. Official GitHub Actions documentation was used to
confirm:

- `workflow_dispatch` requires the workflow file on the default branch;
- reusable workflows can be referenced by exact SHA;
- the called workflow uses the caller-associated `github` context;
- an environment declared in a reusable workflow job uses its environment
  protection and environment secret;
- required reviewers, self-review prevention and branch/tag restrictions remain
  external GitHub settings.

The connector surface did not expose environment protection rules or secret
metadata. No unavailable setting was inferred from YAML.

## Selected bootstrap topology

```text
main
  .github/workflows/live-provider-staging-dispatch.yml
  trigger: workflow_dispatch only
  input: approved_dispatcher_sha only
  hardcoded worker SHA and model
  no secrets passed
    |
    v
exact reviewed worker commit
  .github/workflows/live-provider-staging.yml
  trigger: workflow_call only
  validates caller repository/ref/workflow path
  protected environment: live-provider-staging
  environment secret: AVALAI_API_KEY
```

The dispatcher must reach `main` through a separate bootstrap PR containing only
that file. The worker remains in PR #70 and is referenced by a full immutable
commit SHA.

## Verified repository evidence

| Evidence | Status | Observation |
|---|---|---|
| Repository access | VERIFIED | Repository is public and authenticated operator has admin access. |
| Default branch | VERIFIED | `main` |
| Phase branch | VERIFIED | `core/live-provider-staging` |
| PR state | VERIFIED | PR #70 is open, Draft and mergeable. |
| Issue state | VERIFIED | Issue #65 is open. |
| Previous exact-head CI | VERIFIED | Handoff Head `e62538d16e67dfee50fe01595a4d21a9e5be307b`, run #1040, Core and Android success. |
| Default-branch worker absence | VERIFIED | `.github/workflows/live-provider-staging.yml` returned 404 on `main` before bootstrap. |
| Worker trigger | VERIFIED | `workflow_call` only; no direct dispatch, push, PR or schedule. |
| Worker caller restriction | VERIFIED | Same repository, `refs/heads/main` and exact dispatcher workflow-ref checks. |
| Worker environment | VERIFIED | `live-provider-staging` appears only on `live-canary`. |
| Secret reference placement | VERIFIED | `AVALAI_API_KEY` appears once in the protected worker step. |
| Worker repository permissions | VERIFIED | `contents: read`. |
| Worker concurrency | VERIFIED | One non-cancelling `live-provider-staging` group. |
| Worker commit binding | VERIFIED | Exact lowercase SHA and checkout-HEAD equality. |
| Model binding | VERIFIED | Worker requires `gpt-5.4-mini`. |
| Pre-secret gates | VERIFIED | Ruff, strict MyPy and fake tests precede protected job. |
| Ordinary CI isolation | VERIFIED | Ordinary CI does not invoke live CLI or reference the key. |
| Live execution | NOT EXECUTED | No live workflow was dispatched. |

## Bootstrap evidence still required

| Prerequisite | Status | Required proof |
|---|---|---|
| Exact worker commit frozen | PENDING | Full SHA with green Core and Android CI. |
| Dispatcher exact-SHA pin | PENDING | Same worker SHA in `uses` and `reviewed_commit_sha`. |
| Dispatcher fixed model | PENDING | Hardcoded `gpt-5.4-mini`, no model input. |
| Dispatcher has no secret forwarding | PENDING | No `secrets` or `secrets: inherit`. |
| Bootstrap PR product diff | PENDING | Dispatcher file only. |
| Bootstrap PR CI | PENDING | Core and Android success. |
| Dispatcher merged to `main` | PENDING | Merge commit and file fetch from `main`. |
| Main/reviewed dispatcher blob equality | PENDING | Identical content/blob evidence. |
| Manual workflow enabled/visible | UNVERIFIED | Actions UI/API evidence without dispatch. |

Until the dispatcher is merged, the default-branch blocker remains active.

## Unverified external prerequisites

| Prerequisite | Status | Required proof before approval |
|---|---|---|
| Environment object exists | UNVERIFIED | Independent UI/API inspection showing exact name. |
| Required reviewers configured | UNVERIFIED | Reviewer list and policy from environment settings. |
| Self-review prevention enabled | UNVERIFIED | Environment protection setting. |
| Deployment restriction allows only `main` | UNVERIFIED | Selected branch/tag policy. |
| Environment secret exists | UNVERIFIED | Secret name and update timestamp; never value. |
| Secret is environment-scoped only | UNVERIFIED | No weaker duplicate relied upon. |
| Credential is active/restricted | UNVERIFIED | Provider administrative confirmation. |
| Provider account credit | UNVERIFIED | Reviewed preflight during approved run. |
| Model currently available | UNVERIFIED | Reviewed catalog preflight during approved run. |
| Independent deployment approval | UNVERIFIED | Pending environment approval on exact run. |
| Explicit user spend approval | NOT GRANTED | Both SHAs/ref/model/ceilings/timestamp. |

## Blocking findings

### B1 — dispatcher bootstrap is not yet on `main`

Status: **BLOCKING**

The selected topology is documented and the reusable worker boundary exists, but
the minimal dispatcher has not yet been merged to the default branch. A separate
zero-live-call bootstrap PR and green CI are required.

Forbidden workarounds remain:

- adding push, pull-request or schedule triggers;
- accepting worker SHA or model as dispatch inputs;
- using a branch/tag worker reference;
- forwarding repository/organization secrets;
- running a standalone provider script.

### B2 — environment protections are not observable

Status: **BLOCKING**

Workflow YAML does not prove environment, reviewer, self-review or deployment
restriction settings. Live approval is forbidden until independently verified.

### B3 — credential state is not observable

Status: **BLOCKING**

The connector cannot prove that `AVALAI_API_KEY` exists, is current,
environment-scoped or provider-valid. The secret value must never be retrieved.

### B4 — explicit live approval is absent

Status: **BLOCKING**

Approval to implement the bootstrap is not approval to execute a canary. Live
approval must identify exact dispatcher and worker SHAs, `refs/heads/main`, model
and maximum spend.

### B5 — no exact live transaction evidence exists

Status: **EXPECTED / BLOCKING FOR MERGE ACCEPTANCE**

No canary, provider request ID, exact transaction or sanitized live artifact
exists. Pending or unavailable reconciliation cannot satisfy issue #65.

## Readiness conclusion

```text
reusable worker design: REVIEWED CANDIDATE
ordinary fake CI: PREVIOUS HEAD GREEN; NEW HEAD REQUIRES VALIDATION
default-branch dispatcher: PENDING BOOTSTRAP PR
protected environment: UNVERIFIED
credential readiness: UNVERIFIED
explicit spend approval: NOT GRANTED
live acceptance: NOT EXECUTED
Phase 1.9 merge acceptance: NOT COMPLETE
```

No live workflow may be dispatched from this state.

## Permitted next actions

1. Freeze the exact reusable worker commit and pass full Core/Android CI.
2. Add the exact pinned dispatcher to PR #70 and static-test it.
3. Create a separate dispatcher-only bootstrap PR against `main`.
4. Pass ordinary CI, verify byte identity and merge the bootstrap without
   dispatching it.
5. Re-audit external environment prerequisites.
6. Request separate live approval only after all blockers are evidenced.
