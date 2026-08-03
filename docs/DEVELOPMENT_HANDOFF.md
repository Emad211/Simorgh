# Development Handoff

## Current snapshot

- Date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Base branch: `main`
- Working branch: `core/live-provider-staging`
- Merge base: `a76b5aee006a1ac9dfe54080d02cb54fceef8bde`
- Pull request: #70 — `Core: establish budgeted AvalAI staging policy and User API boundary`
- Pull request state: open, Draft and currently mergeable
- Issue: #65 — `Phase 1 Step 1.9: explicitly budgeted AvalAI live-provider staging`
- Phase: 1.9 — Live Provider Staging
- Lifecycle implementation Head:
  `395eaecd7617b260f1b0bd57a2f364a030aa74f5`
- Trace-link implementation Head:
  `40ac5c755cff50c60d4dda0f9ec7520d2f048961`
- Cancellation/transport-uncertainty implementation Head:
  `7d11af47a0801b4593b6cf031bfaa49b247c0bb7`
- Reconciliation-disposition product Head:
  `50b1484d9113951f15a1fc060d58f13896f52a9e`
- Exact owner-authored validation Head for this increment:
  `aadee09fdf76e66a54a6149a5dfcf5d813916b48`
- Completed substeps:
  - disabled-by-default AvalAI policy and sanitized User API boundary;
  - exactly-one-call fake canary composition;
  - immutable SQLite staging-result authority;
  - Core configuration, registry and lifespan ownership;
  - deterministic staging-result linkage to Invocation and Trace evidence;
  - durable sanitized cancellation and provider-transport uncertainty results;
  - typed canonical reconciliation disposition.
- Next substep: protected manual staging workflow, dedicated composition entry
  and sanitized validation artifact, without dispatching a real canary yet.

The current Handoff commit is the branch `HEAD`; resolve its SHA from Git before
starting the next execution. Do not place an assumed self-referential SHA in this
file. The immutable product and exact validation SHAs above are the source of
truth for the completed increment.

## Architecture and invariants

Simorgh remains authoritative for Task and Invocation identity, durable state,
budget, usage, replay, privacy and execution. Trace remains an immutable audit
projection and cannot authorize execution or rewrite Invocation truth.

The Phase 1.9 implementation preserves these invariants:

- live staging is disabled by default;
- one staging run permits at most one model request;
- no automatic retry, provider failover, streaming or tool use exists;
- exact replay checks durable staging-result authority before credit, model
  catalog, provider or User API entry;
- replay with the same staging and invocation identity adds zero model call,
  zero User API call and zero usage;
- InvocationStore state and committed usage remain source authority;
- Trace-linked staging reads fail closed if Invocation or terminal Trace evidence
  is missing, inconsistent or corrupt;
- billing reconciliation evidence cannot rewrite Invocation truth;
- cancellation never proves non-entry unless typed authority records that proof;
- reserved read-only work with proof of non-entry becomes `cancelled` with zero
  committed usage;
- cancellation or transport failure after possible provider entry becomes
  `unknown` with the conservative reservation committed once;
- a completed provider invocation remains `completed` if cancellation happens
  only during transaction lookup;
- raw prompt, model output, exception text, provider/User API body, header,
  credential, IP address and private account fields are never persisted;
- ordinary CI remains fake and zero-external.

## Completed canonical reconciliation-disposition increment

### Typed projection

Every `LiveProviderStagingResult` now carries exactly one canonical typed value:

```text
exact
pending
unavailable
mismatch
```

The projection is deterministically derived from transaction presence and the
canonical detailed `reconciliation_codes` tuple:

- `exact` requires a retained exact transaction and no reconciliation code;
- `pending` requires no transaction and exactly `transaction_pending`;
- `unavailable` covers provider cancellation, provider failure, provider
  uncertainty, missing/invalid provider request identity and unavailable User
  API lookup;
- `mismatch` takes precedence when output, request identity, model, provider,
  status, stream, usage or cost evidence conflicts.

Mixed pending/unavailable evidence, transaction-plus-unavailable evidence,
duplicate codes, unclassified codes and missing evidence fail closed.

