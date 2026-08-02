# Development Handoff

## Current snapshot

- Date: 2026-08-03
- Repository: `Emad211/Simorgh`
- Base branch: `main`
- Working branch: `core/live-provider-staging`
- Merge base: `a76b5aee006a1ac9dfe54080d02cb54fceef8bde`
- Source baseline: `33f4545cdc5ea22b62b8c3324eac0b4e6ef9df14`
- Latest implementation commit before this Handoff update:
  `d8a3de458279a8659c8ecb790c717fe322682f6e`
- Pull request: #70 — `Core: establish budgeted AvalAI staging policy and User API boundary`
- Issue: #65 — `Phase 1 Step 1.9: explicitly budgeted AvalAI live-provider staging`
- Phase: 1.9 — Live Provider Staging
- Substep: durable staging-result configuration, registry and Core lifespan

The current Handoff commit is the branch `HEAD`; resolve its SHA from Git before
starting the next step. Do not copy an assumed self-referential SHA into this
file.

## Architecture and invariants

Simorgh remains authoritative for Task and Invocation identity, budget, durable
state, execution, Trace, privacy and replay. Provider adapters cannot create
authority or trigger retry.

This substep preserves these invariants:

- Core startup performs no provider, User API, connector or Android call;
- no credential is read or persisted by the staging-result store;
- stored staging reports contain sanitized typed metadata only;
- all persistent Core stores must have distinct filesystem identities;
- a staging store is validated before registry publication;
- failed startup must release SQLite process ownership;
- shutdown removes staging authority before closing Invocation authority;
- Trace remains an audit projection and is not extended here.

## Completed in this substep

- Added `SIMORGH_LIVE_PROVIDER_STAGING_RESULT_STORE_PATH` to Settings and
  `.env.example`.
- Added exact-path and hard-link alias rejection for staging-result storage.
- Added `LiveProviderStagingResultStoreRegistry` with validation-before-swap,
  replaced-store close and fresh-memory reset.
- Wired `SQLiteLiveProviderStagingResultStore` into Core startup, failure unwind
  and ordered shutdown.
- Added ten focused registry, path and lifespan tests.
- Updated the Phase 1.9 validation record.

## Files changed

- `.env.example`
- `docs/DEVELOPMENT_HANDOFF.md`
- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `services/core/src/simorgh_core/config.py`
- `services/core/src/simorgh_core/app.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_store_registry.py`
- `services/core/tests/test_live_provider_staging_store_registry.py`
- `services/core/tests/test_live_provider_staging_settings_and_paths.py`
- `services/core/tests/test_live_provider_staging_lifespan.py`

## Validation state

Baseline CI run `30682318553` (`CI` run #963) passed on
`33f4545cdc5ea22b62b8c3324eac0b4e6ef9df14` with Core and Android jobs green.
It does not validate the new lifecycle increment.

The candidate Python files were syntax-checked before publication. Repository
Ruff, strict MyPy, full Core tests and Android gates must be taken only from the
GitHub Actions run attached to the current exact branch Head. Update this
section after that run completes; do not infer success from an earlier SHA.

## Explicit non-goals

This substep does not add a live workflow, secret injection, real AvalAI call,
provider retry/failover/streaming, Trace identity fields, cancellation-result
persistence, public endpoints, Android actions or Phase 1.10.

## Remaining Phase 1.9 work

After this exact Head is green:

1. link the staging result deterministically to correlated Trace identity and
   terminal event evidence;
2. persist sanitized cancellation and transport-uncertainty outcomes without a
   second provider request;
3. make reconciliation disposition explicit (`exact`, `pending`,
   `unavailable`, `mismatch`);
4. add the protected manual one-call staging workflow and sanitized artifact;
5. execute one approved canary, reconcile exact transaction cost and prove
   replay creates no second request or charge;
6. complete operational documentation, review audit and merge PR #70.

## Mandatory reads for the next execution

- `docs/DEVELOPMENT_HANDOFF.md`
- `docs/SIMORGH_MASTER_DIRECTIVE.md`
- `docs/IMPLEMENTATION_MASTER_PLAN.md`
- `docs/TRACE_AUTHORITY.md`
- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `docs/validation/phase-1-9-sqlite-staging-store-candidate.md`
- `services/core/src/simorgh_core/app.py`
- `services/core/src/simorgh_core/config.py`
- `services/core/src/simorgh_core/agents/live_provider_staging.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_store.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_sqlite_store.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_store_registry.py`
- `services/core/src/simorgh_core/agents/model_gateway.py`
- `services/core/tests/test_live_provider_staging_store_registry.py`
- `services/core/tests/test_live_provider_staging_settings_and_paths.py`
- `services/core/tests/test_live_provider_staging_lifespan.py`
- `.github/workflows/ci.yml`

Also read all PR #70 comments, reviews, changed files and checks created after
`33f4545cdc5ea22b62b8c3324eac0b4e6ef9df14`.

## Exact continuation point

First verify the current branch Head and its exact GitHub Actions run. If Core
or Android CI is not fully green, inspect the failing job logs and fix only
candidate-caused failures, then update this file. Once exact-head CI is green,
perform one review pass over the nine-file lifecycle increment and update this
Handoff with the verified SHA and run ID. Only then start the next Phase 1.9
substep: deterministic Trace linkage for the staging result. Do not start the
live-provider workflow or make a real provider call yet.
