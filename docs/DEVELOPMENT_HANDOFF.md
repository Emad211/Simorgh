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
- Phase: 1.9 — Live Provider Staging
- Lifecycle implementation: `395eaecd7617b260f1b0bd57a2f364a030aa74f5`
- Trace-link implementation: `40ac5c755cff50c60d4dda0f9ec7520d2f048961`
- Cancellation/uncertainty implementation:
  `7d11af47a0801b4593b6cf031bfaa49b247c0bb7`
- Reconciliation-disposition implementation:
  `50b1484d9113951f15a1fc060d58f13896f52a9e`
- Protected manual staging-boundary product Head:
  `8ff42c2fb94c9342df59953725c96a8c04760dff`
- Exact owner-authored validation Head:
  `04d57b61bb34ef759573ca1e51388ff18fd750c9`
- Exact validation CI: run `30776817126`, run number `1025`, success
- Completed substeps:
  - disabled-by-default policy and sanitized User API boundary;
  - exactly-one-call fake canary composition;
  - immutable SQLite staging-result authority;
  - config, registry and lifespan ownership;
  - Invocation/Trace linkage;
  - cancellation and transport-uncertainty persistence;
  - canonical reconciliation disposition;
  - protected manual CLI/workflow and sanitized artifact boundary.
- Next substep: staging ADR, operator runbook and protected-environment
  readiness audit. Do not dispatch the live workflow until the user explicitly
  approves the exact commit, reviewed model and hard maximum spend.

The current Handoff commit is the branch `HEAD`; resolve it from Git before the
next execution. Do not write an assumed self-referential SHA.

## Governing invariants

Simorgh remains authoritative for Task and Invocation identity, durable state,
budget, usage, replay, privacy and execution. Trace is an immutable audit
projection and cannot authorize execution or rewrite Invocation truth.

Phase 1.9 preserves these constraints:

- ordinary runtime and ordinary CI never use live provider credentials;
- one staging run permits at most one model request;
- no automatic retry, provider/model/domain failover, streaming or tool use;
- fixed Core-authored input only; no user, conversation or repository content;
- replay checks durable staging authority before any external boundary;
- replay adds zero provider, catalog, credit or transaction calls and zero usage;
- exact provider cost is staging billing evidence only;
- cancellation and transport uncertainty remain conservative and durable;
- raw prompt/output, exception text, headers, credentials, IP addresses and raw
  provider/User API bodies are never persisted or uploaded;
- live execution is possible only through a manual protected workflow.

## Completed manual staging boundary

### Native task and routing authority

A reviewed internal task/specialist pair now exists:

```text
TaskKind.LIVE_PROVIDER_STAGING
system.live-provider-staging@1.0.0
```

It is read-only, has no tool/connector permissions, allows FAST tier only,
permits exactly one model call, zero retries and one branch, and carries bounded
token, cost and elapsed-time ceilings.

The CLI submits a fixed `TaskEnvelope` through `AgentTaskControlPlane`. The task
has no independent wall-clock deadline; the reviewed 60-second limit remains in
`TaskBudget`, preventing caller/control-plane clock skew.

### Direct routed Invocation Trace projection

Trace reconciliation can now project root model/tool invocations owned directly
by the exact routed specialist. A root is accepted only when request identity,
agent ID and agent version match the durable routing decision, it has no parent
or cancellation owner, and it is not the router classifier. Unrelated root
invocations are ignored. Staging code never manufactures Trace events directly.

### Dedicated CLI composition

`services/core/src/simorgh_core/agents/live_provider_staging_cli.py` provides:

```text
python -m simorgh_core.agents.live_provider_staging_cli run ...
python -m simorgh_core.agents.live_provider_staging_cli verify ...
```

The run path validates reviewed URLs/model, enters the existing Core lifespan,
submits the fixed task, reuses Task/Invocation/Trace/staging-result authorities,
runs `LiveProviderStagingService`, validates terminal evidence, performs exact
replay and emits only a sanitized artifact. Provider/User API wrappers count
calls but do not grant authority or alter retry behavior.

`AvalAIProvider.close()` now explicitly releases the SDK HTTP client.

### Sanitized artifact authority

`LiveProviderStagingArtifact` is strict, frozen and versioned. Its canonical
identity covers source commit, workflow metadata, sanitized result, validated
Trace evidence, bounded call counters, replay proof and committed usage before
and after replay.

A passed artifact requires:

