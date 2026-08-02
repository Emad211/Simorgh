# Development Handoff

## Current snapshot

- Date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Base branch: `main`
- Working branch: `core/live-provider-staging`
- Merge base: `a76b5aee006a1ac9dfe54080d02cb54fceef8bde`
- Pull request: #70 — `Core: establish budgeted AvalAI staging policy and User API boundary`
- Issue: #65 — `Phase 1 Step 1.9: explicitly budgeted AvalAI live-provider staging`
- Phase: 1.9 — Live Provider Staging
- Verified lifecycle implementation Head:
  `395eaecd7617b260f1b0bd57a2f364a030aa74f5`
- Trace-link product implementation Head:
  `40ac5c755cff50c60d4dda0f9ec7520d2f048961`
- Exact owner-authored validation Head:
  `416af29624e48328c4ec28b2518587ab7ec41cc5`
- Completed substeps:
  - durable staging-result configuration, registry and Core lifespan;
  - deterministic staging-result linkage to correlated Trace identity and
    immutable invocation-terminal evidence.
- Next substep: durable sanitized cancellation and provider-transport
  uncertainty outcomes without a second provider request.

The current Handoff commit is the branch `HEAD`; resolve its SHA from Git before
starting the next step. Do not place an assumed self-referential SHA in this
file. The immutable product and validation SHAs above are the evidence for the
completed substep.

## Architecture and invariants

Simorgh remains authoritative for Task and Invocation identity, budget, durable
state, execution, privacy and replay. Trace is an immutable audit projection;
it does not authorize execution and billing evidence cannot rewrite Invocation
truth.

The completed Phase 1.9 foundations preserve these invariants:

- Core startup performs no provider, User API, connector or Android call;
- no credential is read or persisted by the staging-result authority;
- staging results contain sanitized typed metadata only;
- persistent Core stores have distinct filesystem identities;
- staging store candidates are validated before registry publication;
- startup failure releases SQLite process ownership;
- shutdown removes staging authority before Invocation authority;
- one staging result links only to its deterministic request Trace and fresh
  invocation-terminal event;
- InvocationStore remains the execution source of truth;
- missing, changed or corrupt Invocation/Trace evidence fails closed;
- exact replay performs durable local reads only and cannot create a second
  model or User API call;
- retained staging results protect their required Trace from pruning;
- raw prompt, model output, provider/User-API body, header, credential, IP
  address and private provider fields remain excluded.

## Completed lifecycle substep

- Added `SIMORGH_LIVE_PROVIDER_STAGING_RESULT_STORE_PATH` to Settings and
  `.env.example`.
- Added exact-path and hard-link alias rejection for staging-result storage.
- Added `LiveProviderStagingResultStoreRegistry` with validation-before-swap,
  replaced-store close and fresh-memory reset.
- Wired `SQLiteLiveProviderStagingResultStore` into Core startup, failure unwind
  and ordered shutdown.
- Added ten focused registry, path and lifespan tests.

Lifecycle evidence:

```text
Head: 395eaecd7617b260f1b0bd57a2f364a030aa74f5
CI run ID: 30771299238
CI run number: 972
Ruff: passed
strict MyPy: passed for 80 source files
Core: 530 passed, 2 dependency warnings
Android build/JVM/lint/APK: passed
```

## Completed deterministic Trace-link substep

- Added canonical `trace_id` and fresh invocation-terminal event identity to
  every `LiveProviderStagingResult`.
- Kept those identities outside the staging content hash because they are
  deterministic projections of existing request/invocation identities; strict
  validators reject inconsistent values.
- Added `live_provider_staging_trace_evidence()` to verify the exact native
  Invocation record and immutable terminal Trace event.
- Added `TraceLinkedLiveProviderStagingResultStore`, which validates every
  claim, replay, lookup, invocation lookup and load before returning authority.
- Validation checks request/invocation identity, model invocation kind,
  terminal state, committed usage, Trace event identity, stage, source kind,
  source-authority SHA-256, result-payload SHA-256 and fresh replay disposition.
- Added `LiveProviderStagingTraceProtection`, which extends existing Trace
  retention protection with request IDs referenced by durable staging results.
- Wired the raw SQLite staging store into retention protection and publishes
  only the Trace-linked wrapper through the process registry.
- Added positive, exact replay, missing/mismatched/tampered evidence, SQLite
  restart and retention-protection tests.
- Added no Trace event kind and did not turn Trace into source authority.

The exact increment from Handoff baseline
`ccdf59a7c5b4f96ce6cd628f3ec720cd3aa93fec` contains only these nine paths:

- `docs/DEVELOPMENT_HANDOFF.md`
- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `services/core/src/simorgh_core/agents/live_provider_staging.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_trace.py`
- `services/core/src/simorgh_core/app.py`
- `services/core/tests/test_live_provider_staging_lifespan.py`
- `services/core/tests/test_live_provider_staging_store.py`
- `services/core/tests/test_live_provider_staging_trace.py`

