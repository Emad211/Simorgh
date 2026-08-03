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
- Lifecycle implementation Head:
  `395eaecd7617b260f1b0bd57a2f364a030aa74f5`
- Trace-link implementation Head:
  `40ac5c755cff50c60d4dda0f9ec7520d2f048961`
- Cancellation/transport-uncertainty implementation Head:
  `7d11af47a0801b4593b6cf031bfaa49b247c0bb7`
- Reconciliation-disposition implementation Head:
  `50b1484d9113951f15a1fc060d58f13896f52a9e`
- Protected manual staging-boundary product Head:
  `8ff42c2fb94c9342df59953725c96a8c04760dff`
- Last exact owner-authored validation Head before this increment:
  `acf32cb1f498e2a49835f7b44e28c046a91adbbc`
- Completed substeps:
  - disabled-by-default AvalAI policy and sanitized User API boundary;
  - exactly-one-call fake canary composition;
  - immutable SQLite staging-result authority;
  - Core configuration, registry and lifespan ownership;
  - deterministic staging-result linkage to Invocation and Trace evidence;
  - durable sanitized cancellation and provider-transport uncertainty results;
  - typed canonical reconciliation disposition;
  - protected manual CLI/workflow and sanitized artifact boundary.
- Next substep after exact-head CI: complete the staging ADR, operator runbook and
  protected-environment readiness audit. Do not dispatch the live workflow until
  the user explicitly approves the exact commit, model and maximum spend.

The current Handoff commit is the branch `HEAD`; resolve its SHA from Git before
starting the next execution. Never write an assumed self-referential SHA. The
immutable product SHA above and exact CI evidence below are authoritative for
this increment.

## Architecture and invariants

Simorgh remains authoritative for Task and Invocation identity, durable state,
budget, usage, replay, privacy and execution. Trace remains an immutable audit
projection and cannot authorize execution or rewrite Invocation truth.

Phase 1.9 continues to preserve these invariants:

- live staging is disabled for ordinary runtime and ordinary CI;
- one staging run permits at most one model request;
- no automatic retry, provider/model/domain failover, streaming or tool use;
- fixed Core-authored input only, with no user/conversation/project content;
- exact replay checks durable staging authority before credit, catalog, provider
  or User API entry;
- replay adds zero model call, zero User API call and zero usage;
- InvocationStore state and committed usage remain source authority;
- exact provider cost is billing evidence for staging only;
- Trace-linked reads fail closed if Invocation or terminal Trace evidence is
  missing, inconsistent or corrupt;
- cancellation and transport uncertainty remain conservative and durable;
- raw prompt, output, exception text, headers, credentials, IP addresses and raw
  provider/User API bodies are never persisted or uploaded;
- the protected workflow cannot be triggered by push, pull request, schedule,
  API endpoint or model output.

## Completed protected manual execution boundary

### Native Task and specialist authority

A new explicit internal task kind and reviewed specialist definition were added:

```text
TaskKind.LIVE_PROVIDER_STAGING
system.live-provider-staging@1.0.0
```

The specialist has:

- read-only/no-side-effect policy;
- no tool or connector allowlist;
- FAST-tier model policy only;
- exactly one model-call ceiling;
- zero retries and one parallel branch;
- bounded input/output token, cost and elapsed-time ceilings.

The CLI first submits a fixed read-only `TaskEnvelope` through the existing
`AgentTaskControlPlane`. The task has no wall-clock deadline; the reviewed
60-second ceiling remains authoritative inside `TaskBudget`, avoiding clock
skew between test/workflow callers and the durable control plane.

### Direct routed Invocation Trace support

Trace reconciliation now projects root model/tool invocations owned directly by
the exact routed specialist. A direct root is eligible only when:

- request identity matches the durable task;
- invocation kind is model or tool;
- parent invocation and cancellation owner are absent;
- agent ID and version exactly match the durable `RoutingDecision`;
- the invocation is not the router classifier invocation.

The invocation start is parented to the routing event and its terminal evidence
uses the existing Invocation authority. Unrelated root invocations are ignored.
This is a generic governed runtime capability; no staging code manufactures or
writes Trace events directly.

### Dedicated composition CLI

`services/core/src/simorgh_core/agents/live_provider_staging_cli.py` provides:

```text
python -m simorgh_core.agents.live_provider_staging_cli run ...
python -m simorgh_core.agents.live_provider_staging_cli verify ...
```

The run command:

1. validates exact reviewed AvalAI API/User API URLs and the single reviewed
   model ID;
