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
- Lifecycle implementation Head:
  `395eaecd7617b260f1b0bd57a2f364a030aa74f5`
- Trace-link implementation Head:
  `40ac5c755cff50c60d4dda0f9ec7520d2f048961`
- Last exact owner-authored validation Head before this increment:
  `416af29624e48328c4ec28b2518587ab7ec41cc5`
- Cancellation/transport-uncertainty product Head:
  `7d11af47a0801b4593b6cf031bfaa49b247c0bb7`
- Completed substeps:
  - disabled-by-default AvalAI policy and sanitized User API boundary;
  - exactly-one-call fake canary composition;
  - immutable SQLite staging-result authority;
  - Core configuration, registry and lifespan ownership;
  - deterministic staging-result linkage to Invocation and Trace evidence;
  - durable sanitized cancellation and provider-transport uncertainty results.
- Next substep: make reconciliation disposition explicit as `exact`, `pending`,
  `unavailable` or `mismatch` without changing provider-call behavior.

The current Handoff commit is the branch `HEAD`; resolve its SHA from Git before
starting the next step. Do not insert an assumed self-referential SHA. The
immutable product SHA above and the exact CI run recorded below are the evidence
for this increment.

## Architecture and invariants

Simorgh remains authoritative for Task and Invocation identity, durable state,
budget, usage, replay, privacy and execution. Trace remains an immutable audit
projection and cannot authorize execution or rewrite Invocation truth.

The Phase 1.9 implementation preserves these invariants:

- live staging is disabled by default;
- a staging run permits at most one model request;
- no automatic retry, provider failover, streaming or tool use exists;
- exact replay checks durable staging authority before credit, model catalog,
  provider or User API entry;
- replay with the same staging/invocation identity adds zero model call, zero
  User API call and zero usage;
- InvocationStore state and committed usage remain source authority;
- Trace-linked staging reads fail closed if Invocation or terminal Trace evidence
  is missing, inconsistent or corrupt;
- cancellation never proves non-entry unless typed authority records that proof;
- reserved read-only work with proof of non-entry becomes `cancelled` with zero
  committed usage;
- cancellation or transport failure after possible provider entry becomes
  `unknown` with the conservative reservation committed once;
- a completed provider invocation stays `completed` if cancellation occurs only
  during transaction reconciliation;
- a cancellation outcome is durably claimed before `CancelledError` is
  re-raised;
- a staging result is returned only after its Invocation is terminal;
- raw prompt, model output, exception text, provider/User API body, header,
  credential, IP address and private account fields are never persisted.

## Completed cancellation and transport-uncertainty increment

### Typed result semantics

`LiveProviderReconciliationCode` now includes:

```text
provider_invocation_cancelled
```

The result contract enforces:

- `cancelled` Invocation state requires the cancellation code and zero usage;
- `unknown` Invocation state requires `provider_invocation_unknown`;
- the uncertainty code is valid only with `unknown` state;
- the cancellation code is valid only with `cancelled`, `unknown` or
  `completed` Invocation state;
- all reconciliation codes remain unique and canonically sorted.

### Runtime persistence

`LiveProviderStagingService` now:

- catches cancellation raised while the model gateway may be inside provider
  execution;
- reloads the durable terminal Invocation before constructing a result;
- records `cancelled` when adapter authority proves external non-entry;
- records `cancelled + unknown` when provider entry is possible;
- preserves the existing `unknown` transport-failure result and conservative
  committed usage;
- catches cancellation during transaction lookup after model completion and
  records an incomplete staging result while preserving completed Invocation
  truth and sanitized provider/output fingerprints;
- claims the immutable staging result synchronously before re-raising
  cancellation;
- refuses to persist a non-terminal Invocation or a model Invocation carrying
  `unknown_side_effect`.

### Durable replay and restart

The new acceptance coverage proves:

- a normal canary still completes;
- proof-of-non-entry cancellation stores zero usage and no external provider
  entry;
- cancellation after possible provider entry stores `unknown` and commits the
  reservation once;
- cancellation during transaction lookup preserves completed Invocation state;
- provider transport uncertainty survives SQLite close/reopen;
- exact replay after cancellation or transport uncertainty performs zero second
  provider call, zero model-catalog call, zero credit/transaction call and zero
  usage mutation;
- private transport markers are absent from serialized staging results.

## Files changed by this increment

The exact diff from previous Handoff Head
`e6089f16caf3f189e98bb1ce7cfa4e0aafeaf78c` to product Head
`7d11af47a0801b4593b6cf031bfaa49b247c0bb7` contains only:

