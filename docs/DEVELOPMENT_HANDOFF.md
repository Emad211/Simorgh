# Development Handoff

## Current snapshot

- Date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Default/base branch: `main`
- Current audited `main` commit:
  `3bcb41437e3b8d2f497516ef9a214de5becf45e9`
- Working branch: `core/live-provider-staging`
- Pull request: #70 — `Core: establish budgeted AvalAI staging policy and User API boundary`
- Pull request state: open, Draft and mergeable
- Issue: #65 — `Phase 1 Step 1.9: explicitly budgeted AvalAI live-provider staging`
- Issue state: open
- Bootstrap pull request: #72 — merged
- Phase: 1.9 — Live Provider Staging
- Reviewed reusable-worker commit:
  `47b65f359fd844067346d987f9102f6eeab911d9`
- Dispatcher blob SHA:
  `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`
- Latest product/evidence Head before this Handoff:
  `59b46fc4e3a58607c3933c5b3cd920ac836a58ce`
- Exact PR merge-preview commit validated by CI:
  `b45382d985b9afd1e5f32e1e4a585a371ca9ac60`
- Current operational readiness: **NOT READY FOR LIVE DISPATCH**
- Live dispatcher/worker runs initiated by this work: `0`
- Deployment approvals performed by this work: `0`
- Credentials configured, read or used by this work: `0`
- Real AvalAI model requests initiated by this work: `0`
- Real AvalAI User API requests initiated by this work: `0`

The current Handoff commit is the working-branch `HEAD`; resolve its SHA before
starting the next execution. Do not invent a self-referential SHA.

## Governing invariants

Simorgh remains authoritative for Task and Invocation identity, durable state,
budget, usage, replay, privacy and execution. Trace is immutable audit evidence;
it cannot authorize execution or rewrite Invocation truth.

Phase 1.9 preserves these constraints:

- ordinary Core runtime and ordinary CI are fake and zero-external;
- only a manual default-branch dispatcher may enter the live staging topology;
- one accepted staging run permits at most one model request;
- no automatic retry, provider/model/domain failover, streaming or tools;
- fixed Core-authored canary only; no user, conversation or repository content;
- worst-case usage is reserved before provider entry;
- uncertain provider entry remains durable `unknown` and never authorizes a
  replacement request;
- exact replay adds zero provider, catalog, credit or transaction calls and zero
  committed usage;
- only same-provider-request-ID User API polling is permitted after model entry;
- pending or unavailable transaction reconciliation is incomplete, never zero
  cost and never Phase 1.9 acceptance;
- exact provider transaction data is billing evidence only;
- prompt/output text, credentials, authorization headers, cookies, IP addresses,
  API-key suffixes, safety identifiers, raw HTTP bodies and environment dumps
  never enter durable stores, logs or uploaded artifacts;
- live execution requires separately verified environment protection and a new
  explicit user approval bound to exact dispatcher SHA, worker SHA, ref, model
  and hard maximum spend.

## Completed zero-live-call topology increment

### Selected topology

ADR 0022 now selects a two-file fail-closed topology:

```text
main
  .github/workflows/live-provider-staging-dispatch.yml
  trigger: workflow_dispatch only
  input: approved_dispatcher_sha only
  worker SHA: hardcoded
  model: hardcoded
  secrets forwarded: none
    |
    v
exact reviewed worker commit
  .github/workflows/live-provider-staging.yml
  trigger: workflow_call only
  caller repository/ref/workflow validated
  exact worker checkout validated
  fake pre-secret gates
  protected environment live-provider-staging
  environment secret AVALAI_API_KEY
  one governed canary and exact replay
```

The dispatcher exists on `main`; the complete Phase 1.9 worker remains pinned to
an immutable reviewed commit rather than a branch or tag.

### Default-branch dispatcher

`.github/workflows/live-provider-staging-dispatch.yml`:

- has `workflow_dispatch` only;
- exposes one required string input: `approved_dispatcher_sha`;
- requires repository `Emad211/Simorgh`;
- requires ref `refs/heads/main`;
- requires `approved_dispatcher_sha == github.sha`;
- hardcodes worker SHA
  `47b65f359fd844067346d987f9102f6eeab911d9`;
- places that same SHA in the reusable-workflow `uses` reference and
  `reviewed_commit_sha` input;
- hardcodes model `gpt-5.4-mini`;
- has read-only contents permission;
- uses non-cancelling dispatcher concurrency;
- contains no provider key reference, `secrets` field or `secrets: inherit`;
- cannot accept worker SHA, model, provider, prompt or budget at dispatch time.

The reviewed dispatcher blob SHA is
`a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`.

### Reusable worker

`.github/workflows/live-provider-staging.yml`:

- has `workflow_call` only;
- has no direct manual, push, pull-request or schedule trigger;
- validates caller repository `Emad211/Simorgh`;
- validates caller ref `refs/heads/main`;
- validates caller workflow ref
  `Emad211/Simorgh/.github/workflows/live-provider-staging-dispatch.yml@refs/heads/main`;
- validates model `gpt-5.4-mini`;
- checks out and verifies the exact reviewed worker commit;
- runs Ruff, strict MyPy and fake staging suites before the credential boundary;
- binds only `live-canary` to environment `live-provider-staging`;
- references environment secret `AVALAI_API_KEY` exactly once;
- retains one-call, no-retry, no-failover, exact reconciliation and sanitized
  artifact controls.

### Bootstrap PR #72

A separate branch `ops/live-provider-staging-bootstrap` was created from `main`.
PR #72 contained exactly one product path:

```text
.github/workflows/live-provider-staging-dispatch.yml
```

Evidence:

- bootstrap Head: `7f8ad3bc7c3eaac1286adf577823a9cd99a2a3c2`;
- changed files: `1`;
- additions: `49`;
- deletions: `0`;
- dispatcher blob: `a5fe7be975ee41dd0be222ab1c606f8b4bab87d7`;
- CI run `30781058656`, run number `1050`, success;
- merge commit on `main`:
  `3bcb41437e3b8d2f497516ef9a214de5becf45e9`.

After merge, fetching the dispatcher from `main` returned the same blob SHA as
the PR #70 and bootstrap copies. The bootstrap was merged without dispatching the
workflow, approving a deployment, configuring/reading a key or contacting
AvalAI.

### ADR, runbook, readiness and checklist

Updated documents:

- `docs/adr/0022-explicitly-budgeted-live-provider-staging.md`
- `docs/LIVE_PROVIDER_STAGING_RUNBOOK.md`
- `docs/validation/phase-1-9-protected-environment-readiness.md`
- `docs/validation/phase-1-9-live-acceptance-checklist.md`

They now cover:

- exact two-SHA approval identity;
- bootstrap PR and blob-equality procedure;
- default-branch dispatcher and exact reusable-worker pin;
- environment setup, independent reviewer, self-review prevention and `main`
  deployment restriction;
- environment-scoped secret handling with no secret forwarding;
- manual dispatcher procedure and worker/environment gate sequence;
- exact artifact verification and result interpretation;
- duplicate-charge, unknown Invocation, cancellation, cost mismatch, credential
  exposure and privacy incident response;
- credential rotation and dispatcher emergency disablement;
- exact acceptance and post-run evidence fields.

Emergency controls now target the dispatcher:

```text
gh workflow disable live-provider-staging-dispatch.yml
gh run cancel <RUN_ID>
```

Disabling or cancelling does not prove provider non-entry and never authorizes a
replacement model request.

## Static test coverage

`services/core/tests/test_live_provider_staging_workflow.py` now proves:

- dispatcher is `workflow_dispatch` only and `main`-bound;
- only `approved_dispatcher_sha` is exposed;
- exact worker SHA appears consistently in the reviewed constant, `uses` and
  worker input;
- model is fixed;
- no secret is forwarded or referenced by the dispatcher;
- worker is `workflow_call` only;
- worker validates caller repository/ref/workflow, checkout SHA and model;
- environment secret remains after fake gates;
- actions/dependencies remain pinned;
- ordinary CI remains isolated.

`services/core/tests/test_live_provider_staging_documentation.py` proves:

- ADR, runbook, readiness and checklist agree on topology and limits;
- merged bootstrap commit, worker SHA and dispatcher blob are recorded;
- readiness remains fail-closed for unavailable external settings;
- two-SHA approval and rejection states remain explicit;
- documentation tests execute before the worker secret boundary.

The full Core suite increased from 570 to 573 tests.

## Validation evidence

### Frozen reusable worker

```text
Worker commit: 47b65f359fd844067346d987f9102f6eeab911d9
Workflow: CI
Run ID: 30780786562
Run number: 1047
Conclusion: success
core-quality: success
android-quality: success
real provider/User API calls: zero
live dispatches: zero
```

Artifacts:

- `core-quality-diagnostics` — ID `8843562393`,
  SHA-256 `4f7d6e459faff2d99e2fe3232c7b8173daa73ff51c37794328e0cb7930d9ca0a`
- `core-test-report` — ID `8843562647`,
  SHA-256 `1d8973e3e6d4b236ac10c53160cfde9af40aa2b76fcd178bcf65c33c5efe4eec`
- `android-build-diagnostics` — ID `8843569679`,
  SHA-256 `110b9b62e93d64fe885e551f12bd84d95980a77b997a7f3d09d711d687aa068b`
- `simorgh-android-debug` — ID `8843570185`,
  SHA-256 `576a9aaa83e2b99e5c982494ed990176d0faf1ac5debae310dcef29cefb3ccb1`

