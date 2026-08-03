# Development Handoff

## Current snapshot

- Date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Base branch: `main`
- Working branch: `core/live-provider-staging`
- Merge base: `a76b5aee006a1ac9dfe54080d02cb54fceef8bde`
- Pull request: #70 — `Core: establish budgeted AvalAI staging policy and User API boundary`
- Pull request state: open, Draft and mergeable
- Issue: #65 — `Phase 1 Step 1.9: explicitly budgeted AvalAI live-provider staging`
- Issue state: open
- Phase: 1.9 — Live Provider Staging
- Protected manual execution-boundary Head:
  `8ff42c2fb94c9342df59953725c96a8c04760dff`
- Operational documentation/readiness product Head:
  `3aa426b50688ed1ce63693def278d0a05e16daa5`
- Exact product validation:
  CI run `30778245280`, run number `1039`, success
- Current operational readiness: **NOT READY FOR LIVE DISPATCH**
- Live workflow dispatches initiated by this work: `0`
- Credentials read or used by this work: `0`
- Real AvalAI model requests initiated by this work: `0`
- Real AvalAI User API requests initiated by this work: `0`

The current Handoff commit is the branch `HEAD`; resolve its SHA from Git before
starting the next execution. Do not write an assumed self-referential SHA.

## Governing invariants

Simorgh remains authoritative for Task and Invocation identity, durable state,
budget, usage, replay, privacy and execution. Trace is an immutable audit
projection and cannot authorize execution or rewrite Invocation truth.

Phase 1.9 continues to require:

- ordinary Core runtime and ordinary CI remain fake and zero-external;
- one staging run permits at most one model request;
- no provider/model/domain failover, streaming, tools or automatic retry;
- fixed Core-authored canary content only;
- exact replay adds zero provider, catalog, credit or transaction calls and zero
  committed usage;
- provider transport uncertainty remains durable `unknown` and never authorizes
  a replacement request;
- exact transaction data is billing evidence only and cannot rewrite Invocation
  truth;
- pending or unavailable reconciliation is incomplete, never zero cost;
- raw prompt/output, credentials, headers, IP addresses, API-key suffixes,
  cookies, raw HTTP bodies and environment dumps never enter stores, logs or
  uploaded artifacts;
- live execution requires a protected GitHub environment and separate explicit
  user approval bound to exact commit, ref, model and hard maximum spend.

## Completed operational documentation increment

### ADR 0022

`docs/adr/0022-explicitly-budgeted-live-provider-staging.md` is accepted and
records:

- `workflow_dispatch` as the only live entry;
- protected environment `live-provider-staging`;
- environment secret `AVALAI_API_KEY`;
- exact commit/ref/model/spend approval identity;
- one-call, zero-retry and zero-failover semantics;
- fixed reviewed limits;
- bounded same-request-ID User API reconciliation only;
- exact reconciliation as the merge acceptance requirement;
- sanitized artifact authority;
- external environment state as explicitly unverified;
- the default-branch manual-dispatch blocker;
- rejection of push/schedule triggers, generic provider scripts and any bypass
  of Task, Invocation, Trace or environment authority.

### Operator runbook

`docs/LIVE_PROVIDER_STAGING_RUNBOOK.md` now covers:

- GitHub environment creation;
- independent required reviewer and self-review prevention;
- selected branch/tag deployment restrictions;
- environment-secret setup and safe credential handling;
- exact commit/ref/model/cost review;
- manual dispatch and pending-deployment review;
- artifact download and local verifier usage;
- interpretation of exact, pending, unavailable, mismatch and unknown states;
- suspected duplicate-charge response;
- unknown Invocation and cancellation response;
- cost mismatch and ceiling-exceeded response;
- credential leak and artifact privacy incidents;
- credential rotation;
- workflow/run emergency disablement;
- post-run sanitized evidence recording.

The emergency controls include:

```text
gh workflow disable live-provider-staging.yml
gh run cancel <RUN_ID>
```

Cancellation or workflow disablement does not prove that a provider request did
not enter. The same provider request ID remains the only permitted reconciliation
identity.

### Protected-environment readiness audit

`docs/validation/phase-1-9-protected-environment-readiness.md` separates verified
repository evidence from external operational state.

Verified in repository evidence:

- default branch is `main`;
- PR #70 is open, Draft and mergeable;
- Issue #65 is open;
- no PR comments, submitted reviews or inline review threads existed at audit
  time;
- workflow trigger is `workflow_dispatch` only;
- workflow environment name is `live-provider-staging`;
- the secret reference appears once in the protected live step;
- exact SHA binding, one-model allowlist, read-only permissions, single
  concurrency and pre-secret fake gates remain present;
- ordinary CI does not invoke the live CLI or reference the live credential;
- exact-head Core and Android CI are green.

Explicitly unverified external prerequisites:

