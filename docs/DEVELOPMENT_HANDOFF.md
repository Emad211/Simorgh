# Development Handoff

## Current snapshot

- Date: 2026-08-03
- Audit time: `2026-08-03T13:11+03:30`
- Repository: `Emad211/Simorgh`
- Default/base branch: `main`
- Audited `main` commit:
  `3bcb41437e3b8d2f497516ef9a214de5becf45e9`
- Working branch: `core/live-provider-staging`
- Pull request: #70 — `Core: establish budgeted AvalAI staging policy and User API boundary`
- Pull request state at audit start: open, Draft and mergeable
- Issue: #65 — `Phase 1 Step 1.9: explicitly budgeted AvalAI live-provider staging`
- Issue state: open
- Bootstrap pull request: #72 — merged
- Phase: 1.9 — Live Provider Staging
- Default-branch dispatcher blob:
  `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`
- Reviewed reusable-worker commit:
  `47b65f359fd844067346d987f9102f6eeab911d9`
- Non-live settings-audit product Head:
  `ae2bc640226da8a117174f70530483c67b03a2c4`
- Product merge-preview validated by CI:
  `6d08d271e5c0f242b288e43fd442a7a772ada549`
- Product CI: run `30803084979`, number `1058`, success
- Operational readiness: **NOT READY FOR LIVE DISPATCH**
- Approval package: **NOT PREPARED**
- Live dispatcher/worker runs initiated by this work: `0`
- Deployment approvals performed by this work: `0`
- Credentials configured, read or used by this work: `0`
- Real AvalAI model requests initiated by this work: `0`
- Real AvalAI User API requests initiated by this work: `0`

The current Handoff commit is the working-branch `HEAD`; resolve its SHA before
starting the next execution. Do not write an assumed self-referential SHA.

## Governing invariants

Simorgh remains authoritative for Task and Invocation identity, durable state,
budget, usage, replay, privacy and execution. Trace is immutable audit evidence;
it cannot authorize execution or rewrite Invocation truth.

Phase 1.9 continues to require:

- ordinary Core runtime and ordinary CI are fake and zero-external;
- only the manual dispatcher on `main` may enter the live staging topology;
- exactly one provider model request is permitted;
- no automatic retry, provider/model/domain failover, streaming, tools or
  connector calls;
- the canary is fixed and Core-authored;
- worst-case usage is reserved before provider entry;
- uncertain provider entry remains durable `unknown` and cannot authorize a
  replacement request;
- exact replay adds zero provider, catalog, credit or transaction calls and zero
  committed usage;
- after model entry only the same provider request ID may be queried through the
  bounded User API reconciliation path;
- pending or unavailable reconciliation is incomplete and never zero cost;
- exact transaction evidence is billing evidence only;
- prompt/output text, credentials, authorization headers, cookies, IP addresses,
  API-key suffixes, safety identifiers, raw HTTP bodies and environment dumps
  never enter stores, logs or uploaded artifacts;
- live execution requires independently proved GitHub Environment protection and
  a separate explicit user approval bound to exact dispatcher SHA, worker SHA,
  ref, model and hard spend ceilings.

## Implemented live-staging topology

```text
main @ 3bcb41437e3b8d2f497516ef9a214de5becf45e9
  .github/workflows/live-provider-staging-dispatch.yml
  trigger: workflow_dispatch only
  input: approved_dispatcher_sha only
  worker SHA: hardcoded
  model: hardcoded
  forwarded secrets: none
    |
    v
worker @ 47b65f359fd844067346d987f9102f6eeab911d9
  .github/workflows/live-provider-staging.yml
  trigger: workflow_call only
  validates caller repository/ref/workflow path
  validates exact worker SHA and fixed model
  runs fake quality gates before Environment access
  live job names environment live-provider-staging
  AVALAI_API_KEY is referenced only in the protected step
```

The dispatcher, worker, policy, durable Invocation/Trace/staging-result
composition, sanitized artifact and no-retry uncertainty semantics were completed
in earlier Phase 1.9 increments. This increment changed no runtime or live
workflow behavior.

## Completed non-live GitHub settings audit

### Repository and CI state

The following were proved through connected GitHub repository operations:

- dispatcher file exists on `main`;
- dispatcher blob on `main`, bootstrap branch and PR #70 is
  `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`;
- dispatcher is `workflow_dispatch` only and exposes only
  `approved_dispatcher_sha`;
