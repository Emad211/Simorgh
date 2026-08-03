# Phase 1.9 protected-environment readiness audit

- Audit timestamp: `2026-08-03T14:49+03:30`
- Repository: `Emad211/Simorgh`
- Repository visibility: public
- Authenticated repository permission: admin
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
  `901e858e3be6d92d9a64e1617fdcf972dec4c2c9`
- Audited PR merge-preview:
  `6cb97ab7263bb17f11699159e28b49795d2a99ec`
- Audited CI: run `30803363635`, run number `1059`, success
- Live dispatcher/worker runs initiated by this audit: `0`
- Deployment approvals performed by this audit: `0`
- Credentials configured, read or used by this audit: `0`
- Real AvalAI/User API calls initiated by this audit: `0`
- Overall readiness: **NOT READY FOR LIVE DISPATCH**
- Approval package status: **NOT PREPARED — NON-LIVE PREREQUISITES INCOMPLETE**

The default-branch topology blocker remains resolved. This audit proves current
repository state, immutable dispatcher/worker identity and full fake CI only. It
does not infer GitHub Actions state, Environment protection or secret metadata
from workflow YAML.

## Audit method

The following authenticated sources were inspected without starting a workflow:

- repository metadata, permissions and default branch;
- dispatcher content and blob identity on `main`;
- phase-branch worker and policy files;
- PR #70 and Issue #65 state;
- PR conversation comments, submitted reviews and inline review threads;
- exact PR merge-preview and its CI jobs/artifacts;
- the complete GitHub Connector operation surface exposed in this session.

### Authenticated Connector result

The authenticated GitHub Connector confirms repository admin access and exposes
repository files, commits, pull requests, issues, review state, CI runs, jobs,
logs and artifacts. A full resource discovery was repeated at this audit time.
It does **not** expose read operations for:

- workflow metadata/state such as `active` or `disabled_manually`;
- repository deployment Environment objects;
- required reviewer configuration;
- prevention-of-self-review configuration;
- Environment deployment branch/tag policies;
- Environment-secret names or update timestamps;
- repository or organization secret-name inventories needed to prove that no
  weaker fallback is relied upon.

Therefore those settings cannot be proved in this execution and remain
`UNVERIFIED`. Absence of a Connector endpoint is not evidence that a setting is
absent. The secret value was neither requested nor read.

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
  protected Environment name: live-provider-staging
  Environment-secret reference: AVALAI_API_KEY
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
| PR #70 audited Head | VERIFIED | `901e858e3be6d92d9a64e1617fdcf972dec4c2c9` |
| PR #70 merge-preview | VERIFIED | `6cb97ab7263bb17f11699159e28b49795d2a99ec` |
| Exact merge-preview CI | VERIFIED | Run #1059 (`30803363635`), Core and Android success. |
| Core quality | VERIFIED | Ruff passed; strict MyPy passed for 83 source files; 575 tests passed. |
| Android quality | VERIFIED | assembleDebug, JVM tests, lint and Debug APK upload passed. |
| Bootstrap PR product diff | VERIFIED | PR #72 added only the 49-line dispatcher. |
| Bootstrap merge | VERIFIED | PR #72 merged to `main` at `3bcb41437e3b8d2f497516ef9a214de5becf45e9`. |
| Dispatcher on default branch | VERIFIED | Authenticated file fetch from `main` succeeded. |
| Dispatcher blob identity | VERIFIED | Blob is `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`. |
| Dispatcher trigger | VERIFIED | `workflow_dispatch` only. |
| Dispatcher input | VERIFIED | `approved_dispatcher_sha` only. |
| Dispatcher repository/ref binding | VERIFIED | Requires `Emad211/Simorgh`, `refs/heads/main` and approved SHA equal to `github.sha`. |
| Exact worker pin | VERIFIED | `47b65f359fd844067346d987f9102f6eeab911d9` is hardcoded in `uses` and `reviewed_commit_sha`. |
| Dispatcher model binding | VERIFIED | `gpt-5.4-mini` is hardcoded; no model input exists. |
| Dispatcher secret forwarding | VERIFIED | No `secrets` or `secrets: inherit`. |
| Worker trigger | VERIFIED | `workflow_call` only; no direct dispatch, push, PR or schedule. |
| Worker caller restriction | VERIFIED | Same repository, `main` and exact dispatcher workflow-ref checks. |
| Worker Environment declaration | VERIFIED | `live-provider-staging` is declared on `live-canary`. |
| Secret reference placement | VERIFIED | `AVALAI_API_KEY` appears once in the protected worker step. |
| Worker permissions | VERIFIED | `contents: read`. |
| Worker concurrency | VERIFIED | One non-cancelling `live-provider-staging` group. |
| Pre-secret gates | VERIFIED | Ruff, strict MyPy and fake tests precede the protected job. |
| Ordinary CI isolation | VERIFIED | Ordinary CI does not invoke the live CLI or reference the provider key. |
| Live execution | NOT EXECUTED | No dispatcher or worker live run was started. |

