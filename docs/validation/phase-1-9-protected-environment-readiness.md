# Phase 1.9 protected-environment readiness audit

- Audit date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Repository visibility: public
- Default branch: `main`
- Pull request: #70
- Issue: #65
- Bootstrap pull request: #72 — merged
- Bootstrap merge commit on `main`:
  `3bcb41437e3b8d2f497516ef9a214de5becf45e9`
- Reviewed reusable worker commit:
  `47b65f359fd844067346d987f9102f6eeab911d9`
- Dispatcher blob SHA: `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`
- Live workflow dispatches observed or initiated by this audit: `0`
- Credentials read or configured by this audit: `0`
- Real AvalAI/User API calls initiated by this audit: `0`
- Overall readiness: **NOT READY FOR LIVE DISPATCH**

The default-branch topology blocker is resolved. This audit still does not prove
that the workflow is enabled in Actions, that the protected environment is
configured, or that any credential exists.

## Audit method

Repository, PR, issue, changed-file and CI evidence were read through connected
GitHub tools. Official GitHub Actions documentation was used to confirm:

- `workflow_dispatch` requires the workflow file on the default branch;
- reusable workflows can be referenced by exact SHA;
- the called workflow uses the caller-associated `github` context;
- an environment declared in a reusable workflow job uses its environment
  protection and environment secret;
- required reviewers, self-review prevention and branch/tag restrictions remain
  external GitHub settings.

The connector did not expose workflow enabled/disabled state, environment
protection rules or secret metadata. No unavailable setting was inferred.

## Implemented topology

```text
main @ 3bcb41437e3b8d2f497516ef9a214de5becf45e9
  .github/workflows/live-provider-staging-dispatch.yml
  blob a5fe7be975ee41dd0be222ab1c606f8b4bab87d7
  trigger: workflow_dispatch only
  input: approved_dispatcher_sha only
  hardcoded worker SHA and model
  no secrets passed
    |
    v
worker @ 47b65f359fd844067346d987f9102f6eeab911d9
  .github/workflows/live-provider-staging.yml
  trigger: workflow_call only
  validates caller repository/ref/workflow path
  protected environment: live-provider-staging
  environment secret: AVALAI_API_KEY
```

## Verified repository evidence

| Evidence | Status | Observation |
|---|---|---|
| Repository access | VERIFIED | Repository is public and authenticated operator has admin access. |
| Default branch | VERIFIED | `main` |
| Phase branch | VERIFIED | `core/live-provider-staging` |
| PR #70 state | VERIFIED | Open, Draft and mergeable before final documentation update. |
| Issue #65 state | VERIFIED | Open. |
| Review audit | VERIFIED | No PR #70 comments, review submissions or inline threads at audit time. |
| Previous Handoff CI | VERIFIED | `e62538d16e67dfee50fe01595a4d21a9e5be307b`, run #1040, Core/Android success. |
| Reusable worker CI | VERIFIED | `47b65f359fd844067346d987f9102f6eeab911d9`, run #1047 (`30780786562`), Core/Android success. |
| Dispatcher candidate CI | VERIFIED | PR #70 Head `adfae44756de11e1e4372dbf2838402f01681b5b`, run #1049 (`30780907144`), Core/Android success. |
| Bootstrap PR product diff | VERIFIED | PR #72 contained one added file only: dispatcher, 49 lines. |
| Bootstrap PR CI | VERIFIED | Head `7f8ad3bc7c3eaac1286adf577823a9cd99a2a3c2`, run #1050 (`30781058656`), Core/Android success. |
| Bootstrap merge | VERIFIED | PR #72 merged to `main` at `3bcb41437e3b8d2f497516ef9a214de5becf45e9`. |
| Dispatcher on default branch | VERIFIED | File fetch from `main` succeeded. |
| Dispatcher blob identity | VERIFIED | `main`, bootstrap branch and PR #70 copy use blob `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`. |
| Dispatcher trigger | VERIFIED | `workflow_dispatch` only. |
| Dispatcher input | VERIFIED | `approved_dispatcher_sha` only. |
| Dispatcher repository/ref binding | VERIFIED | Requires `Emad211/Simorgh`, `refs/heads/main` and approval SHA equal to `github.sha`. |
| Exact worker pin | VERIFIED | Same worker SHA in `uses`, `reviewed_commit_sha` and review constant. |
| Dispatcher model binding | VERIFIED | Hardcoded `gpt-5.4-mini`, no model input. |
| Dispatcher secret forwarding | VERIFIED | No `secrets` or `secrets: inherit`. |
| Worker trigger | VERIFIED | `workflow_call` only; no direct dispatch, push, PR or schedule. |
| Worker caller restriction | VERIFIED | Same repository, `main` and exact dispatcher workflow-ref checks. |
| Worker environment | VERIFIED | `live-provider-staging` appears on `live-canary`. |
| Secret reference placement | VERIFIED | `AVALAI_API_KEY` appears once in protected worker step. |
| Worker permissions | VERIFIED | `contents: read`. |
| Worker concurrency | VERIFIED | Non-cancelling `live-provider-staging` group. |
| Worker commit/model binding | VERIFIED | Exact checkout SHA and `gpt-5.4-mini`. |
| Pre-secret gates | VERIFIED | Ruff, strict MyPy and fake tests precede protected job. |
| Ordinary CI isolation | VERIFIED | Ordinary CI does not invoke live CLI or reference key. |
| Live execution | NOT EXECUTED | No dispatcher or worker live run was started. |

