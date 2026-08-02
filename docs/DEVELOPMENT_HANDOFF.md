# Development Handoff

## Current snapshot

- Date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Base branch: `main`
- Working branch: `core/live-provider-staging`
- Merge base: `a76b5aee006a1ac9dfe54080d02cb54fceef8bde`
- Source baseline: `33f4545cdc5ea22b62b8c3324eac0b4e6ef9df14`
- Verified lifecycle implementation Head:
  `395eaecd7617b260f1b0bd57a2f364a030aa74f5`
- Pull request: #70 — `Core: establish budgeted AvalAI staging policy and User API boundary`
- Issue: #65 — `Phase 1 Step 1.9: explicitly budgeted AvalAI live-provider staging`
- Phase: 1.9 — Live Provider Staging
- Completed substep: durable staging-result configuration, registry and Core
  lifespan
- Active substep: deterministic staging-result linkage to correlated Trace
  identity and terminal evidence

The current Handoff commit is the branch `HEAD`; resolve its SHA from Git before
starting the next step. Do not copy an assumed self-referential SHA into this
file.

## Architecture and invariants

Simorgh remains authoritative for Task and Invocation identity, budget, durable
state, execution, Trace, privacy and replay. Provider adapters cannot create
authority or trigger retry.

The completed lifecycle substep preserves these invariants:

- Core startup performs no provider, User API, connector or Android call;
- no credential is read or persisted by the staging-result store;
- stored staging reports contain sanitized typed metadata only;
- all persistent Core stores must have distinct filesystem identities;
- a staging store is validated before registry publication;
- failed startup releases SQLite process ownership;
- shutdown removes staging authority before closing Invocation authority;
- Trace remains an audit projection and was not extended by this substep.

## Completed in the lifecycle substep

- Added `SIMORGH_LIVE_PROVIDER_STAGING_RESULT_STORE_PATH` to Settings and
  `.env.example`.
- Added exact-path and hard-link alias rejection for staging-result storage.
- Added `LiveProviderStagingResultStoreRegistry` with validation-before-swap,
  replaced-store close and fresh-memory reset.
- Wired `SQLiteLiveProviderStagingResultStore` into Core startup, failure unwind
  and ordered shutdown.
- Added ten focused registry, path and lifespan tests.
- Updated the Phase 1.9 validation record.
- Reviewed the exact nine-path diff from the source baseline; no unrelated file,
  workflow, credential or generated durable artifact entered the increment.

## Files changed by the lifecycle increment

- `.env.example`
- `docs/DEVELOPMENT_HANDOFF.md`
- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `services/core/src/simorgh_core/config.py`
- `services/core/src/simorgh_core/app.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_store_registry.py`
- `services/core/tests/test_live_provider_staging_store_registry.py`
- `services/core/tests/test_live_provider_staging_settings_and_paths.py`
- `services/core/tests/test_live_provider_staging_lifespan.py`

## Verified validation

Exact implementation Head:

```text
395eaecd7617b260f1b0bd57a2f364a030aa74f5
```

GitHub Actions:

```text
workflow: CI
run ID: 30771299238
run number: 972
core-quality: success
android-quality: success
```

Core evidence:

```text
Ruff: all checks passed
strict MyPy: no issues in 80 source files
pytest: 530 passed, 2 dependency deprecation warnings, 11.53s
focused lifecycle tests included: 10 passed
```

Android evidence:

```text
assembleDebug: passed
testDebugUnitTest: passed
lintDebug: passed
Gradle: BUILD SUCCESSFUL, 53 actionable tasks
Debug APK upload: passed
```

Artifacts attached to run 30771299238:

- `core-quality-diagnostics` — ID `8840616381`
- `core-test-report` — ID `8840616614`
- `android-build-diagnostics` — ID `8840618168`
- `simorgh-android-debug` — ID `8840618358`

No AvalAI model request, User API request, connector call, live secret injection
or paid external call was introduced or executed by this increment.