2. enters the existing Core lifespan;
3. submits and routes the fixed staging TaskEnvelope;
4. reuses the existing Task, Invocation, Trace and staging-result authorities;
5. runs `LiveProviderStagingService` through `BudgetedModelGateway`;
6. validates terminal Invocation/Trace evidence;
7. executes the identical staging identity again to prove durable replay;
8. records external-call and committed-usage deltas;
9. emits only a strict sanitized artifact.

Provider and User API wrappers count bounded operations only. They do not grant
execution authority or modify provider behavior. `AvalAIProvider` now exposes an
explicit async `close()` so the protected CLI releases its SDK HTTP client.

### Versioned sanitized artifact

`LiveProviderStagingArtifact` is strict, frozen and versioned. It contains only:

- source commit and workflow metadata;
- staging/request/invocation IDs;
- the already-sanitized staging result;
- validated terminal Trace evidence;
- bounded first-run call counts;
- replay external-call deltas;
- committed usage before and after replay;
- typed pass/failure disposition;
- canonical SHA-256 and deterministic artifact UUID.

A passing artifact requires:

- an exact completed reconciliation result;
- valid terminal Invocation and Trace evidence;
- exactly one model request on the first run;
- one catalog and credit preflight;
- at least one bounded transaction lookup;
- replay of the same immutable result identity;
- zero provider/catalog/credit/transaction calls during replay;
- zero committed-usage mutation during replay.

The artifact writer uses canonical JSON, a one-megabyte ceiling, atomic replace
and file mode `0600`. Verification reparses the strict contract and revalidates
its hash and identity.

The privacy scanner rejects the fixed canary strings, authorization/bearer/API
key/cookie/header/IP/safety/raw-response/environment-dump markers and the exact
runtime credential value supplied only in process memory.

### Manual protected GitHub workflow

`.github/workflows/live-provider-staging.yml` has only `workflow_dispatch` and:

- requires an exact reviewed 40-character commit SHA;
- requires that input SHA equal the workflow dispatch SHA and checkout SHA;
- offers only the reviewed `gpt-5.4-mini` model choice;
- uses one non-cancelling repository concurrency group;
- has read-only repository permissions;
- pins every action to a full commit SHA;
- installs exact constrained direct dependency versions;
- runs Ruff, strict MyPy and fake acceptance before any secret boundary;
- binds the live job to the `live-provider-staging` environment;
- references `AVALAI_API_KEY` exactly once, only in the protected execution step;
- uses isolated temporary SQLite authorities;
- verifies the artifact schema/hash/privacy contract;
- uploads only the sanitized JSON artifact with 30-day retention.

The workflow was committed and statically tested but was **not dispatched** in
this increment. No environment secret was read and no real AvalAI or User API
request was made.

Repository code cannot prove that the GitHub environment, required reviewers or
environment secret are configured. Those remain operator prerequisites before
any approved live acceptance run.

## Files changed by this increment

The exact product diff from previous Handoff Head
`acf32cb1f498e2a49835f7b44e28c046a91adbbc` to product Head
`8ff42c2fb94c9342df59953725c96a8c04760dff` contains exactly these 14 paths:

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

No transfer workflow, patcher, generated database, WAL/SHM file, process-lock
file, credential or temporary diagnostic artifact remains in the product diff.

## Test coverage

This increment adds 13 tests:

- four artifact contract/privacy/tamper tests;
- two zero-network native CLI composition/replay tests;
- six static protected-workflow boundary tests;
- one direct routed root Invocation Trace test.

Coverage proves:

- artifact round-trip, mode, canonical identity and tamper rejection;
- forbidden canary and exact-secret marker rejection;
- success cannot be claimed without exact result, Trace and replay evidence;
- fake composition uses the native lifespan and durable authorities;
- first run performs one model request and replay performs zero external calls;
- incomplete reconciliation remains typed and never retries the model;
- unrelated root invocations are excluded from Trace;
- workflow has no push/pull-request/schedule trigger;
- secret appears only after pre-secret quality gates in the protected job;
- exact commit/model/action/dependency pinning remains enforced;
- ordinary CI cannot invoke the live CLI or reference its credential.

## Validation evidence

Deterministic transfer and Core product gate:

```text
Product Head: 8ff42c2fb94c9342df59953725c96a8c04760dff
Workflow: Phase 1.9 Direct Routed Trace Transfer
Run ID: 30776688407
Run number: 7
Conclusion: success
Ruff: all checks passed
strict MyPy: no issues in 83 source files
Core: 564 passed, 2 dependency warnings, 12.66s
real provider/User API calls: zero
live workflow dispatches by this implementation: zero
```

The ordinary CI generated directly from the bot-authored product commit is:

```text
Run ID: 30776723861
Run number: 1024
Conclusion: action_required
Jobs created: zero
```