## Unverified external prerequisites

| Prerequisite | Status | Required proof before approval |
|---|---|---|
| Dispatcher workflow enabled/visible | UNVERIFIED | Authenticated Actions UI or workflow-state API showing enabled and visible; do not press Run workflow. |
| Environment object exists | UNVERIFIED | Authenticated UI/API showing exact name `live-provider-staging`. |
| Required reviewers configured | UNVERIFIED | Reviewer list and required-review policy from Environment settings. |
| Independent reviewer available | UNVERIFIED | A reviewer distinct from the dispatch actor. |
| Self-review prevention enabled | UNVERIFIED | Environment protection setting. |
| Deployment restriction allows only `main` | UNVERIFIED | Selected branch/tag policy allowing only `main`. |
| Environment secret exists | UNVERIFIED | Secret name `AVALAI_API_KEY` and update timestamp; never its value. |
| Secret is Environment-scoped only | UNVERIFIED | Evidence that no repository/organization fallback is relied upon. |
| Credential is active/restricted | UNVERIFIED | Provider administrative confirmation without exposing value. |
| Provider account credit | UNVERIFIED | Reviewed preflight during an approved run. |
| Model currently available | UNVERIFIED | Reviewed catalog preflight during an approved run. |
| Independent deployment approval | UNVERIFIED | Pending Environment approval on the exact future run. |
| Explicit user spend approval | NOT GRANTED | Exact dispatcher SHA, worker SHA, ref, model, ceilings and approval timestamp. |

## Approval-package decision

The conditional approval package was **not prepared** because all non-live
prerequisites were not proved. These fixed values are retained only as a future
candidate identity, not as authorization:

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

These values may become stale if `main`, the dispatcher, worker, policy or
GitHub configuration changes. A future approval request must re-resolve and
re-audit every value.

## Blocking findings

### B1 — dispatcher enabled/visibility state is unverified

The workflow file exists on `main`, but the authenticated Connector cannot read
its Actions state. The audit did not press or submit the Run workflow form.

### B2 — Environment protections are unverified

YAML cannot prove the Environment object, required reviewer, self-review or
`main`-only deployment restriction, and the connected surface exposes no read
endpoint for those settings.

### B3 — credential metadata is unverified

The Connector cannot list Environment secrets. `AVALAI_API_KEY` name and update
time remain unproved; its value must never be retrieved.

### B4 — weaker secret fallback cannot be disproved

The connected surface does not list repository/organization secret names, so the
audit cannot prove that no weaker fallback exists or is relied upon.

### B5 — live approval is absent

Repository implementation, CI and this audit are not permission to execute.

### B6 — no exact live transaction evidence exists

No provider request, exact transaction or sanitized live artifact exists.
`pending` or `unavailable` reconciliation cannot satisfy issue #65.

## Readiness conclusion

```text
reusable worker: VERIFIED AND PINNED
default-branch dispatcher file/blob: VERIFIED
dispatcher enabled/visible: UNVERIFIED
protected Environment object: UNVERIFIED
required reviewer: UNVERIFIED
self-review prevention: UNVERIFIED
deployment restriction main-only: UNVERIFIED
Environment secret name/timestamp: UNVERIFIED
weaker secret fallback absent: UNVERIFIED
credential/provider readiness: UNVERIFIED
explicit spend approval: NOT GRANTED
approval package: NOT PREPARED
live acceptance: NOT EXECUTED
Phase 1.9 merge acceptance: NOT COMPLETE
```

No live workflow may be dispatched from this state.

## Permitted next actions

1. Use an authenticated GitHub UI/API surface that exposes workflow state,
   Environment protection rules and Environment-secret metadata without reading
   the secret value.
2. Record only exact proved settings; leave anything unavailable `UNVERIFIED`.
3. Re-resolve `main`, worker and policy identities after any configuration or
   repository change.
4. Prepare an explicit approval package only after all non-live prerequisites
   are proved.
5. Ask the user for separate live approval; do not infer it from implementation
   work or this audit.