- worker and model are hardcoded;
- dispatcher forwards no secret and has no `secrets: inherit`;
- worker is `workflow_call` only and validates the expected repository, `main`,
  dispatcher path, exact worker SHA and fixed model;
- PR #70 had zero conversation comments, zero submitted reviews and zero inline
  review threads at the audit point;
- Issue #65 remained open;
- the exact merge-preview passed full Core and Android CI.

### Connector capability audit

The complete GitHub Connector surface available in this execution was inspected.
It exposed repository files, commits, pull requests, issues, reviews, CI runs,
jobs, logs and artifacts. It did **not** expose read operations for:

- workflow metadata/state such as `active` or `disabled_manually`;
- deployment Environment objects;
- required reviewer rules;
- prevention of self-review;
- Environment deployment branch/tag policies;
- Environment secret names or update timestamps.

No unavailable setting was inferred. Lack of a Connector endpoint is not evidence
that a GitHub setting is absent. The provider secret value was neither requested
nor read.

### Verified settings

```text
default branch: VERIFIED main
dispatcher file on main: VERIFIED
dispatcher blob identity: VERIFIED
dispatcher trigger/input: VERIFIED
dispatcher worker SHA/model pinning: VERIFIED
dispatcher secret forwarding: VERIFIED absent
worker caller/SHA/model checks: VERIFIED
worker environment name in YAML: VERIFIED
worker secret reference placement: VERIFIED
ordinary CI isolation: VERIFIED
full merge-preview Core/Android CI: VERIFIED
```

### Unverified external settings

```text
dispatcher enabled and visible in Actions: UNVERIFIED
Environment live-provider-staging exists: UNVERIFIED
independent required reviewer configured: UNVERIFIED
prevention of self-review enabled: UNVERIFIED
deployment restriction allows only main: UNVERIFIED
Environment secret AVALAI_API_KEY exists: UNVERIFIED
Environment secret update timestamp: UNVERIFIED
no weaker repository/organization secret fallback: UNVERIFIED
credential provider validity/restriction: UNVERIFIED
provider credit and current model availability: UNVERIFIED
independent deployment approval: UNVERIFIED
explicit user spend approval: NOT GRANTED
```

## Approval-package decision

The approval package was not prepared because the non-live prerequisites above
were not all proved. The values below are retained only as a candidate identity
for the next audit; they are not authorization:

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

Every value must be re-resolved after any repository or GitHub configuration
change. Implementation work, CI or this candidate identity does not constitute
permission to dispatch.

## Files changed by this increment

From previous Handoff Head
`096890150c7cf129eab19ebf4ac0bdf05e631e2f` to audit product Head
`ae2bc640226da8a117174f70530483c67b03a2c4`, the product increment changes only:

- `docs/validation/phase-1-9-protected-environment-readiness.md`
- `docs/validation/phase-1-9-live-acceptance-checklist.md`
- `services/core/tests/test_live_provider_staging_documentation.py`

This Handoff update adds only `docs/DEVELOPMENT_HANDOFF.md`.

No provider runtime, model policy, workflow trigger, Environment name, secret
reference, dependency, Android source, generated database, WAL/SHM or credential
was changed.

## Static test coverage

Two additional documentation-contract tests were added, bringing the full Core
suite to 575 tests. The documentation suite now proves:

- exact repository, worker, dispatcher, PR, merge-preview and CI identities are
  retained in readiness evidence;
- unavailable Connector settings remain explicitly `UNVERIFIED`;
- the audit records that no secret value was requested or read;
- checklist state remains `non_live_prerequisites_complete: false`;
- approval package remains `NOT PREPARED`;
- no Environment/reviewer/secret field can silently become approved through a
  documentation edit;
- all previous topology, policy, no-retry, privacy and pre-secret gates remain
  locked.

