# Phase 1.4 typed specialist results — validation record

- Status: Accepted implementation candidate
- Governing issue: #46
- Pull request: #48
- Branch: `core/typed-specialist-results`
- Validated implementation commit: `6af7f8d8ccb5e22c57dd8b0c50cfe6aa4e2a3e89`
- GitHub Actions run: `30216134239`
- Authority boundary: typed specialist result, evidence and artifact metadata persistence

## Validated scope

This increment validates the transition from the completed Phase 1.3 specialist invocation into one immutable Phase 1.4 result authority.

Included:

- exact result-schema/version registry;
- `simorgh.typed-plan.v1` / `SpecialistPlanPayload` family;
- immutable result identity and canonical SHA-256;
- artifact metadata and deterministic fake-byte integrity checks;
- evidence source, freshness, cache, citation and taint metadata;
- uncertainty and verification requirements;
- conservative privacy and retention composition;
- in-memory and SQLite WAL result stores;
- restart replay without a new specialist call or usage charge;
- cross-check against durable invocation payload and committed usage;
- deterministic Persian presentation outside authority fields;
- metadata-only result traces;
- Core lifespan and distinct-store-path integration.

Excluded:

- live provider/model calls;
- live GitHub or other connectors;
- mutation executors;
- public result API;
- production artifact-byte storage;
- MCP, Voice, Notification, Memory and new Android behavior.

## Automated evidence

### Core contract and persistence coverage

The exact validated implementation passed 317 Core tests. The result-specific slice proves:

- raw text and arbitrary dictionary payloads are rejected;
- duplicate/unknown schema registrations are rejected;
- canonical result hashing is stable;
- rendering cannot mutate authority identity;
- artifact size/hash/media/storage rules fail closed;
- evidence taint, freshness and artifact linkage survive persistence;
- strictest privacy and retention are propagated;
- in-memory replay returns one immutable result;
- SQLite restart replay returns identical result ID/hash;
- end-to-end Phase 1.3 → 1.4 replay does not re-enter the executor or add usage;
- changed payload or changed reference metadata conflicts;
- durable invocation mismatch prevents result creation;
- corrupt payload hash and unsupported schema fail closed;
- process ownership lock prevents concurrent SQLite authority;
- oversized/private payload markers remain absent from validation failures and traces;
- application startup loads the result store and shutdown resets it;
- result store path cannot alias task, invocation or Android action stores;
- extra/unregistered artifact shapes are rejected.

### Repository gates

Executed on GitHub Actions run `30216134239` for exact implementation commit `6af7f8d8ccb5e22c57dd8b0c50cfe6aa4e2a3e89`:

```text
ruff check .                                      PASS
mypy services/core/src                            PASS
pytest --junitxml=artifacts/junit.xml              PASS — 317 tests, 2 warnings
gradle :apps:android:assembleDebug                 PASS
gradle :apps:android:testDebugUnitTest             PASS
gradle :apps:android:lintDebug                     PASS
debug APK upload                                  PASS
```

The two warnings are upstream Starlette/FastAPI deprecations and did not alter test conclusions.

## Review and scope audit

- no unresolved inline review thread;
- no pending review submission;
- no temporary publisher workflow remains in the PR;
- all changed files belong to Phase 1.4 code, tests or documentation;
- ordinary CI used fake/local evidence and artifact data and made no live provider, connector or MCP call.

## Acceptance checklist

- [x] Ruff passed on exact implementation Head
- [x] strict MyPy passed on exact implementation Head
- [x] full Core pytest passed — 317 tests
- [x] Android build passed
- [x] Android JVM tests passed
- [x] Android lint passed
- [x] debug APK artifact produced
- [x] no unresolved review thread
- [x] ADR 0017 accepted
- [x] master plan and documentation synchronized
- [x] PR remains limited to Phase 1.4

Documentation-only successor commits remain subject to the same repository CI before merge. The PR body records the final merge-candidate Head and its exact final run after those commits complete.
