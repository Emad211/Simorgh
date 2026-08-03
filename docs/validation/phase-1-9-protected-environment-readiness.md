# Phase 1.9 protected-environment readiness audit

- Audit timestamp: `2026-08-03T13:11+03:30`
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
- Audited PR #70 Head:
  `096890150c7cf129eab19ebf4ac0bdf05e631e2f`
- Audited PR merge-preview:
  `caf563792dfbcf65da6a32965d9479824bd9541a`
- Audited CI: run `30781540524`, run number `1054`, success
- Live dispatcher/worker runs initiated by this audit: `0`
- Deployment approvals performed by this audit: `0`
- Credentials configured, read or used by this audit: `0`
- Real AvalAI/User API calls initiated by this audit: `0`
- Overall readiness: **NOT READY FOR LIVE DISPATCH**
- Approval package status: **NOT PREPARED — NON-LIVE PREREQUISITES INCOMPLETE**

The default-branch topology blocker is resolved. This audit proves repository
state, immutable dispatcher/worker identity and full fake CI only. It does not
infer GitHub Actions state, environment protection or secret metadata from YAML.

## Audit method

The following sources were inspected without starting a workflow:

- repository metadata and default branch;
- `main` and phase-branch workflow files;
- PR #70 and Issue #65 state;
- PR conversation comments, submitted reviews and inline review threads;
- exact PR merge-preview and CI jobs/artifacts;
- the complete set of GitHub Connector operations exposed in this session;
- official GitHub Actions documentation for `workflow_dispatch`, reusable
  workflows, environments and environment secrets.

### Connector-surface result

The connected GitHub surface exposes repository files, commits, pull requests,
issues, review state, CI runs, jobs, logs and artifacts. It does **not** expose
read operations for:

- workflow metadata/state such as `active` or `disabled_manually`;
- repository deployment environments;
- required reviewer configuration;
- prevention-of-self-review configuration;
- environment deployment-branch policies;
- environment-secret names or update timestamps.

Therefore those settings cannot be proved in this execution. They remain
`UNVERIFIED`; absence of an endpoint is not evidence that a setting is absent.
The secret value was neither requested nor read.

## Implemented topology

```text
main @ 3bcb41437e3b8d2f497516ef9a214de5becf45e9
  .github/workflows/live-provider-staging-dispatch.yml
  blob a5fe7be975ee41dd0be222ab1c606f8b4bab87d7
  trigger: workflow_dispatch only
  input: approved_dispatcher_sha only
  worker SHA and model: hardcoded
  secrets forwarded: none
    |
    v
worker @ 47b65f359fd844067346d987f9102f6eeab911d9
  .github/workflows/live-provider-staging.yml
  trigger: workflow_call only
  validates caller repository/ref/workflow path
  protected environment name: live-provider-staging
  environment-secret reference: AVALAI_API_KEY
```

## Verified repository and CI evidence

| Evidence | Status | Observation |
|---|---|---|
| Repository access | VERIFIED | Repository is public; authenticated operator has admin access. |
| Default branch | VERIFIED | `main` |
| Current `main` bootstrap commit | VERIFIED | `3bcb41437e3b8d2f497516ef9a214de5becf45e9` |
| Phase branch | VERIFIED | `core/live-provider-staging` |
| PR #70 state | VERIFIED | Open, Draft and mergeable. |
| Issue #65 state | VERIFIED | Open. |
| PR #70 conversation comments | VERIFIED | Zero at audit time. |
| PR #70 submitted reviews | VERIFIED | Zero at audit time. |
| PR #70 inline review threads | VERIFIED | Zero at audit time. |
| PR #70 audited Head | VERIFIED | `096890150c7cf129eab19ebf4ac0bdf05e631e2f` |
| PR #70 merge-preview | VERIFIED | `caf563792dfbcf65da6a32965d9479824bd9541a` |
| Exact merge-preview CI | VERIFIED | Run #1054 (`30781540524`), Core and Android success. |
| Core quality | VERIFIED | Ruff passed; strict MyPy passed for 83 source files; 573 tests passed. |
| Android quality | VERIFIED | assembleDebug, JVM tests, lint and Debug APK upload passed. |
| Bootstrap PR product diff | VERIFIED | PR #72 added only the 49-line dispatcher. |
| Bootstrap PR CI | VERIFIED | Run #1050 (`30781058656`), Core and Android success. |
| Bootstrap merge | VERIFIED | PR #72 merged to `main` at `3bcb41437e3b8d2f497516ef9a214de5becf45e9`. |
| Dispatcher on default branch | VERIFIED | File fetch from `main` succeeded. |
| Dispatcher blob identity | VERIFIED | `main`, bootstrap branch and PR #70 copy use blob `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`. |
| Dispatcher trigger | VERIFIED | `workflow_dispatch` only. |
| Dispatcher input | VERIFIED | `approved_dispatcher_sha` only. |
| Dispatcher repository/ref binding | VERIFIED | Requires `Emad211/Simorgh`, `refs/heads/main` and approved SHA equal to `github.sha`. |
| Exact worker pin | VERIFIED | `47b65f359fd844067346d987f9102f6eeab911d9` is hardcoded in `uses` and `reviewed_commit_sha`. |
| Dispatcher model binding | VERIFIED | `gpt-5.4-mini` is hardcoded; no model input exists. |
| Dispatcher secret forwarding | VERIFIED | No `secrets` or `secrets: inherit`. |
| Worker trigger | VERIFIED | `workflow_call` only; no direct dispatch, push, PR or schedule. |
| Worker caller restriction | VERIFIED | Same repository, `main` and exact dispatcher workflow-ref checks. |
| Worker environment declaration | VERIFIED | `live-provider-staging` is declared on `live-canary`. |
| Secret reference placement | VERIFIED | `AVALAI_API_KEY` appears once in the protected worker step. |
| Worker permissions | VERIFIED | `contents: read`. |
| Worker concurrency | VERIFIED | One non-cancelling `live-provider-staging` group. |
| Worker commit/model binding | VERIFIED | Exact checkout SHA and `gpt-5.4-mini`. |
| Pre-secret gates | VERIFIED | Ruff, strict MyPy and fake tests precede the protected job. |
| Ordinary CI isolation | VERIFIED | Ordinary CI does not invoke the live CLI or reference the provider key. |
| Live execution | NOT EXECUTED | No dispatcher or worker live run was started. |