The first candidate run (#1057) reached 574 passing tests and one formatting-only
Markdown assertion failure. Ruff, MyPy and Android were otherwise unaffected.
The assertion was changed to compare normalized whitespace.

## Validation evidence

Exact audit product validation:

```text
Product Head: ae2bc640226da8a117174f70530483c67b03a2c4
Merge preview: 6d08d271e5c0f242b288e43fd442a7a772ada549
Workflow: CI
Run ID: 30803084979
Run number: 1058
Conclusion: success
core-quality: success
android-quality: success
Ruff: all checks passed
strict MyPy: no issues in 83 source files
Core: 575 passed, 2 dependency warnings, 12.85s
Android assembleDebug: passed
Android testDebugUnitTest: passed
Android lintDebug: passed
Debug APK upload: passed
live workflow dispatches: zero
credential access: zero
real AvalAI/User API calls: zero
```

Artifacts from run `30803084979`:

- `core-quality-diagnostics` — ID `8851630583`,
  SHA-256 `f9d97aa1978d3d043c57d25e80f9368edc89e9bbd991add176f089d64f4c4aa2`
- `core-test-report` — ID `8851631134`,
  SHA-256 `1ecc66854bdeceb7211bb65dc7671e6d94fa7e9a14d1ec8892371b2983c77953`
- `android-build-diagnostics` — ID `8851641252`,
  SHA-256 `b9cff75a807bd7bbf4f2d4ceb52bb90c719134b124a3ff207018e9dc07705edd`
- `simorgh-android-debug` — ID `8851642241`,
  SHA-256 `d5436ac5a7bdefbfca47f0cab705e6d6861ddf0ca50fd99e5d2480d763b7c7a3`

## Current blockers

1. Workflow state (`active`/disabled and visible in Actions) is not available
   through the connected tool surface.
2. Environment existence and protection settings are not available.
3. Environment-secret name/update metadata is not available.
4. Credential validity, provider credit and model availability remain live
   preflight facts and are not proved.
5. No exact live approval has been granted.
6. No canary, provider request ID, exact transaction or sanitized live artifact
   exists.
7. PR #70 remains Draft and Phase 1.9 merge acceptance is incomplete.

## Remaining Phase 1.9 work

1. Use an authenticated GitHub UI/API surface that can read workflow state,
   Environment protection and Environment-secret metadata without retrieving the
   secret value.
2. Record only proved settings; keep unavailable settings `UNVERIFIED`.
3. Re-resolve current `main`, dispatcher blob, worker SHA and merge-preview after
   any setting or repository change.
4. Prepare the exact approval package only when every non-live prerequisite is
   proved.
5. Obtain separate explicit user approval for dispatcher SHA, worker SHA,
   `refs/heads/main`, `gpt-5.4-mini` and all hard ceilings.
6. Dispatch once, require independent Environment approval, reconcile exact
   transaction evidence and prove zero-call/zero-charge replay.
7. Record sanitized evidence, complete review audit and merge PR #70.

## Mandatory reads for the next execution

- `docs/DEVELOPMENT_HANDOFF.md`
- `docs/SIMORGH_MASTER_DIRECTIVE.md`
- `docs/IMPLEMENTATION_MASTER_PLAN.md`
- `docs/CANCELLATION_PROPAGATION.md`
- `docs/TRACE_AUTHORITY.md`
- `docs/adr/0022-explicitly-budgeted-live-provider-staging.md`
- `docs/LIVE_PROVIDER_STAGING_RUNBOOK.md`
- `docs/validation/phase-1-9-protected-environment-readiness.md`
- `docs/validation/phase-1-9-live-acceptance-checklist.md`
- `docs/validation/phase-1-9-manual-staging-boundary.md`
- `.github/workflows/live-provider-staging-dispatch.yml`
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

Also inspect all PR #70 comments, submitted reviews, inline review threads,
changed files and checks created after audit product Head
`ae2bc640226da8a117174f70530483c67b03a2c4`.

## Exact continuation point

First resolve current `main`, branch Head, PR #70 merge-preview, Issue #65, CI,
comments, reviews and review threads. Verify full Core and Android CI triggered by
this Handoff update. Fix only an exact failure before proceeding.

Then perform one narrow **non-live GitHub configuration evidence increment**:

- use an authenticated GitHub UI/API surface that exposes workflow state and
  deployment Environment metadata;
- verify the dispatcher is enabled and visible without starting it;
- verify Environment `live-provider-staging` exists;
- verify at least one independent required reviewer;
- verify prevention of self-review;
- verify deployment restrictions allow only `main`;
- verify Environment secret name `AVALAI_API_KEY` and its update timestamp without
  reading or reproducing the value;
- verify no weaker repository/organization secret fallback is relied upon when
  the available surface permits that determination;
- update readiness and checklist with only directly proved facts;
- leave every unavailable fact `UNVERIFIED`;
- prepare the exact approval package only if all non-live prerequisites pass.

Do not press Run workflow, dispatch a workflow, approve a deployment, configure,
read or rotate a credential, call AvalAI/User API, or interpret implementation
work as live authorization. Run full Core and Android gates and update this
Handoff with exact evidence.