- exact completed reconciliation;
- valid terminal Invocation and Trace evidence;
- exactly one first-run model request;
- one catalog and credit preflight;
- at least one transaction lookup;
- replay of the same immutable result;
- zero external replay calls;
- zero committed-usage mutation.

The writer uses canonical JSON, a one-megabyte ceiling, atomic replacement and
mode `0600`. The privacy scanner rejects canary strings, authorization/bearer,
API-key, cookie, header, IP, safety, raw-response and environment-dump markers,
plus the exact runtime credential value.

### Protected manual workflow

`.github/workflows/live-provider-staging.yml`:

- has only `workflow_dispatch`;
- requires a reviewed 40-character SHA that equals dispatch and checkout SHA;
- offers only `gpt-5.4-mini`;
- uses one non-cancelling concurrency group;
- has read-only repository permissions;
- pins actions to complete commit SHAs;
- installs constrained direct dependency versions;
- runs Ruff, strict MyPy and fake acceptance before the secret boundary;
- binds the live job to environment `live-provider-staging`;
- references `AVALAI_API_KEY` exactly once in the protected execution step;
- uses isolated temporary SQLite authorities;
- verifies schema/hash/privacy and uploads only sanitized JSON for 30 days.

The workflow was **not dispatched** in this increment. No environment secret was
read and no real AvalAI or User API request occurred.

Repository code cannot prove environment existence, reviewer rules or secret
configuration. These remain operator prerequisites.

## Files changed by this increment

The product diff from previous Handoff Head
`acf32cb1f498e2a49835f7b44e28c046a91adbbc` to product Head
`8ff42c2fb94c9342df59953725c96a8c04760dff` contains exactly 14 paths:

- `.github/constraints/live-provider-staging.txt`
- `.github/workflows/live-provider-staging.yml`
- `docs/validation/phase-1-9-manual-staging-boundary.md`
- `services/core/src/simorgh_core/agents/contracts.py`
- `services/core/src/simorgh_core/agents/defaults.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_artifact.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_cli.py`
- `services/core/src/simorgh_core/agents/trace_child_invocations.py`
- `services/core/src/simorgh_core/agents/trace_reconciliation.py`
- `services/core/src/simorgh_core/providers/avalai.py`
- `services/core/tests/test_live_provider_staging_artifact.py`
- `services/core/tests/test_live_provider_staging_cli.py`
- `services/core/tests/test_live_provider_staging_workflow.py`
- `services/core/tests/test_trace_child_invocations.py`

No transfer workflow, patcher, generated database, WAL/SHM, credential or
diagnostic artifact remains in the product diff.

## Test coverage

This increment adds 13 tests:

- four artifact contract/privacy/tamper tests;
- two zero-network native composition/replay tests;
- six static workflow-security tests;
- one direct routed root Invocation Trace test.

The tests prove native authority composition, exactly one fake model call,
zero-call replay, unchanged usage, incomplete reconciliation without retry,
strict artifact privacy/tamper rejection, unrelated-root Trace exclusion,
manual-only triggering, protected secret placement, action/dependency pinning and
ordinary-CI isolation.

## Validation evidence

Deterministic product gate:

```text
Product Head: 8ff42c2fb94c9342df59953725c96a8c04760dff
Workflow: Phase 1.9 Direct Routed Trace Transfer
Run ID: 30776688407
Run number: 7
Conclusion: success
Ruff: passed
strict MyPy: no issues in 83 source files
Core: 564 passed, 2 dependency warnings, 12.66s
real provider/User API calls: zero
live workflow dispatches: zero
```

The direct CI from the bot-authored product commit was `action_required` with no
jobs (run `30776723861`, number `1024`). This was workflow authorization behavior,
not a product failure.

Exact owner-authored full validation:

```text
Validated Head: 04d57b61bb34ef759573ca1e51388ff18fd750c9
Workflow: CI
Run ID: 30776817126
Run number: 1025
Conclusion: success
core-quality: success
android-quality: success
Ruff: passed
strict MyPy: no issues in 83 source files
Core: 564 passed, 2 dependency warnings, 11.59s
Android assembleDebug: passed
Android testDebugUnitTest: passed
Android lintDebug: passed
Debug APK upload: passed
real provider/User API calls: zero
live workflow dispatches: zero
```

Artifacts from run `30776817126`:

- `core-quality-diagnostics` — ID `8842311487`,
  SHA-256 `96293a45556347b5f5e7a851d4c5fd614c0f520448f0864fb4f4f6ab17668c09`