## Unverified external prerequisites

| Prerequisite | Status | Required proof before approval |
|---|---|---|
| Dispatcher workflow enabled/visible | UNVERIFIED | Actions UI or workflow-state API showing the dispatcher as enabled and visible; do not press Run workflow. |
| Environment object exists | UNVERIFIED | Independent UI/API inspection showing exact name `live-provider-staging`. |
| Required reviewers configured | UNVERIFIED | Reviewer list and required-review policy from environment settings. |
| Independent reviewer available | UNVERIFIED | A reviewer distinct from the dispatch actor. |
| Self-review prevention enabled | UNVERIFIED | Environment protection setting. |
| Deployment restriction allows only `main` | UNVERIFIED | Selected branch/tag policy allowing only `main`. |
| Environment secret exists | UNVERIFIED | Secret name `AVALAI_API_KEY` and update timestamp; never its value. |
| Secret is environment-scoped only | UNVERIFIED | Evidence that no repository/organization fallback is relied upon. |
| Credential is active/restricted | UNVERIFIED | Provider administrative confirmation without exposing value. |
| Provider account credit | UNVERIFIED | Reviewed preflight during an approved run. |
| Model currently available | UNVERIFIED | Reviewed catalog preflight during an approved run. |
| Independent deployment approval | UNVERIFIED | Pending environment approval on the exact future run. |
| Explicit user spend approval | NOT GRANTED | Exact dispatcher SHA, worker SHA, ref, model, ceilings and approval timestamp. |

## Approval-package decision

The conditional approval package was **not prepared** because all non-live
prerequisites were not proved. The following fixed values are retained only as a
future candidate identity, not as authorization:

```text
dispatcher_sha_on_main: 3bcb41437e3b8d2f497516ef9a214de5becf45e9
worker_sha: 47b65f359fd844067346d987f9102f6eeab911d9
ref: refs/heads/main
model: gpt-5.4-mini
max_model_calls: 1
max_input_tokens: 128
max_output_tokens: 16
max_estimated_cost_microusd: 20000
max_exact_cost: 0.01 UNIT
minimum_credit_floor: 0.10 UNIT
```

These values may become stale if `main`, the dispatcher, the worker or policy
changes. A future approval request must re-resolve and re-audit every value.

## Blocking findings

### B1 — dispatcher enabled/visibility state is unverified

The workflow file exists on `main`, but the available Connector cannot read its
Actions state. The audit did not press or submit the Run workflow form.

### B2 — environment protections are unverified

YAML cannot prove the environment object, required reviewer, self-review or
`main`-only deployment restriction.

### B3 — credential metadata is unverified

The Connector cannot list environment secrets. `AVALAI_API_KEY` name and update
time remain unproved; its value must never be retrieved.

### B4 — live approval is absent

Repository implementation, CI and this audit are not permission to execute.

### B5 — no exact live transaction evidence exists

No provider request, exact transaction or sanitized live artifact exists.
`pending` or `unavailable` reconciliation cannot satisfy issue #65.

## Readiness conclusion

```text
reusable worker: VERIFIED AND PINNED
default-branch dispatcher file/blob: VERIFIED
dispatcher enabled/visible: UNVERIFIED
protected environment object: UNVERIFIED
required reviewer: UNVERIFIED
self-review prevention: UNVERIFIED
deployment restriction main-only: UNVERIFIED
environment secret name/timestamp: UNVERIFIED
credential/provider readiness: UNVERIFIED
explicit spend approval: NOT GRANTED
approval package: NOT PREPARED
live acceptance: NOT EXECUTED
Phase 1.9 merge acceptance: NOT COMPLETE
```

No live workflow may be dispatched from this state.

## Permitted next actions

1. Use an authenticated GitHub UI/API surface that exposes workflow state,
   environment protection rules and environment-secret metadata without reading
   the secret value.
2. Record only the exact proven settings; leave anything unavailable
   `UNVERIFIED`.
3. Re-resolve `main`, worker and policy identities after any configuration or
   repository change.
4. Prepare an explicit approval package only after all non-live prerequisites
   are proven.
5. Ask the user for separate live approval; do not infer it from implementation
   work or this audit.