### Bootstrap PR #72

```text
Bootstrap Head: 7f8ad3bc7c3eaac1286adf577823a9cd99a2a3c2
Workflow: CI
Run ID: 30781058656
Run number: 1050
Conclusion: success
core-quality: success
android-quality: success
changed product files: 1
real provider/User API calls: zero
live dispatches: zero
```

Artifacts:

- `core-quality-diagnostics` — ID `8843653822`,
  SHA-256 `d14eb11b3e2cf13c0fa2879bce134f09111d0ab27b8737e75751fd864c82ff41`
- `core-test-report` — ID `8843654069`,
  SHA-256 `35903cd49bd7a1dfef8bc46e232a97b442acbf8646a7ac0e60aa6d251465791d`
- `android-build-diagnostics` — ID `8843659984`,
  SHA-256 `6f0b4af292b9b386dc8e93cf4b620863e4f6f7349e1c64dc6fc34f51180f7f56`
- `simorgh-android-debug` — ID `8843660242`,
  SHA-256 `102791cca3617e74a4a655a94536288097e0884a53e8fd1a619dbaae20fb6d16`

### Final PR #70 merge preview before Handoff

GitHub built merge-preview commit
`b45382d985b9afd1e5f32e1e4a585a371ca9ac60` from product Head
`59b46fc4e3a58607c3933c5b3cd920ac836a58ce` and current `main`
`3bcb41437e3b8d2f497516ef9a214de5becf45e9`.

```text
Workflow: CI
Run ID: 30781246040
Run number: 1053
Conclusion: success
Ruff: all checks passed
strict MyPy: no issues in 83 source files
Core: 573 passed, 2 dependency warnings, 12.12s
Android assembleDebug: passed
Android testDebugUnitTest: passed
Android lintDebug: passed
Debug APK upload: passed
real provider/User API calls: zero
live dispatches: zero
```

Artifacts:

- `core-quality-diagnostics` — ID `8843722877`,
  SHA-256 `cbd39fae6076adfa52fb622362c8d7dcf1df22313ec08f62c4d24ad640a907f7`
- `core-test-report` — ID `8843723033`,
  SHA-256 `fb9c0fe0ff265e3624d02937505c56c073ed251fdbdefc44432341ee2c39190b`
- `android-build-diagnostics` — ID `8843727010`,
  SHA-256 `12039e6fa056a5649784b7bc36c5f9cc08276fd2c50e5ff2485f49c9164b9c8a`
- `simorgh-android-debug` — ID `8843727477`,
  SHA-256 `f7e7d3bac1638f409d627b2b9b38e4add6dd900b31038280065aa6ec80667eba`

The working branch was 118 commits ahead and two commits behind `main` after the
bootstrap merge because the bootstrap history was created separately. The
content-equivalent dispatcher is already present on both sides, PR #70 remains
mergeable, and CI #1053 validated GitHub's exact current-main merge preview. Do
not claim the branch history is synchronized; re-audit ahead/behind and the merge
preview before any final PR merge.

## Files changed by this increment

From previous Handoff Head
`e62538d16e67dfee50fe01595a4d21a9e5be307b` to product/evidence Head
`59b46fc4e3a58607c3933c5b3cd920ac836a58ce`, this increment changes eight paths:

- `.github/workflows/live-provider-staging-dispatch.yml`
- `.github/workflows/live-provider-staging.yml`
- `docs/LIVE_PROVIDER_STAGING_RUNBOOK.md`
- `docs/adr/0022-explicitly-budgeted-live-provider-staging.md`
- `docs/validation/phase-1-9-live-acceptance-checklist.md`
- `docs/validation/phase-1-9-protected-environment-readiness.md`
- `services/core/tests/test_live_provider_staging_documentation.py`
- `services/core/tests/test_live_provider_staging_workflow.py`

This Handoff update changes only `docs/DEVELOPMENT_HANDOFF.md` in addition. No
provider runtime, model gateway, budget policy, credential, generated database,
WAL/SHM, Android runtime or live artifact was changed by this topology increment.

## Resolved blocker

The structural default-branch `workflow_dispatch` blocker is resolved:

- dispatcher exists on `main`;
- it is byte-identical to the reviewed PR #70 copy;
- it pins an exact green worker commit;
- it has no automatic trigger or secret forwarding.

This does **not** make the system operationally ready or authorize execution.

## Unverified prerequisites and remaining risks

1. **Dispatcher enabled/visible state:** the current connector can fetch the file
   from `main` but cannot prove Actions reports the workflow as enabled or shows
   the Run workflow button. Verify without starting a run.
2. **Environment object:** existence of `live-provider-staging` is unverified.
3. **Required reviewer:** reviewer list and independent approval policy are
   unverified.
4. **Self-review prevention:** setting is unverified.
5. **Deployment restriction:** selected branch/tag policy allowing only `main` is
   unverified.