The Handoff evidence update is documentation-only and creates a newer branch
Head. Verify that current Head and its ordinary CI before changing production
code; use the lifecycle implementation Head and run above as the immutable
product-validation evidence.

## Explicit non-goals

The completed substep did not add a live workflow, secret injection, real
AvalAI call, provider retry/failover/streaming, Trace identity fields,
cancellation-result persistence, public endpoints, Android actions or Phase
1.10.

## Remaining Phase 1.9 work

1. Link the staging result deterministically to correlated Trace identity and
   terminal event evidence.
2. Persist sanitized cancellation and transport-uncertainty outcomes without a
   second provider request.
3. Make reconciliation disposition explicit (`exact`, `pending`,
   `unavailable`, `mismatch`).
4. Add the protected manual one-call staging workflow and sanitized artifact.
5. Execute one approved canary, reconcile exact transaction cost and prove
   replay creates no second request or charge.
6. Complete operational documentation, review audit and merge PR #70.

## Mandatory reads for the next execution

- `docs/DEVELOPMENT_HANDOFF.md`
- `docs/SIMORGH_MASTER_DIRECTIVE.md`
- `docs/IMPLEMENTATION_MASTER_PLAN.md`
- `docs/TRACE_AUTHORITY.md`
- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `docs/validation/phase-1-9-sqlite-staging-store-candidate.md`
- `services/core/src/simorgh_core/agents/live_provider_staging.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_store.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_sqlite_store.py`
- `services/core/src/simorgh_core/agents/model_gateway.py`
- `services/core/src/simorgh_core/agents/trace_contracts.py`
- `services/core/src/simorgh_core/agents/trace_projection.py`
- `services/core/src/simorgh_core/agents/trace_store.py`
- `services/core/src/simorgh_core/agents/sqlite_trace_store.py`
- `services/core/tests/test_live_provider_staging.py`
- `services/core/tests/test_live_provider_staging_contracts.py`
- `services/core/tests/test_live_trace_projection_prefixes.py`
- `services/core/tests/test_request_trace_projection.py`
- `.github/workflows/ci.yml`

Also read every PR #70 comment, review, changed file and check created after
`395eaecd7617b260f1b0bd57a2f364a030aa74f5`.

## Trace-link candidate in this commit

- Adds canonical `trace_id` and invocation-terminal event identity to every
  staging result without changing its content-addressed result identity.
- Validates every published staging-result store read/write against exact
  Invocation and immutable Trace authority.
- Protects traces referenced by durable staging results from retention
  pruning.
- Adds positive, replay, mismatch/tamper and SQLite restart coverage.

This candidate has not yet passed the exact resulting-head CI. The next
execution must verify that CI and update this file with the product SHA, run
ID, test counts and artifact IDs before starting cancellation durability.

## Exact continuation point

First verify the current branch Head and its ordinary CI. If the Trace-link
candidate is not fully green, inspect and fix only candidate-caused failures.
Once its exact Head passes Core and Android gates, update this Handoff with
the verified SHA and CI evidence. Then start only the next Phase 1.9 substep:
persist sanitized cancellation and transport-uncertainty outcomes without a
second provider request. Do not start reconciliation-disposition changes, the
protected live workflow or a real provider call in the same increment.

<!-- Previous continuation rationale retained below for audit. -->

First verify the current branch Head and its ordinary CI, then audit how
`LiveProviderStagingResult`, `BudgetedModelGateway` and the request Trace
projector currently correlate Task, Invocation and terminal events. Implement
one narrow Phase 1.9 increment that gives every persisted staging result a
deterministic, validated link to the correlated Trace identity and terminal
evidence without turning Trace into source authority and without storing raw
prompt, output, provider body, header, credential or private User API fields.
Add positive, replay, mismatch/corruption and restart tests; run Ruff, strict
MyPy, the full Core suite and Android gates; update this Handoff with exact SHA
and CI evidence. Do not address cancellation durability, reconciliation
disposition, the protected live workflow or a real provider call in that same
increment.