### Canonical identity and contract enforcement

- `reconciliation_disposition` is included in the staging-result canonical
  SHA-256 and stable result identity.
- Internal candidate construction may omit the derived field, but any supplied
  value must equal the deterministic projection.
- A changed disposition with a recomputed storage payload hash still fails typed
  validation and SQLite load treats it as corruption.
- Detailed reconciliation codes remain authoritative diagnostic evidence and
  are not replaced by the projection.
- Added `transaction_request_mismatch` as a typed detailed code.
- A transaction whose identity differs from the provider request ID is retained
  only as an explicit `mismatch`; it is no longer an untyped validation failure.

### Runtime composition

`LiveProviderStagingService` now:

- passes the captured provider request identity into exact transaction
  reconciliation;
- records request/model/provider/status/stream/usage/cost mismatches as detailed
  codes;
- derives the canonical reconciliation disposition before claiming the immutable
  result;
- preserves all existing one-call, cancellation, uncertainty and replay
  semantics.

No provider-call path, transaction-polling policy, retry behavior, credential
boundary, Trace authority or Invocation transition changed in this increment.

## Files changed by this increment

The exact product diff from previous Handoff Head
`874b675c16c1d1c71af4a4d58a8f7eac4738bbdd` to product Head
`50b1484d9113951f15a1fc060d58f13896f52a9e` contains only:

- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `services/core/src/simorgh_core/agents/live_provider_staging.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`
- `services/core/tests/test_live_provider_staging.py`
- `services/core/tests/test_live_provider_staging_reconciliation.py`

The owner-authored validation commit changes only this Handoff. No transfer
workflow, patcher, generated database, WAL/SHM file, process-lock file,
credential or other temporary artifact remains in the product diff.

## Validation evidence

An initial transfer run reached 550 passing tests and one test-only expectation
failure. It published no product commit. The fixture was corrected so the test
reaches the intended request-identity invariant.

Deterministic transfer and Core product gate:

```text
Product Head: 50b1484d9113951f15a1fc060d58f13896f52a9e
Workflow: Phase 1.9 Reconciliation Disposition Transfer
Run ID: 30774528624
Run number: 2
Conclusion: success
Ruff: all checks passed
strict MyPy: no issues in 81 source files
Core: 551 passed, 2 dependency warnings, 11.87s
focused reconciliation-disposition tests: 12 passed
provider/User API/connector paid calls: zero
```

The ordinary CI created directly from the bot-authored product commit was:

```text
Run ID: 30774559050
Run number: 996
Conclusion: action_required
Jobs created: zero
```

This was a GitHub workflow-authorization state, not a Core or Android product
failure. The same product tree was then validated through an owner-authored
Handoff commit.

Exact owner-authored full validation:

```text
Validated Head: aadee09fdf76e66a54a6149a5dfcf5d813916b48
Workflow: CI
Run ID: 30774611110
Run number: 997
Conclusion: success
core-quality: success
android-quality: success
Ruff: all checks passed
strict MyPy: no issues in 81 source files
Core: 551 passed, 2 dependency warnings, 11.46s
focused reconciliation-disposition tests: 12 passed
Android assembleDebug: passed
Android testDebugUnitTest: passed
Android lintDebug: passed
Android build: BUILD SUCCESSFUL in 19s, 53 actionable tasks
Debug APK upload: passed
ordinary live provider/User API calls: zero
```

Artifacts from run `30774611110`:

- `core-quality-diagnostics` — ID `8841597153`,
  SHA-256 `ad1c83dda3946830525d0c5df6e8ac1e004631f3a2fb87482d6e5e14e291120e`
- `core-test-report` — ID `8841597284`,
  SHA-256 `140224124bbef4d5f713a701b36a7e9722702c8797886de595c99deb122271a3`
- `android-build-diagnostics` — ID `8841598978`,
  SHA-256 `59af55c5fe557e177a306b087fa64133968a10ed289725a1ef241a4b180cab72`
- `simorgh-android-debug` — ID `8841599192`,
  SHA-256 `079f354252ab5547d22c7c8d833f9ab5cbb56732511bf148b5186cb5fc006aee`