## Unverified external prerequisites

| Prerequisite | Status | Required proof before approval |
|---|---|---|
| Dispatcher workflow enabled/visible | UNVERIFIED | Actions UI or workflow API status; do not dispatch. |
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

## Resolved finding

### R1 — default-branch `workflow_dispatch` topology

Status: **RESOLVED IN REPOSITORY STATE**

PR #72 merged the minimal dispatcher to `main`. The dispatcher is byte-identical
to the statically tested PR #70 copy and pins the reviewed worker by exact SHA.
It has no automatic trigger and passes no secrets.

This resolution proves file placement and integrity only. It is not evidence that
the workflow is enabled, that environment protections exist or that live
execution is authorized.

## Remaining blocking findings

### B1 — workflow enabled/visibility state is not observable

Status: **BLOCKING**

The connector can fetch the workflow file from `main` but cannot prove GitHub
Actions currently reports it as enabled or exposes the Run workflow button.
Verify this without pressing the button.

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

Bootstrap implementation/merge is not permission to execute. Approval must bind
current `main` dispatcher SHA, pinned worker SHA, `refs/heads/main`, model and
maximum spend.

### B5 — no exact live transaction evidence exists

Status: **EXPECTED / BLOCKING FOR MERGE ACCEPTANCE**

No canary, provider request ID, exact transaction or sanitized live artifact
exists. Pending or unavailable reconciliation cannot satisfy issue #65.

## Readiness conclusion

```text
reusable worker: VERIFIED AND PINNED
default-branch dispatcher: VERIFIED PRESENT AND BYTE-IDENTICAL
bootstrap ordinary CI: GREEN
current PR #70 final Head CI: REQUIRES RERUN AFTER DOCUMENTATION UPDATE
dispatcher enabled/visible: UNVERIFIED
protected environment: UNVERIFIED
credential readiness: UNVERIFIED
explicit spend approval: NOT GRANTED
live acceptance: NOT EXECUTED
Phase 1.9 merge acceptance: NOT COMPLETE
```

No live workflow may be dispatched from this state.

## Permitted next actions

1. Verify dispatcher enabled/visible state without starting a run.
2. Configure and independently verify environment, reviewer, self-review policy,
   `main` deployment restriction and environment secret metadata.
3. Re-run full Core and Android CI on final PR #70 Head.
4. Populate the acceptance checklist with current evidence.
5. Ask the user for separate explicit live approval only after all non-live
   prerequisites are satisfied.