- `core-test-report` — ID `8842311648`,
  SHA-256 `994428ee15ee3e18dcc45cc91f511bfa5b9d8d74de560a7722076eb8f5997143`
- `android-build-diagnostics` — ID `8842315909`,
  SHA-256 `4cd6bd8cba96acf4c0724c646169c09404bc57ebdb638b6155050aee161ca44c`
- `simorgh-android-debug` — ID `8842316100`,
  SHA-256 `4352679cc866994f517e3ab8f70589f98d36b51f8d75e922e8565d56ab27b2ad`

## Security and failure semantics

- missing credentials or URL/model/preflight mismatch blocks provider entry;
- CLI stderr is fixed and sanitized;
- failed or missing artifact verification fails the workflow;
- passed status cannot be asserted without exact result, Trace and replay proof;
- input SHA must equal dispatch and checkout SHA;
- the secret is unavailable to the pre-secret job;
- actions and direct dependencies are pinned;
- no endpoint or autonomous live path was introduced;
- cancellation, uncertainty, no-retry and replay semantics are unchanged.

## Remaining Phase 1.9 work

1. Add the staging ADR and operator runbook.
2. Audit protected-environment, reviewer and secret readiness without inventing
   evidence unavailable through repository APIs.
3. Prepare an exact live-acceptance checklist with commit, model and hard limits.
4. Obtain explicit user approval for exact commit/model/maximum spend.
5. Dispatch one canary, validate sanitized artifact, reconcile exact cost and
   prove zero-call/zero-charge replay.
6. Complete review audit and merge PR #70.

## Mandatory reads for the next execution

- `docs/DEVELOPMENT_HANDOFF.md`
- `docs/SIMORGH_MASTER_DIRECTIVE.md`
- `docs/IMPLEMENTATION_MASTER_PLAN.md`
- `docs/CANCELLATION_PROPAGATION.md`
- `docs/TRACE_AUTHORITY.md`
- `docs/validation/phase-1-9-live-provider-staging-start.md`
- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `docs/validation/phase-1-9-manual-staging-boundary.md`
- `.github/workflows/live-provider-staging.yml`
- `.github/constraints/live-provider-staging.txt`
- `services/core/src/simorgh_core/agents/contracts.py`
- `services/core/src/simorgh_core/agents/defaults.py`
- `services/core/src/simorgh_core/agents/live_provider_staging.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_artifact.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_cli.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_trace.py`
- `services/core/src/simorgh_core/agents/trace_child_invocations.py`
- `services/core/src/simorgh_core/agents/trace_reconciliation.py`
- `services/core/src/simorgh_core/agents/model_gateway.py`
- `services/core/src/simorgh_core/providers/avalai.py`
- `services/core/src/simorgh_core/providers/avalai_user_api.py`
- `services/core/tests/test_live_provider_staging_artifact.py`
- `services/core/tests/test_live_provider_staging_cli.py`
- `services/core/tests/test_live_provider_staging_workflow.py`
- `services/core/tests/test_trace_child_invocations.py`
- `.github/workflows/ci.yml`

Also inspect every PR #70 comment, review, changed file and check created after
`8ff42c2fb94c9342df59953725c96a8c04760dff`.

## Exact continuation point

First resolve the current branch Head and verify ordinary CI triggered by this
final Handoff update. If either Core or Android is not green, fix only that exact
failure before changing production code.

Then perform one narrow Phase 1.9 documentation and operational-readiness
increment without dispatching the live workflow:

- add an ADR for manual approval, protected environment, one-call/no-retry
  semantics, exact reconciliation and sanitized artifact authority;
- add an operator runbook covering environment/reviewer/secret setup, exact
  commit/model/cost review, dispatch, verification, result interpretation,
  duplicate-charge/unknown-invocation/cost-mismatch response, credential rotation
  and emergency disablement;
- add static tests keeping ADR/runbook and workflow controls synchronized;
- record which environment/reviewer/secret prerequisites cannot be proven from
  available repository APIs;
- prepare a precise live-acceptance checklist with exact commit, model and hard
  ceilings.

Do not dispatch `.github/workflows/live-provider-staging.yml`, use a credential
or make a real AvalAI/User API call without separate explicit user approval for
the exact commit, model and maximum spend. Update this Handoff with exact product
SHA and full Core/Android CI evidence when that increment is complete.