This is GitHub workflow authorization behavior for the bot-authored commit, not
a Core or Android product failure. This owner-authored Handoff commit must
trigger full ordinary CI against the same product tree. Do not proceed to the
next production substep unless both Core and Android jobs on that exact Head are
green.

Previous exact owner-authored validation remains:

```text
Validated Head: acf32cb1f498e2a49835f7b44e28c046a91adbbc
CI run ID: 30774703671
CI run number: 998
Core: success — 551 passed
Android: success — assembleDebug, JVM tests, lint and APK upload
```

## Security and failure semantics

- Missing credentials, URL/model mismatch or preflight failure fails before
  provider entry.
- CLI error output is fixed and sanitized; exception text is not printed.
- A failed run may produce only a typed failed artifact and the workflow exits
  nonzero unless a fully passed artifact verifies.
- Exact input SHA must equal the dispatch commit and checkout commit.
- `AVALAI_API_KEY` is not available to the pre-secret job.
- Workflow actions and direct dependencies are pinned.
- Failed artifact verification or missing artifact causes workflow failure.
- No public API endpoint or autonomous execution path was introduced.
- Existing cancellation, uncertainty, no-retry and replay semantics are unchanged.

## Remaining Phase 1.9 work

1. Add the staging ADR and complete the operator runbook for environment setup,
   review/approval, dispatch, interpretation, incident response, credential
   rotation and emergency disablement.
2. Audit the exact final commit and verify the protected GitHub environment,
   required reviewer and `AVALAI_API_KEY` environment secret are configured.
3. Obtain explicit user approval for the exact commit, reviewed model and hard
   maximum spend.
4. Dispatch one approved live canary, validate its sanitized artifact, reconcile
   exact transaction cost and prove zero-call/zero-charge replay.
5. Complete review audit and merge PR #70.

## Explicit non-goals still in force

- no live dispatch without explicit user approval;
- no live provider in ordinary CI;
- no production/autonomous live-model enablement;
- no public model endpoint;
- no automatic or scheduled live test;
- no provider/model/domain failover;
- no streaming, multimodal, tools or batch validation;
- no raw prompt/output/provider/User API body persistence;
- no Android mutation;
- no Phase 1.10 workflow;
- no Voice, Notification, Scheduling, Channels, Delegation, MCP, Memory,
  Personal Work Graph or self-improvement.

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
- `services/core/src/simorgh_core/agents/live_provider_staging_store.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_sqlite_store.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_trace.py`
- `services/core/src/simorgh_core/agents/trace_child_invocations.py`
- `services/core/src/simorgh_core/agents/trace_reconciliation.py`
- `services/core/src/simorgh_core/agents/model_gateway.py`
- `services/core/src/simorgh_core/providers/avalai.py`
- `services/core/src/simorgh_core/providers/avalai_user_api.py`
- `services/core/tests/test_live_provider_staging.py`
- `services/core/tests/test_live_provider_staging_artifact.py`
- `services/core/tests/test_live_provider_staging_cli.py`
- `services/core/tests/test_live_provider_staging_reconciliation.py`
- `services/core/tests/test_live_provider_staging_uncertainty.py`
- `services/core/tests/test_live_provider_staging_workflow.py`
- `services/core/tests/test_trace_child_invocations.py`
- `.github/workflows/ci.yml`

Also inspect every PR #70 comment, review, changed file and check created after
`8ff42c2fb94c9342df59953725c96a8c04760dff`.

## Exact continuation point

First resolve the current branch Head and verify ordinary CI triggered by this
Handoff update. If either Core or Android is not green, inspect and fix only that
exact failure before changing production code.

Once exact-head CI is green, perform one narrow Phase 1.9 documentation and
operational-readiness increment without dispatching the live workflow:

- add an ADR for the manually approved one-call AvalAI boundary, protected
  environment, no-retry uncertainty semantics, exact transaction reconciliation
  and sanitized artifact authority;
- add an operator runbook covering protected environment creation, optional or
  required reviewer setup, environment-secret creation, exact commit/model/cost
  review, manual dispatch, artifact verification, result interpretation,
  suspected duplicate charge, unknown Invocation, cost mismatch, credential
  rotation and emergency workflow disablement;
- add static tests that keep the ADR/runbook and workflow controls synchronized;
- inspect whether the repository connector can prove environment/reviewer/secret
  configuration; record unprovable operator prerequisites without inventing
  evidence;
- prepare a precise live-acceptance checklist containing the exact commit,
  reviewed model and hard ceilings.

Do not dispatch `.github/workflows/live-provider-staging.yml`, use a credential
or make any real AvalAI/User API call without a separate explicit user approval
for the exact commit, model and maximum spend. Update this Handoff with exact
product SHA and full Core/Android CI evidence when that documentation/readiness
increment is complete.