Previous exact validation evidence remains retained in Git history and earlier
Handoff revisions.

## Test coverage added or extended

The increment covers:

- deterministic `exact`, `pending`, `unavailable` and `mismatch` derivation;
- rejection of missing evidence and conflicting pending/unavailable evidence;
- canonical hash participation and changed-projection rejection;
- request-identity mismatch typing;
- model, provider, usage and cost mismatch aggregation;
- service-level exact, pending, lookup-unavailable, mismatch and transport
  uncertainty projections;
- SQLite close/reopen and exact replay;
- SQLite rejection of rehashed disposition corruption;
- preservation of the detailed code tuple and zero-call replay behavior.

## Security and failure semantics

- The disposition is a projection, not execution or billing authority.
- Exact cost remains transaction evidence for staging reconciliation only.
- Local committed usage remains Invocation/request-budget authority.
- `mismatch` has precedence over unavailable evidence so a known conflict cannot
  be hidden as mere absence.
- `pending` cannot be combined with unavailable evidence.
- Request identity mismatch is explicit and privacy-safe.
- No raw transaction body or private provider field is introduced.
- No credential, real AvalAI request, paid call or live environment was used.

## Remaining Phase 1.9 work

1. Add the protected manual one-call staging workflow, dedicated CLI/composition
   entry and schema-validated sanitized JSON artifact.
2. Execute one explicitly approved real canary, reconcile exact transaction cost
   and prove replay creates no second request or charge.
3. Complete ADR and operational documentation, perform review audit and merge
   PR #70.

## Explicit non-goals still in force

- no live provider in ordinary CI;
- no production or autonomous live-model enablement;
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
- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `services/core/src/simorgh_core/agents/live_provider_staging.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_store.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_sqlite_store.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_trace.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_store_registry.py`
- `services/core/src/simorgh_core/agents/model_gateway.py`
- `services/core/src/simorgh_core/providers/avalai.py`
- `services/core/src/simorgh_core/providers/avalai_user_api.py`
- `services/core/src/simorgh_core/config.py`
- `services/core/src/simorgh_core/app.py`
- `services/core/tests/test_live_provider_staging.py`
- `services/core/tests/test_live_provider_staging_contracts.py`
- `services/core/tests/test_live_provider_staging_store.py`
- `services/core/tests/test_live_provider_staging_trace.py`
- `services/core/tests/test_live_provider_staging_uncertainty.py`
- `services/core/tests/test_live_provider_staging_reconciliation.py`
- `.github/workflows/ci.yml`

Also read every PR #70 comment, review, changed file and check created after
`aadee09fdf76e66a54a6149a5dfcf5d813916b48`.

## Exact continuation point

First resolve the current branch Head and verify the ordinary CI triggered by
this final Handoff evidence update. If either Core or Android is not green,
inspect and fix only that exact failure before changing production code.

Once exact-head CI is green, implement one narrow Phase 1.9 increment for the
manual staging execution boundary without making the real paid canary request:

- add a dedicated staging CLI/composition entry that uses the existing policy,
  BudgetedModelGateway, InvocationStore, Trace and staging-result authority;
- add a strict versioned sanitized JSON artifact contract and deterministic
  writer/verifier;
- add a dedicated `workflow_dispatch` workflow only;
- bind live steps to the protected `live-provider-staging` environment;
- reference `AVALAI_API_KEY` only in the protected live step environment;
- enforce one concurrency group, `max_model_calls=1`, fixed Core-authored canary,
  reviewed model/base URLs and no provider retry/failover;
- run Ruff, strict MyPy and fake targeted tests before the protected secret step;
- scan and reject prompt/output, credentials, headers, IP addresses, API-key
  suffixes, cookies, raw responses and environment dumps from the artifact;
- add static workflow tests proving there is no push, pull_request or schedule
  trigger and ordinary CI cannot invoke live staging.

The workflow may be committed and statically validated, but do not dispatch it,
use a credential or execute a real AvalAI request in that same increment. Update
this Handoff with exact product SHA and full Core/Android CI evidence when the
single boundary is complete.