6. **Environment secret metadata:** presence and update time for
   `AVALAI_API_KEY` are unverified; never retrieve its value.
7. **Secret scope:** absence of a weaker relied-upon repository/organization
   duplicate is unverified.
8. **Provider credential validity/restriction:** unverified.
9. **Provider account credit/model availability:** may only be proven in an
   explicitly approved preflight.
10. **Explicit approval:** implementation and bootstrap merge are not permission
    to spend. No exact two-SHA/ref/model/cost approval has been granted.
11. **No live evidence:** no provider request ID, exact transaction or sanitized
    live artifact exists.
12. **Exact acceptance:** pending/unavailable reconciliation remains incomplete.
13. **Branch history divergence:** re-audit current main/head/merge preview before
    final merge; do not rely on old ahead/behind counts.
14. **GitHub plan/settings:** environment protection behavior must be verified in
    the actual repository settings.

## Remaining Phase 1.9 sequence

1. Verify dispatcher enabled/visible state without dispatching it.
2. Configure or independently verify environment `live-provider-staging`:
   required reviewer, self-review prevention, `main`-only deployment restriction
   and environment secret name/update metadata.
3. Confirm no live run is queued, active, awaiting approval or unresolved.
4. Populate Section A/B evidence in the live-acceptance checklist without marking
   any unverified statement as true.
5. Re-resolve current `main` dispatcher SHA and confirm it still contains the
   reviewed dispatcher blob and worker pin.
6. Present an explicit approval packet to the user containing:
   - current dispatcher SHA on `main`;
   - worker SHA `47b65f359fd844067346d987f9102f6eeab911d9`;
   - ref `refs/heads/main`;
   - model `gpt-5.4-mini`;
   - maximum one model call;
   - 128 input tokens;
   - 16 output tokens;
   - 20,000 micro-USD estimated ceiling;
   - `0.01 UNIT` exact-cost ceiling;
   - `0.10 UNIT` remaining-credit floor.
7. Do not dispatch until the user separately and explicitly approves that exact
   packet.
8. After approval, execute once, require exact transaction reconciliation,
   verify sanitized artifact and prove zero-call replay.
9. Re-audit PR comments/reviews/checks and merge PR #70 only after complete live
   acceptance.

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
- `.github/workflows/live-provider-staging-dispatch.yml` from both `main` and PR
  #70;
- `.github/workflows/live-provider-staging.yml` at worker commit
  `47b65f359fd844067346d987f9102f6eeab911d9`;
- `.github/constraints/live-provider-staging.txt`;
- `services/core/src/simorgh_core/agents/live_provider_staging.py`;
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`;
- `services/core/src/simorgh_core/agents/live_provider_staging_artifact.py`;
- `services/core/src/simorgh_core/agents/live_provider_staging_cli.py`;
- `services/core/src/simorgh_core/agents/live_provider_staging_trace.py`;
- `services/core/src/simorgh_core/agents/model_gateway.py`;
- `services/core/src/simorgh_core/providers/avalai.py`;
- `services/core/src/simorgh_core/providers/avalai_user_api.py`;
- `services/core/tests/test_live_provider_staging_documentation.py`;
- `services/core/tests/test_live_provider_staging_workflow.py`;
- `.github/workflows/ci.yml`.

Also inspect all PR #70 comments, review submissions, inline review threads,
changed files and checks created after product/evidence Head
`59b46fc4e3a58607c3933c5b3cd920ac836a58ce`, plus any change to `main` after
`3bcb41437e3b8d2f497516ef9a214de5becf45e9`.

## Exact continuation point

First resolve the current working-branch Head and verify the full Core and
Android CI triggered by this Handoff update. If either gate is not green, fix
only that exact failure.

Then perform one narrow **non-dispatch operational-readiness verification**:

- resolve current `main`, PR #70 Head, merge preview, Issue #65 and all current
  checks/reviews;
- confirm the dispatcher file remains present on `main`, byte-identical to the
  reviewed blob and pinned to the reviewed worker commit;
- verify, without pressing Run workflow, whether the dispatcher is enabled and
  visible in Actions;
- inspect environment `live-provider-staging` settings without reading any secret
  value;
- verify required reviewer, self-review prevention, `main`-only deployment
  restriction and `AVALAI_API_KEY` name/update metadata;
- record unavailable evidence as `UNVERIFIED`, never infer it;
- populate the checklist with only proven repository/environment evidence;
- if all non-live prerequisites are proven, prepare the exact approval packet for
  the user but do not dispatch it;
- update this Handoff with exact SHA, CI, settings evidence, remaining blockers
  and the next continuation point.

Do not dispatch the workflow, approve a deployment, configure/read/use a
credential, call AvalAI/User API, infer environment settings, or treat this
implementation request as live-spend approval.