- environment object existence;
- required reviewer configuration;
- prevention of self-review;
- deployment branch/tag restrictions;
- environment-secret presence, scope and update time;
- provider credential validity or provider-side restriction;
- account credit and current model availability;
- workflow enabled state;
- independent deployment approval;
- explicit user authorization for exact live spend.

No unavailable setting is inferred from workflow YAML.

### Live-acceptance checklist

`docs/validation/phase-1-9-live-acceptance-checklist.md` locks the reviewed
values:

```text
provider_id: avalai
api_base_url: https://api.avalai.ir/v1
user_api_base_url: https://api.avalai.ir/user/v1
model_id: gpt-5.4-mini
max_model_calls: 1
max_retries: 0
max_parallel_branches: 1
max_input_tokens: 128
max_output_tokens: 16
max_estimated_cost_microusd: 20000
max_exact_cost_unit: 0.01 UNIT
minimum_credit_floor_unit: 0.10 UNIT
max_elapsed_ms: 60000
transaction_poll_attempts: 6
transaction_poll_interval_ms: 5000
user_api_timeout_ms: 10000
user_api_max_response_bytes: 256000
artifact_retention_days: 30
```

It contains exact fields for commit/ref/user approval, environment evidence,
dispatch evidence, pre-secret gates, live result acceptance, stop conditions and
post-run sanitized evidence. No checkbox is pre-authorized.

## Critical readiness finding

### Default-branch manual-dispatch blocker

GitHub requires a workflow using `workflow_dispatch` to exist on the repository
default branch before it can be manually dispatched. The Simorgh default branch
is `main`, but `.github/workflows/live-provider-staging.yml` currently exists
only in PR #70.

Therefore:

```text
implementation boundary: validated
ordinary fake CI: green
manual dispatchability: blocked
protected environment: unverified
credential readiness: unverified
explicit spend approval: not granted
live acceptance: not executed
Phase 1.9 merge acceptance: incomplete
```

This increment does not bypass the blocker. It adds no push, pull-request or
schedule trigger, no standalone provider script and no weaker credential path.
A separately reviewed zero-live-call default-branch/bootstrap topology is the
next required engineering decision.

Official GitHub references retained by the runbook and ADR:

- `https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow`
- `https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments`
- `https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments`
- `https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows`
- `https://docs.github.com/en/actions/how-tos/manage-workflow-runs/cancel-a-workflow-run`

## Files changed by this increment

The exact product diff from previous Handoff Head
`9326c29bbdaf804e7d3f9abd8902b0385edf7378` to product Head
`3aa426b50688ed1ce63693def278d0a05e16daa5` contains exactly seven paths:

- `.github/workflows/live-provider-staging.yml`
- `docs/LIVE_PROVIDER_STAGING_RUNBOOK.md`
- `docs/adr/0022-explicitly-budgeted-live-provider-staging.md`
- `docs/validation/phase-1-9-live-acceptance-checklist.md`
- `docs/validation/phase-1-9-protected-environment-readiness.md`
- `services/core/tests/test_live_provider_staging_documentation.py`
- `services/core/tests/test_live_provider_staging_workflow.py`

The final Handoff update adds only `docs/DEVELOPMENT_HANDOFF.md` to that product
diff. No provider runtime, policy, model gateway, credential, generated database,
WAL/SHM, patcher or diagnostic helper was changed.

## Static test coverage

Six new documentation-contract tests now prove:

- ADR, runbook, readiness audit and checklist cross-link correctly;
- ADR retains manual-only, exact-identity, no-retry and zero-external controls;
- runbook values match the executable reviewed policy;
- readiness remains fail-closed while environment/reviewer/secret evidence is
  unavailable;
- checklist values match the executable policy and reject pending, unavailable,
  mismatch and unknown acceptance;
- documentation-contract tests run in the workflow pre-secret gate.

The existing workflow static tests additionally require the new documentation
suite before the protected live job.

## Validation evidence

Exact product validation:

```text
Product Head: 3aa426b50688ed1ce63693def278d0a05e16daa5
Workflow: CI
Run ID: 30778245280
Run number: 1039
Conclusion: success
core-quality: success
android-quality: success
Ruff: all checks passed
strict MyPy: no issues in 83 source files
Core: 570 passed, 2 dependency warnings, 12.41s
Android assembleDebug: passed
Android testDebugUnitTest: passed
Android lintDebug: passed
Android build: BUILD SUCCESSFUL in 21s
Android tasks: 53 actionable, 24 executed, 29 from cache
Debug APK upload: passed
live workflow dispatches initiated: zero
credential use: zero
real AvalAI/User API calls: zero
```

Artifacts from run `30778245280`:

- `core-quality-diagnostics` — ID `8842786257`,
  SHA-256 `8eb2be3ed6ce5d6a94815d85ee2b117eea8d05e61b6de3f32822519c45c10c4e`
- `core-test-report` — ID `8842786502`,
  SHA-256 `df32e4ecb611e1aef1273c77c49795b1695b21bd61510e1080115360954d407d`