- `docs/validation/phase-1-9-user-api-contract-candidate.md`
- `services/core/src/simorgh_core/agents/live_provider_staging.py`
- `services/core/src/simorgh_core/agents/live_provider_staging_contracts.py`
- `services/core/tests/test_live_provider_staging_uncertainty.py`

No transfer workflow, patcher, generated database, WAL/SHM file, process-lock
file, credential or other temporary artifact remains in the product diff.

## Validation state

Deterministic transfer and Core product gate:

```text
Product Head: 7d11af47a0801b4593b6cf031bfaa49b247c0bb7
Workflow: Phase 1.9 Staging Uncertainty Transfer
Run ID: 30773677111
Run number: 1
Conclusion: success
Ruff: all checks passed
strict MyPy: no issues in 81 source files
Core: 539 passed, 2 dependency warnings, 11.01s
focused cancellation/uncertainty tests: 5 passed
provider/User API/connector paid calls: zero
```

The ordinary CI created directly from the bot-authored product commit is:

```text
Run ID: 30773713271
Run number: 989
Conclusion: action_required
Jobs created: zero
```

This is a GitHub workflow-authorization state, not a Core or Android failure.
This owner-authored Handoff update must trigger ordinary CI against the product
tree above. Do not start the next production substep until both Core and Android
jobs on that owner-authored Head are green.

Previous exact Trace-link validation remains:

```text
Validated Head: 416af29624e48328c4ec28b2518587ab7ec41cc5
CI run ID: 30772631461
CI run number: 984
Core: success — 534 passed
Android: success — assembleDebug, JVM tests, lint and APK upload
```

## Security and failure semantics

- Cancellation exception content is discarded; only typed codes and terminal
  authority are stored.
- Provider transport exception content is discarded.
- A failed staging-store claim prevents cancellation propagation from being
  reported as successfully persisted; the store failure remains visible and no
  false durable result is asserted.
- `cancelled` with non-zero usage, `unknown` without uncertainty, and mismatched
  code/state combinations fail typed validation.
- Existing Trace linkage revalidates terminal state and committed usage on every
  claim, replay, lookup and restart load.
- No secret, credential, real AvalAI request or paid call was introduced or
  executed.

## Remaining risks and non-goals

The completed increment intentionally does not solve:

- cancellation before durable Invocation reservation; no staging result is
  claimed because no terminal Invocation authority exists;
- an explicit reconciliation-disposition field separating `exact`, `pending`,
  `unavailable` and `mismatch`;
- protected `workflow_dispatch` staging and secret injection;
- a real one-call AvalAI canary;
- operator approval UX and sanitized downloadable live report;
- production/autonomous enablement;
- Phase 1.10 workflows.

The current reconciliation codes still express multiple conditions as a tuple.
The next increment must introduce one authoritative disposition projection
without weakening or replacing the detailed codes.

## Remaining Phase 1.9 work

1. Make reconciliation disposition explicit (`exact`, `pending`,
   `unavailable`, `mismatch`).
2. Add the protected manual one-call staging workflow and sanitized artifact.
3. Execute one approved canary, reconcile exact transaction cost and prove
   replay creates no second request or charge.
4. Complete operational documentation, review audit and merge PR #70.

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
- `services/core/src/simorgh_core/providers/avalai_user_api.py`
- `services/core/tests/test_live_provider_staging.py`
- `services/core/tests/test_live_provider_staging_contracts.py`
- `services/core/tests/test_live_provider_staging_store.py`
- `services/core/tests/test_live_provider_staging_trace.py`
- `services/core/tests/test_live_provider_staging_uncertainty.py`
- `.github/workflows/ci.yml`

Also read every PR #70 comment, review, changed file and check created after
`7d11af47a0801b4593b6cf031bfaa49b247c0bb7`.

## Exact continuation point

First resolve the current branch Head and verify its ordinary CI. This Handoff
update is documentation-only; if either Core or Android is not green, inspect
and fix only that exact failure before changing production code.

Then implement one narrow Phase 1.9 increment that adds a typed, canonical
reconciliation disposition to every staging result:

```text
exact
pending
unavailable
mismatch
```

Derive it deterministically from existing transaction evidence and detailed
reconciliation codes. Preserve the detailed code tuple, immutable result hash,
Invocation/Trace authority, one-call ceiling, zero-call replay and current
cancellation/transport semantics. Add positive, pending, lookup-unavailable,
identity/usage/cost mismatch, corruption, SQLite restart and replay tests.

Do not add the protected live workflow, use credentials, make a real provider
request, alter provider retry behavior or begin Phase 1.10 in the same
increment. Update this Handoff with exact product SHA and CI evidence when that
single step is complete.
