# Development Handoff

## Current snapshot

- Date: 2026-08-03
- Audit time: `2026-08-03T14:49+03:30`
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
- Authenticated settings-audit product Head:
  `ef33f37af04f76439490930b1d220b63495155f7`
- Product merge-preview validated by CI:
  `535d3c27299aeeb9d315db26bdf08f5376a4abc9`
- Product CI: run `30809544297`, number `1062`, success
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
  live job names Environment live-provider-staging
  AVALAI_API_KEY is referenced only in the protected step
```

The dispatcher, worker, policy, durable Invocation/Trace/staging-result
composition, sanitized artifact and no-retry uncertainty semantics were completed
in earlier Phase 1.9 increments. This increment changed no runtime or live
workflow behavior.

## Completed authenticated configuration-evidence refresh

### Repository and CI state

The following were proved through authenticated GitHub repository operations:

- authenticated repository permission is admin;
- default branch remains `main` at
  `3bcb41437e3b8d2f497516ef9a214de5becf45e9`;
- dispatcher file remains present on `main` with blob
  `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`;
- dispatcher remains `workflow_dispatch` only with only
  `approved_dispatcher_sha` as input;
- worker SHA and model remain hardcoded;
- dispatcher forwards no secret and has no `secrets: inherit`;
- worker remains `workflow_call` only and validates the expected repository,
  `main`, dispatcher path, exact worker SHA and fixed model;
- PR #70 is open, Draft and mergeable;
- PR #70 has zero conversation comments, zero submitted reviews and zero inline
  review threads at this audit point;
- Issue #65 remains open;
- exact product merge-preview `535d3c27299aeeb9d315db26bdf08f5376a4abc9`
  passed full Core and Android CI.

### Authenticated Connector capability result

The complete authenticated GitHub Connector surface exposed during this
execution was discovered again. It supports repository files, commits, pull
requests, issues, reviews, CI runs, jobs, logs and artifacts. It still provides
no read operations for:

- workflow metadata/state such as `active` or `disabled_manually`;
- deployment Environment objects;
- required reviewer rules;
- prevention of self-review;
- Environment deployment branch/tag restrictions;
- Environment secret names or update timestamps;
- repository/organization secret inventories needed to prove absence of a weaker
  fallback.

No unavailable setting was inferred. Lack of an endpoint is not evidence that a
setting is absent. The provider secret value was neither requested nor read.

### Directly verified state

```text
default branch: VERIFIED main
dispatcher file on main: VERIFIED
dispatcher blob identity: VERIFIED
dispatcher trigger/input: VERIFIED
dispatcher worker SHA/model pinning: VERIFIED
dispatcher secret forwarding: VERIFIED absent
worker caller/SHA/model checks: VERIFIED
worker Environment name in YAML: VERIFIED
worker secret reference placement: VERIFIED
ordinary CI isolation: VERIFIED
full merge-preview Core/Android CI: VERIFIED
```

### External state still unverified

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

The approval package was not prepared because all non-live prerequisites were
not proved. These values are retained only as a candidate identity for a future
audit and are not authorization:

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
`901e858e3be6d92d9a64e1617fdcf972dec4c2c9` to audit product Head
`ef33f37af04f76439490930b1d220b63495155f7`, the product increment changes only:

- `docs/validation/phase-1-9-protected-environment-readiness.md`
- `docs/validation/phase-1-9-live-acceptance-checklist.md`
- `services/core/tests/test_live_provider_staging_documentation.py`

This Handoff update adds only `docs/DEVELOPMENT_HANDOFF.md`.

No provider runtime, model policy, workflow trigger, Environment name, secret
reference, dependency, Android source, generated database, WAL/SHM or credential
was changed.

## Static test coverage

The existing documentation-contract suite was updated to lock the refreshed
repository, worker, dispatcher, PR, merge-preview and CI identities. It continues
to prove:

- unavailable Connector settings remain explicitly `UNVERIFIED`;
- the audit records that no secret value was requested or read;
- checklist state remains `non_live_prerequisites_complete: false`;
- approval package remains `NOT PREPARED`;
- no Environment/reviewer/secret field can silently become approved through a
  documentation edit;
- all topology, policy, no-retry, privacy and pre-secret gates remain locked.

The full Core suite remains 575 tests.

## Validation evidence

Exact audit product validation:

```text
Product Head: ef33f37af04f76439490930b1d220b63495155f7
Merge preview: 535d3c27299aeeb9d315db26bdf08f5376a4abc9
Workflow: CI
Run ID: 30809544297
Run number: 1062
Conclusion: success
core-quality: success
android-quality: success
Ruff: all checks passed
strict MyPy: no issues in 83 source files
Core: 575 passed, 2 dependency warnings, 11.62s
Android assembleDebug: passed
Android testDebugUnitTest: passed
Android lintDebug: passed
Debug APK upload: passed
live workflow dispatches: zero
credential access: zero
real AvalAI/User API calls: zero
```

Artifacts from run `30809544297`:

- `core-quality-diagnostics` — ID `8854191790`,
  SHA-256 `5d3c2a41827a5f0fe4e201b1ad202e5d0949061c4dc5f89d9c4429b1274f8e37`
- `core-test-report` — ID `8854192067`,
  SHA-256 `cd58b631e01b81e220aeaa258504df47c8b7114860772199a0ced039bac3c126`
- `android-build-diagnostics` — ID `8854195852`,
  SHA-256 `57f8917a66653c55adf5f385cb4a09a6b39a66a9301f987b140c3615bda14351`
- `simorgh-android-debug` — ID `8854196297`,
  SHA-256 `85b5d52e73b2e6625ace866970c49ac2d0e8249d540a4948306e14e56904e99f`

## Current blockers

1. Workflow state (`active`/disabled and visible in Actions) remains unavailable
   through the connected authenticated surface.
2. Environment existence and protection settings remain unavailable.
3. Environment-secret name/update metadata remains unavailable.
4. Absence of weaker repository/organization secret fallback cannot be proved.
5. Credential validity, provider credit and model availability remain live
   preflight facts and are not proved.
6. No exact live approval has been granted.
7. No canary, provider request ID, exact transaction or sanitized live artifact
   exists.
8. PR #70 remains Draft and Phase 1.9 merge acceptance is incomplete.

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
`ef33f37af04f76439490930b1d220b63495155f7`.

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