No transfer workflow, patcher, generated database, WAL/SHM file, credential or
other temporary artifact remains in the product diff.

## Verified Trace-link validation

Transfer validation and product publication:

```text
Product Head: 40ac5c755cff50c60d4dda0f9ec7520d2f048961
Workflow: Phase 1.9 Trace Link Transfer
Run ID: 30772525231
Run number: 8
Conclusion: success
Ruff: passed after 3 deterministic fixes
strict MyPy: no issues in 81 source files
Core: 534 passed, 2 dependency warnings
focused Trace-link tests: 4 passed
ordinary provider/User-API/connector calls: zero
```

The first ordinary CI created directly from the bot-authored product commit had
`action_required` with zero jobs (`30772569782`, run #983). That was a GitHub
workflow-authorization state, not a product failure. The same product tree was
then validated by an owner-authored Handoff commit.

Exact owner-authored validation:

```text
Validated Head: 416af29624e48328c4ec28b2518587ab7ec41cc5
Workflow: CI
Run ID: 30772631461
Run number: 984
Conclusion: success
core-quality: success
android-quality: success
Ruff: all checks passed
strict MyPy: no issues in 81 source files
Core: 534 passed, 2 dependency warnings, 12.65s
focused Trace-link tests: 4 passed
Android assembleDebug: passed
Android testDebugUnitTest: passed
Android lintDebug: passed
Android build: BUILD SUCCESSFUL, 53 actionable tasks
Debug APK upload: passed
```

Artifacts from run `30772631461`:

- `core-quality-diagnostics` — ID `8841014488`,
  SHA-256 `cee50c3236860401be7395eb4348af3c6032b831835ef77dd33845330224ab91`
- `core-test-report` — ID `8841014671`,
  SHA-256 `5579985007a3b4d26c80aee93b91c239241b20a8aba178804e378af589044ce3`
- `android-build-diagnostics` — ID `8841017620`,
  SHA-256 `62982634a125fb2e48e0abb95b544b019065f37a8978ffbc7d1bcbc27509516f`
- `simorgh-android-debug` — ID `8841017973`,
  SHA-256 `ad6aadfd44175c9aa802d4a42b503cff1b99b8ba5b7745c4ad78b30d4d4100eb`

No AvalAI model request, User API request, connector call, credential injection
or paid external call was introduced or executed by this increment.

## Explicit non-goals of the completed substep

The Trace-link increment did not add:

- cancellation-result persistence;
- a new reconciliation disposition contract;
- protected `workflow_dispatch` live staging;
- credential injection or a real AvalAI request;
- provider retry, failover, streaming or tool use;
- a public endpoint;
- Android actions;
- Phase 1.10 behavior.

## Remaining Phase 1.9 work

1. Persist sanitized cancellation and provider-transport uncertainty outcomes
   without a second provider request.
2. Make reconciliation disposition explicit (`exact`, `pending`,
   `unavailable`, `mismatch`).
3. Add the protected manual one-call staging workflow and sanitized artifact.
4. Execute one approved canary, reconcile exact transaction cost and prove
   replay creates no second request or charge.
5. Complete operational documentation, review audit and merge PR #70.

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
- `services/core/src/simorgh_core/agents/model_gateway.py`
- `services/core/src/simorgh_core/agents/invocations.py`
- `services/core/src/simorgh_core/agents/invocation_store.py`
- `services/core/src/simorgh_core/agents/trace_projecting_invocation_store.py`
- `services/core/tests/test_live_provider_staging.py`
- `services/core/tests/test_live_provider_staging_contracts.py`
- `services/core/tests/test_live_provider_staging_store.py`
- `services/core/tests/test_live_provider_staging_trace.py`
- `services/core/tests/test_budgeted_model_gateway.py`
- `services/core/tests/test_gateway_cancellation_settlement.py`
- `services/core/tests/test_cancellation_invocation_authority.py`
- `services/core/tests/test_cancellation_acceptance.py`
- `.github/workflows/ci.yml`

Also read every PR #70 comment, review, changed file and check created after
`416af29624e48328c4ec28b2518587ab7ec41cc5`.

## Exact continuation point

First verify the current branch Head and its ordinary CI. This Handoff evidence
update is documentation-only; if its exact CI is not green, inspect and resolve
only that failure before changing production code.

Then implement one narrow Phase 1.9 increment that persists a sanitized staging
result when cancellation or provider transport uncertainty occurs after durable
invocation reservation or possible provider entry. Preserve the existing
conservative Invocation state, never automatically retry the model, and ensure
replay with the same invocation identity performs zero second provider/User-API
call and adds zero usage. Add positive, cancellation-before-entry,
cancellation-after-possible-entry, transport-uncertainty, restart and replay
tests.

Do not change reconciliation-disposition semantics, add the protected live
workflow, use credentials, make a real provider call or start Phase 1.10 in the
same increment. Update this Handoff with exact SHA and CI evidence when that
single step is complete.