- `android-build-diagnostics` — ID `8842789937`,
  SHA-256 `b9939762f8a098ab37e1f93c688edd1f8f0914fc9736b504c24b08c9cef0bcc9`
- `simorgh-android-debug` — ID `8842790422`,
  SHA-256 `374a0e644481449ca159154c6762aa56f5ea7cb9eba50a6fe40a9ae7f2fa422b`

Several intermediate candidate runs failed only on brittle Markdown-string
assertions in the new static documentation suite. Runtime code and live controls
were unchanged. The final tests normalize formatting and validate stable
semantics; the exact final product run above is fully green.

## Risks and blockers

1. **Default-branch blocker:** the manual workflow is not yet present on `main`.
2. **Environment evidence:** environment/reviewer/self-review/ref restrictions
   cannot be proven by the current repository connector surface.
3. **Credential evidence:** secret presence and provider validity are unverified.
4. **Approval:** no exact commit/ref/model/spend live approval has been granted.
5. **No live evidence:** no provider request ID, exact transaction or sanitized
   live artifact exists yet.
6. **Public repository:** environment protection capabilities and reviewer rules
   may depend on GitHub plan and repository settings and must be checked in the
   actual UI/API.
7. **Acceptance remains exact:** pending or unavailable transaction evidence
   cannot satisfy the Phase 1.9 merge gate.

## Remaining Phase 1.9 work

1. Resolve the default-branch/manual-dispatch bootstrap topology without adding
   automatic triggers or weakening exact SHA/environment/secret controls.
2. Configure and independently verify the protected environment and secret.
3. Populate the live-acceptance checklist with current evidence.
4. Obtain separate explicit user approval for exact commit, ref, model and hard
   maximum spend.
5. Dispatch one protected canary, obtain exact reconciliation and prove
   zero-call/zero-charge replay.
6. Record sanitized live evidence, complete review audit and merge PR #70.

## Mandatory reads for the next execution

- `docs/DEVELOPMENT_HANDOFF.md`
- `docs/SIMORGH_MASTER_DIRECTIVE.md`
- `docs/IMPLEMENTATION_MASTER_PLAN.md`
- `docs/CANCELLATION_PROPAGATION.md`
- `docs/TRACE_AUTHORITY.md`
- `docs/adr/0022-explicitly-budgeted-live-provider-staging.md`
- `docs/LIVE_PROVIDER_STAGING_RUNBOOK.md`
- `docs/validation/phase-1-9-live-provider-staging-start.md`
- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `docs/validation/phase-1-9-manual-staging-boundary.md`
- `docs/validation/phase-1-9-protected-environment-readiness.md`
- `docs/validation/phase-1-9-live-acceptance-checklist.md`
- `.github/workflows/live-provider-staging.yml`
- `.github/workflows/ci.yml`
- `.github/constraints/live-provider-staging.txt`
- `services/core/src/simorgh_core/agents/live_provider_staging.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_artifact.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_cli.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_trace.py`
- `services/core/src/simorgh_core/agents/model_gateway.py`
- `services/core/src/simorgh_core/providers/avalai.py`
- `services/core/src/simorgh_core/providers/avalai_user_api.py`
- `services/core/tests/test_live_provider_staging_artifact.py`
- `services/core/tests/test_live_provider_staging_cli.py`
- `services/core/tests/test_live_provider_staging_documentation.py`
- `services/core/tests/test_live_provider_staging_workflow.py`

Also inspect all PR #70 comments, review submissions, inline review threads,
changed files and checks created after product Head
`3aa426b50688ed1ce63693def278d0a05e16daa5`.

## Exact continuation point

First resolve the current branch Head and verify the full Core and Android CI
triggered by this Handoff update. If either gate is not green, inspect and fix
only that exact failure before changing production files.

Then perform one narrow **zero-live-call Phase 1.9 bootstrap-topology increment**
to resolve the default-branch `workflow_dispatch` blocker:

- verify the current GitHub default-branch/manual-dispatch semantics against
  official documentation and repository behavior;
- compare fail-closed topology options for making the reviewed workflow
  definition available on `main` before the Phase 1.9 canary, including a
  separately reviewed bootstrap PR;
- select the smallest option that keeps `workflow_dispatch` as the only trigger,
  keeps `AVALAI_API_KEY` environment-scoped, preserves exact SHA/ref/model/cost
  binding, and cannot make a provider request from an unreviewed commit;
- implement only the selected bootstrap/default-branch boundary and its static
  tests;
- update ADR 0022, runbook, readiness audit and checklist to match the selected
  topology;
- run all Core and Android gates;
- record exact SHA, CI, artifacts, remaining environment prerequisites and the
  next continuation point in this Handoff.

Do not dispatch a workflow, configure or read a credential, approve a deployment,
make an AvalAI/User API call, add push/pull-request/schedule triggers, or weaken
one-call/no-retry/exact-reconciliation semantics in that increment.
